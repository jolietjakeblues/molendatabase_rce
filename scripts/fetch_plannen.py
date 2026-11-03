"""Formele molenbiotoopzones uit bestemmingsplannen: PDOK Ruimtelijke Plannen WMS (GetFeatureInfo).

Per molen: welke gebiedsaanduiding / dubbelbestemming / functieaanduiding / bouwaanduiding met 'molen' in de naam
ligt op de molen (of, zo niet, in een ring van 60 en 150 m)? Plus welke bestemmingsplan-achtige plannen gelden op die plek (uit de laag enkelbestemming).
Bron: https://service.pdok.nl/kadaster/ruimtelijke-plannen/wms/v1_0 (Ruimtelijkeplannen.nl, IHR).
Omgevingsplannen onder de Omgevingswet staan hier niet in; die vragen de DSO-API met een sleutel.

Invoer : data/rce_raw.json
Uitvoer: data/plannen.json  {rijksmonumentnummer: {opgehaald, gevonden_op, zones:[...], plannen:[...]}}
"""
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from shapely import wkt

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "plannen.json"
BASE = "https://service.pdok.nl/kadaster/ruimtelijke-plannen/wms/v1_0"
ZONE_LAGEN = "gebiedsaanduiding,dubbelbestemming,functieaanduiding,bouwaanduiding,enkelbestemming"
PLANTYPES = {"bestemmingsplan", "beheersverordening", "wijzigingsplan", "uitwerkingsplan", "inpassingsplan",
             "projectbesluit", "exploitatieplan", "omgevingsplan"}
RINGEN = [60, 150]


def probe(layers, x, y, count=100, tries=4):
    q = dict(service="WMS", version="1.3.0", request="GetFeatureInfo", layers=layers, query_layers=layers, crs="EPSG:28992",
             bbox=f"{x - 15},{y - 15},{x + 15},{y + 15}", width=101, height=101, i=50, j=50, info_format="application/json",
             feature_count=count, styles="")
    last = None
    for t in range(tries):
        try:
            with urllib.request.urlopen(BASE + "?" + urllib.parse.urlencode(q), timeout=60) as r:
                return json.load(r).get("features", [])
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (t + 1))
    raise RuntimeError(f"probe mislukt: {last}")


def molen_zones(feats):
    out = []
    for f in feats:
        p = f["properties"]
        naam = (p.get("naam") or "")
        if "molen" not in naam.lower():
            continue
        out.append({
            "id": f.get("id"), "identificatie": p.get("identificatie"), "naam": naam,
            "groep": p.get("gebiedsaanduidinggroep") or p.get("bestemmingshoofdgroep") or p.get("functieaanduidinggroep") or p.get("bouwaanduiding") or "",
            "artikel": p.get("artikelnummer"), "typeplan": p.get("typeplan"), "planstatus": p.get("planstatus"),
            "dossierstatus": p.get("dossierstatus"), "historisch": p.get("historisch"), "datum": p.get("datum"),
            "dossierid": p.get("dossierid"), "plangebied": p.get("plangebied"), "tekst": p.get("verwijzingnaartekst"),
            "geometry": f.get("geometry"),
        })
    return out


def plan_context(feats):
    """Welke bestemmingsplan-achtige plannen gelden hier? (uit de lichte laag enkelbestemming, uniek per dossier)"""
    best = {}
    for f in feats:
        p = f["properties"]
        if p.get("typeplan") in PLANTYPES and p.get("historisch") == "0" and p.get("planstatus") not in ("ontwerp", "voorontwerp"):
            k = p.get("dossierid")
            if k not in best or (p.get("datum") or "") > (best[k]["datum"] or ""):
                best[k] = {"typeplan": p.get("typeplan"), "planstatus": p.get("planstatus"), "dossierstatus": p.get("dossierstatus"),
                           "datum": p.get("datum"), "dossierid": k, "tekst": p.get("verwijzingnaartekst")}
    return list(best.values())


def analyse(m):
    nr = m["rijksmonumentnummer"]
    c = wkt.loads(m["rd"]).centroid
    x, y = round(c.x), round(c.y)
    feats = probe(ZONE_LAGEN, x, y)
    zones, waar = molen_zones(feats), "op de molen"
    plannen = plan_context(feats)
    if not zones:
        for r in RINGEN:
            for k in range(8):
                px, py = round(x + r * math.sin(math.radians(k * 45))), round(y + r * math.cos(math.radians(k * 45)))
                zones = molen_zones(probe("gebiedsaanduiding,dubbelbestemming", px, py))
                if zones:
                    waar = f"op {r} m van de molen (richting {['N', 'NO', 'O', 'ZO', 'Z', 'ZW', 'W', 'NW'][k]})"
                    break
            if zones:
                break
    return nr, {"opgehaald": date.today().isoformat(), "gevonden_op": waar if zones else "", "zones": zones, "plannen": plannen}


def safe(m):
    try:
        r = analyse(m)
        print("ok", r[0], len(r[1]["zones"]), flush=True)
        return r
    except Exception as e:  # noqa: BLE001
        print("FOUT", m["rijksmonumentnummer"], e, file=sys.stderr, flush=True)
        return m["rijksmonumentnummer"], {"fout": str(e)}


if __name__ == "__main__":
    molens = [m for m in json.loads((ROOT / "data" / "rce_raw.json").read_text(encoding="utf-8"))["molens"] if m.get("categorie", "Molen") == "Molen"]
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    if lim:
        molens = molens[:lim]
    with ThreadPoolExecutor(6) as ex:
        res = dict(ex.map(safe, molens))
    OUT.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print("klaar:", sum(1 for r in res.values() if "fout" not in r), "ok,", sum(1 for r in res.values() if "fout" in r), "fout,",
          sum(1 for r in res.values() if r.get("zones")), "met zone", file=sys.stderr)
