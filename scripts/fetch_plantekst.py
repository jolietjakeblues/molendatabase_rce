"""Regelteksten van de molenbiotoopzones uit de API Ruimtelijke Plannen (Ruimtelijkeplannen.nl, v4).

Per vigerende biotoopzone uit data/plannen.json: het gebiedsaanduiding-object (zelfde ID als in de PDOK-WMS) -> gekoppeld artikel
(_links.teksten) -> tekst van het artikel (de regels). Er wordt per artikel gecached; uit de tekst worden afstanden, de hoogtehelling en
de referentie (onderste wiekpunt) herkend.

Vereist de sleutel in .env (RUIMTELIJKE_PLANNEN_API_KEY) of als omgevingsvariabele. De sleutel wordt nooit weggeschreven of geprint.
Invoer : data/plannen.json
Uitvoer: data/plantekst.json  {"zones": {gebiedsaanduiding_id: [tekst_href]}, "teksten": {tekst_href: {...}}}
"""
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "plantekst.json"
BASE = "https://ruimte.omgevingswet.overheid.nl/ruimtelijke-plannen/api/opvragen/v4"


def sleutel():
    k = os.environ.get("RUIMTELIJKE_PLANNEN_API_KEY")
    if not k and (ROOT / ".env").exists():
        for l in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if l.startswith("RUIMTELIJKE_PLANNEN_API_KEY="):
                k = l.split("=", 1)[1].strip()
    if not k:
        raise SystemExit("RUIMTELIJKE_PLANNEN_API_KEY ontbreekt (zet hem in .env)")
    return k


KEY = sleutel()


def get(url, tries=4):
    h = {"X-Api-Key": KEY, "Accept": "application/hal+json", "Accept-Crs": "epsg:28992"}
    for t in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (404, 400):
                return None
            time.sleep(2 * (t + 1))
        except Exception:  # noqa: BLE001
            time.sleep(2 * (t + 1))
    return None


def schoon(inhoud):
    t = html.unescape(re.sub(r"<[^>]+>", " ", inhoud or ""))
    return re.sub(r"\s+", " ", t).strip()


def parse(tekst):
    """Afstanden, hoogtehelling en referentie uit de regeltekst. Alleen wat er letterlijk staat."""
    t = tekst.lower()
    out = {}
    banden = []
    for a, b in re.findall(r"(?:afstand|straal) van (\d+)\s*(?:m\b|meter)?(?:\s*(?:tot|en)\s*(\d+)\s*(?:m\b|meter))?", t):
        band = [int(a), int(b) if b else None]
        if band not in banden:
            banden.append(band)
    if banden:
        out["afstanden_m"] = banden
    hell = []
    for m in re.finditer(r"\b1\s*[/:]\s*(\d+)\b", t):
        if f"1/{m.group(1)}" not in hell:
            hell.append(f"1/{m.group(1)}")
    if hell:
        out["helling"] = "; ".join(hell)
    if re.search(r"(?:onderste|laagste|onderkant)\s*(?:punt\s*)?(?:van\s*)?(?:de\s*)?(?:verticaal staande\s*)?wiek", t):
        out["referentie"] = "onderste punt van de (verticaal staande) wiek"
    if "beplanting" in t:
        out["beplanting_genoemd"] = True
    h = re.findall(r"hoogte (?:van|van maximaal|van niet meer dan) (\d+(?:[.,]\d+)?)\s*m", t)
    if h:
        out["hoogtes_m"] = [float(x.replace(",", ".")) for x in h]
    out["norm_herkend"] = bool(banden and (out.get("referentie") or out.get("helling")))
    return out


def artikel(href, diepte=0):
    """Tekst van een artikel, aangevuld met de tekst van onderliggende artikelen (regels staan vaak in een lid eronder)."""
    t = get(href)
    if not t:
        return None, 0
    delen = [schoon(t.get("inhoud"))]
    n = 1
    if diepte < 2:
        for l in t.get("_links", {}).get("children", []):
            sub, k = artikel(l["href"], diepte + 1)
            if sub:
                delen.append(sub)
            n += k
    return " ".join(d for d in delen if d), n


def zone_tekst(item):
    plan, ga = item
    z = get(f"{BASE}/plannen/{plan}/gebiedsaanduidingen/{ga}")
    if not z:
        return item, None, []
    hrefs = [l["href"] for l in z.get("_links", {}).get("teksten", [])]
    return item, z, hrefs


def main():
    plannen = json.loads((ROOT / "data" / "plannen.json").read_text(encoding="utf-8"))
    items = {}
    for r in plannen.values():
        for q in r.get("zones", []):
            if "biotoop" in q["naam"].lower() and q["historisch"] == "0" and q["planstatus"] not in ("ontwerp", "voorontwerp"):
                m = re.search(r"/documents/([^/]+)/", q.get("tekst") or "")
                if m and q.get("identificatie"):
                    items[(m.group(1), q["identificatie"])] = q["dossierid"]
    print("zones om op te halen:", len(items), file=sys.stderr, flush=True)
    zones, teksten = {}, {}
    with ThreadPoolExecutor(4) as ex:
        for (plan, ga), z, hrefs in ex.map(zone_tekst, list(items)):
            zones[ga] = {"plan_api": plan, "teksten": hrefs, "gevonden": z is not None}
    uniek = sorted({h for v in zones.values() for h in v["teksten"]})
    print("unieke artikelen:", len(uniek), file=sys.stderr, flush=True)

    def haal(h):
        t = get(h)
        if not t:
            return h, None
        tekst, n = artikel(h)
        return h, {"titel": t.get("titel"), "tekst": tekst or "", "artikelen_gelezen": n, "parse": parse(tekst or ""), "opgehaald": date.today().isoformat()}

    with ThreadPoolExecutor(4) as ex:
        for h, v in ex.map(haal, uniek):
            if v:
                teksten[h] = v
    OUT.write_text(json.dumps({"bron": "Ruimtelijkeplannen.nl API v4", "opgehaald": date.today().isoformat(), "zones": zones, "teksten": teksten},
                              ensure_ascii=False), encoding="utf-8")
    herkend = sum(1 for v in teksten.values() if v["parse"].get("norm_herkend"))
    print(f"klaar: {sum(1 for z in zones.values() if z['gevonden'])}/{len(zones)} zones gekoppeld, {len(teksten)} artikelen, norm herkend in {herkend}", file=sys.stderr)


if __name__ == "__main__":
    main()
