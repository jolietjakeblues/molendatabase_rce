"""KNMI-uurgegevens (windrichting DD, uurgemiddelde windsnelheid FH) -> windroos per station, per periode.

Bron: https://www.daggegevens.knmi.nl/klimatologie/uurgegevens (KNMI, open data, CC BY 4.0).
Per station en periode: aantal uren, frequentie per windrichting (8 sectoren, 'N' = wind uit het noorden, 337,5-22,5 graden)
en energieaandeel (som van v^3, een maat voor windenergie) per sector.
Uitvoer: data/knmi_windroos.json ; ruwe uurdata staat per station en jaar in data/cache/knmi_<stn>_<jaar>.csv.
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)
OUT = ROOT / "data" / "knmi_windroos.json"
URL = "https://www.daggegevens.knmi.nl/klimatologie/uurgegevens"
# stations in en rond Zuid-Holland
STATIONS = {"330": "Hoek van Holland", "344": "Rotterdam", "348": "Cabauw", "215": "Voorschoten", "240": "Schiphol",
            "356": "Herwijnen", "350": "Gilze-Rijen", "340": "Woensdrecht"}
PERIODEN = {"1991-2020": (1991, 2020), "2014-2023": (2014, 2023)}
DIRS = ["N", "NO", "O", "ZO", "Z", "ZW", "W", "NW"]


def jaar(stn, y):
    f = CACHE / f"knmi_{stn}_{y}.csv"
    if not f.exists():
        data = urllib.parse.urlencode({"start": f"{y}010101", "end": f"{y}123124", "vars": "DD:FH", "stns": stn}).encode()
        for t in range(4):
            try:
                with urllib.request.urlopen(urllib.request.Request(URL, data=data), timeout=120) as r:
                    f.write_bytes(r.read())
                break
            except Exception as e:  # noqa: BLE001
                print("  poging", t + 1, stn, y, e, file=sys.stderr)
                time.sleep(5 * (t + 1))
        else:
            raise SystemExit(f"KNMI ophalen mislukt: {stn} {y}")
        time.sleep(0.3)
    return f.read_text(encoding="utf-8", errors="replace")


def station_info(txt):
    """Naam en coordinaten uit de kop van het KNMI-bestand."""
    for l in txt.splitlines():
        if l.startswith("# ") and l[2:5].strip().isdigit():
            p = l[2:].split()
            try:
                return {"lon": float(p[1]), "lat": float(p[2]), "hoogte": float(p[3]), "knmi_naam": " ".join(p[4:])}
            except (ValueError, IndexError):
                continue
    return {}


def roos(stn, y0, y1):
    n = [0] * 8
    e = [0.0] * 8
    v = [0.0] * 8
    uren = geldig = stil = 0
    info = {}
    for y in range(y0, y1 + 1):
        txt = jaar(stn, y)
        info = info or station_info(txt)
        for l in txt.splitlines():
            if l.startswith("#") or not l.strip():
                continue
            p = [x.strip() for x in l.split(",")]
            if len(p) < 5:
                continue
            uren += 1
            if not p[3] or not p[4]:
                continue
            dd, fh = int(p[3]), int(p[4]) / 10
            if dd in (0, 990):
                stil += 1
                continue
            s = int(((dd % 360) + 22.5) // 45) % 8
            n[s] += 1
            e[s] += fh ** 3
            v[s] += fh
            geldig += 1
    if not geldig:
        return info, None
    se = sum(e)
    return info, {"uren": uren, "geldig": geldig, "stil_of_variabel": stil,
                  "freq": [round(x / geldig, 4) for x in n], "energie": [round(x / se, 4) for x in e],
                  "gem_snelheid": [round(v[i] / n[i], 2) if n[i] else None for i in range(8)]}


if __name__ == "__main__":
    out = {"bron": "KNMI uurgegevens (DD, FH), CC BY 4.0", "opgehaald": date.today().isoformat(), "richtingen": DIRS, "stations": {}}
    for stn, naam in STATIONS.items():
        info, per = {}, {}
        for pn, (y0, y1) in PERIODEN.items():
            info2, r = roos(stn, y0, y1)
            info = info or info2
            if r:
                per[pn] = r
        out["stations"][stn] = {"naam": naam, **info, "perioden": per}
        print(stn, naam, info.get("lat"), info.get("lon"), {k: v["geldig"] for k, v in per.items()}, file=sys.stderr, flush=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("geschreven", OUT, file=sys.stderr)
