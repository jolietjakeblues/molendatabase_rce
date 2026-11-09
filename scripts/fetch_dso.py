"""Omgevingsplannen (DSO, Omgevingsdocumenten presenteren v8) raadplegen voor molens zonder zone in een bestemmingsplan.

Per molen met zonestatus Nee of Onbekend (data/zones.json): welke omgevingsplannen en voorbeschermingsregels gelden op het molenpunt
(POST /regelingen/_zoek met een punt), en wat leveren hun annotaties op dat punt (POST .../regeltekstannotaties/_zoek):
locaties, activiteiten, regels. Een molenbiotoopzone zou hier als locatie of aanwijzing met 'molenbiotoop' in de naam terugkomen.

Vereist DSO_API_KEY in .env (of als omgevingsvariabele); de sleutel wordt nooit weggeschreven of geprint. Alleen lezen.
Invoer : data/zones.json, data/rce_raw.json
Uitvoer: data/dso_scan.json
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from shapely import wkt

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://service.omgevingswet.overheid.nl/publiek/omgevingsdocumenten/api/presenteren/v8"
CRS = "http://www.opengis.net/def/crs/EPSG/0/28992"
# 'biotoop', of 'molen' als los woord (dus niet de gemeentenaam Molenlanden of straatnamen als Molendijk)
ZOEK = re.compile(r"biotoop|\bmolens?\b", re.I)


def sleutel():
    k = os.environ.get("DSO_API_KEY")
    if not k and (ROOT / ".env").exists():
        for l in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if l.startswith("DSO_API_KEY="):
                k = l.split("=", 1)[1].strip()
    if not k:
        raise SystemExit("DSO_API_KEY ontbreekt (zet hem in .env)")
    return k


KEY = sleutel()


def call(url, body=None, tries=3):
    h = {"x-api-key": KEY, "Accept": "application/hal+json", "Content-Crs": CRS}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    last = ""
    for t in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=120) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503):
                time.sleep(3 * (t + 1))
                continue
            return e.code, e.read()[:200].decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            last = str(e)[:120]
            time.sleep(3 * (t + 1))
    return 0, last


def main():
    raw = {m["rijksmonumentnummer"]: m for m in json.loads((ROOT / "data" / "rce_raw.json").read_text(encoding="utf-8"))["molens"]}
    zones = json.loads((ROOT / "data" / "zones.json").read_text(encoding="utf-8"))
    doel = [nr for nr, z in zones.items() if z["status"] in ("Nee", "Onbekend")]
    print(len(doel), "molens zonder bestemmingsplan-zone", file=sys.stderr)
    uit = {}
    for nr in doel:
        c = wkt.loads(raw[nr]["rd"]).centroid
        pt = {"geometrie": {"type": "Point", "coordinates": [round(c.x), round(c.y)]}}
        st, d = call(BASE + "/regelingen/_zoek?page=1&size=100", pt)
        if st != 200:
            uit[nr] = {"fout": f"regelingen/_zoek {st} {d}"}
            continue
        rec = {"plannen": []}
        for r in d["_embedded"]["regelingen"]:
            t = r["type"]["waarde"] if isinstance(r["type"], dict) else r["type"]
            if "omgevingsplan" not in t.lower():
                continue
            u = urllib.parse.urlsplit(r["_links"]["self"]["href"])
            url = urllib.parse.urlunsplit((u.scheme, u.netloc, u.path + "/regeltekstannotaties/_zoek", u.query, ""))
            st2, a = call(url, pt)
            p = {"type": t, "id": r["identificatie"], "titel": r.get("officieleTitel"), "bevoegd_gezag": (r.get("aangeleverdDoorEen") or {}).get("naam")}
            if st2 != 200:
                p["fout"] = f"annotaties {st2} {a}"
            else:
                loc = [(l.get("noemer"), l.get("locatieType")) for l in a.get("locaties", [])]
                p.update({"locaties": loc, "aantal_regels": len(a.get("regelsVoorIedereen", [])), "sleutels": sorted(a.keys()),
                          "molen_locaties": [x for x in loc if ZOEK.search(x[0] or "")],
                          "molen_activiteiten": [x.get("naam") for x in a.get("activiteiten", []) if ZOEK.search(x.get("naam") or "")]})
            rec["plannen"].append(p)
        uit[nr] = rec
        print(nr, [(p["type"][:14], len(p.get("molen_locaties", [])) + len(p.get("molen_activiteiten", []))) for p in rec["plannen"]], file=sys.stderr, flush=True)
        time.sleep(0.3)
    (ROOT / "data" / "dso_scan.json").write_text(json.dumps({"opgehaald": date.today().isoformat(), "molens": uit}, ensure_ascii=False), encoding="utf-8")
    hits = [nr for nr, r in uit.items() if any(p.get("molen_locaties") or p.get("molen_activiteiten") for p in r.get("plannen", []))]
    print(f"klaar: {len(uit)} molens bekeken, {len(hits)} met molen of biotoop in locaties of activiteiten", hits, file=sys.stderr)


if __name__ == "__main__":
    main()
