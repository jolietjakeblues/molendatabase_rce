"""Molenbiotoopzones analyseren en vergelijken met de berekende biotoop.

Invoer : data/plannen.json (fetch_plannen.py), data/rce_raw.json, data/biotoop.json, data/cache/<nr>_bag.json, <nr>_dsm_05m.tif, <nr>_dtm_05m.tif
Uitvoer: data/zones.json en site/data/zone/<nr>.json (GeoJSON, WGS84, voor de kaart)

Per molen:
 - 'biotoopzones': vigerende gebiedsaanduidingen met 'biotoop' in de naam (formele molenbiotoopzone);
 - 'molenaanduidingen': overige vigerende aanduidingen met 'molen' in de naam (het object is als molen bestemd of aangeduid);
 - straal uit de naam (bijv. '100 m'), anders geschat uit het polygoon (verste hoekpunt vanaf de molen, op 25 m afgerond);
 - dekking van de cirkels van 100 en 400 m, gebouwen in de zone (BAG), gebouwen jonger dan het plan, en hoge objecten in de zone (AHN).
De vergelijking met de berekende biotoop is een indicatie: de plantekst met de eigenlijke regels (bijv. maximale bouwhoogte) is niet gelezen.
"""
import json
import re
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.transform import from_bounds
from shapely import wkt
from shapely.geometry import shape, mapping, Point
from shapely.ops import transform as shp_transform, unary_union

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
SITE = ROOT / "site" / "data" / "zone"
SITE.mkdir(parents=True, exist_ok=True)
to_ll = Transformer.from_crs(28992, 4326, always_xy=True).transform
R, N = 400, 400  # zelfde raster als build_biotoop.py (2 m)
PT_F = ROOT / "data" / "plantekst.json"
PT = json.loads(PT_F.read_text(encoding="utf-8")) if PT_F.exists() else {"zones": {}, "teksten": {}}
GEBRUIKT = {}


def regels(ga):
    """Regeltekst (Ruimtelijkeplannen.nl API) bij een gebiedsaanduiding; voorkeur voor het artikel waarin de norm herkend is."""
    zz = PT["zones"].get(ga or "")
    hrefs = [h for h in (zz or {}).get("teksten", []) if h in PT["teksten"]]
    if not hrefs:
        return None, None
    h = next((x for x in hrefs if PT["teksten"][x]["parse"].get("norm_herkend")), hrefs[0])
    GEBRUIKT[h] = PT["teksten"][h]
    return h, PT["teksten"][h]["parse"]


def vigerend(z):
    return z.get("historisch") == "0" and z.get("planstatus") not in ("ontwerp", "voorontwerp")


def straal_uit_naam(naam):
    m = re.search(r"(\d{2,3})\s*(m\b|meter)", naam.lower())
    return int(m.group(1)) if m else None


def hoge_objecten(nr, zone, mill_geom):
    """Aandeel van de zone met objecten >= 3 m en hoogste obstakel (AHN 2 m raster, eigen molen en erf tot 12 m uitgesloten)."""
    d, t = CACHE / f"{nr}_dsm_05m.tif", CACHE / f"{nr}_dtm_05m.tif"
    if not (d.exists() and t.exists()):
        return None, None
    c = mill_geom.centroid
    x, y = round(c.x), round(c.y)
    with rasterio.open(d) as s1, rasterio.open(t) as s2:
        a, b = s1.read(1).astype(float), s2.read(1).astype(float)
    for arr in (a, b):
        arr[(arr > 1e5) | (arr < -1e3)] = np.nan
    n = np.clip(a - b, 0, 60)
    tf = from_bounds(x - R, y - R, x + R, y + R, N, N)
    z = rasterize([(zone, 1)], out_shape=(N, N), transform=tf, fill=0, dtype="uint8").astype(bool)
    yy, xx = np.mgrid[0:N, 0:N]
    dist = np.hypot((xx + .5) * 2 - R, (yy + .5) * 2 - R)
    m = z & (dist > 12) & np.isfinite(n)
    if not m.any():
        return None, None
    return round(float((n[m] >= 3).mean()), 3), round(float(n[m].max()), 1)


def main():
    raw = {m["rijksmonumentnummer"]: m for m in json.loads((ROOT / "data" / "rce_raw.json").read_text(encoding="utf-8"))["molens"]}
    plannen = json.loads((ROOT / "data" / "plannen.json").read_text(encoding="utf-8"))
    bio = {b["rijksmonumentnummer"]: b for b in json.loads((ROOT / "data" / "biotoop.json").read_text(encoding="utf-8")) if "klasse" in b}
    out = {}
    for nr, p in plannen.items():
        if "fout" in p:
            out[nr] = {"status": "Onbekend", "reden": "ophalen mislukt: " + p["fout"]}
            continue
        m = raw[nr]
        geom = wkt.loads(m["rd"])
        c = geom.centroid
        zs = [z for z in p["zones"] if vigerend(z) and z.get("geometry")]
        uniek = {}
        for z in zs:  # uniek per identificatie, nieuwste plan eerst
            uniek.setdefault(z["identificatie"], z)
        zs = sorted(uniek.values(), key=lambda z: z.get("datum") or "", reverse=True)
        bz = [z for z in zs if "biotoop" in z["naam"].lower()]
        ma = [z for z in zs if "biotoop" not in z["naam"].lower()]
        rec = {"opgehaald": p["opgehaald"], "gevonden_op": p["gevonden_op"], "plannen": p["plannen"]}
        if bz:
            geoms = [shape(z["geometry"]) for z in bz]
            U = unary_union(geoms)
            z0 = bz[0]
            zl, radii = [], []
            for z, g in zip(bz, geoms):
                r_naam = straal_uit_naam(z["naam"])
                r_g = max((Point(x, y).distance(c) for poly in getattr(g, "geoms", [g]) for x, y in poly.exterior.coords), default=0)
                r_g = int(round(r_g / 25) * 25)
                if r_naam:
                    r, bron = r_naam, "naam van de aanduiding"
                elif r_g <= 450:
                    r, bron = r_g, "geschat uit het polygoon (naam zonder straal)"
                else:
                    r, bron = None, "niet te bepalen (polygoon omvat meer dan de molen)"
                if r and r not in radii:
                    radii.append(r)
                rh, rp = regels(z.get("identificatie"))
                zl.append({"naam": z["naam"], "straal_m": r, "straal_bron": bron, "plan_dossier": z.get("dossierid"), "planstatus": z.get("planstatus"),
                           "plandatum": z.get("datum"), "plantekst": z.get("tekst"), "artikel": z.get("artikel"),
                           "regels_href": rh, "norm": rp})
            straal = "; ".join(str(r) for r in sorted(radii)) if radii else ""
            bron = "; ".join(sorted({q["straal_bron"] for q in zl}))
            r_geom = ""
            plan_jaar = int((z0.get("datum") or "0000")[:4]) or None
            cirkel = lambda r: round(U.intersection(c.buffer(r)).area / c.buffer(r).area, 3)
            pf = CACHE / f"{nr}_bag.json"
            n_in = n_jong = 0
            if pf.exists():
                own = {b.get("pand") for b in m.get("bag", [])}
                for f in json.loads(pf.read_text(encoding="utf-8")):
                    g, pr = shape(f["geometry"]), f["properties"]
                    if g.intersection(geom.buffer(0.5)).area > 0.3 * min(g.area, max(geom.area, 1)) or pr.get("identificatie") in own:
                        continue
                    if g.intersects(U) and g.intersection(U).area > 0.5 * g.area:
                        n_in += 1
                        bj = pr.get("bouwjaar")
                        if plan_jaar and bj and bj != 9999 and int(bj) > plan_jaar:
                            n_jong += 1
            aandeel, hoogste = hoge_objecten(nr, U, geom)
            rec.update({
                "status": "Ja", "zone_naam": " | ".join(dict.fromkeys(z["naam"] for z in bz)), "straal_m": straal, "straal_bron": bron, "zones": zl,
                "plan_dossier": z0.get("dossierid"), "planstatus": z0.get("planstatus"), "plandatum": z0.get("datum"),
                "plantype": z0.get("typeplan"), "plantekst": z0.get("tekst"), "artikel": z0.get("artikel"),
                "aantal_zones": len(bz), "zone_m2": round(U.area), "dekking_100m": cirkel(100), "dekking_400m": cirkel(400),
                "gebouwen_in_zone": n_in, "gebouwen_jonger_dan_plan": n_jong,
                "hoge_objecten_aandeel": aandeel, "hoogste_obstakel_m": hoogste,
            })
        else:
            geldend = [pl for pl in p["plannen"]]
            rec.update({"status": "Nee" if geldend else "Onbekend",
                        "reden": ("bestemmingsplan zonder molenbiotoopzone op deze plek" if geldend else "geen bestemmingsplan gevonden; mogelijk een omgevingsplan onder de Omgevingswet (DSO)")})
        rec["molenaanduidingen"] = [{"naam": z["naam"], "plan_dossier": z.get("dossierid"), "plandatum": z.get("datum")} for z in ma]
        # vergelijking met de berekende biotoop
        b = bio.get(nr)
        slecht = sum(1 for v in b["klasse"].values() if v == "Slecht") if b else None
        if rec["status"] == "Ja":
            if (rec.get("hoge_objecten_aandeel") or 0) >= 0.10:
                vgl = "Zone aanwezig; hoge objecten (>= 3 m) bedekken >= 10% van de zone"
            else:
                vgl = "Zone aanwezig; zone grotendeels vrij van hoge objecten"
        elif rec["status"] == "Nee":
            vgl = "Geen zone, wel hinder (>= 2 richtingen slecht)" if slecht and slecht >= 2 else "Geen zone, weinig berekende hinder"
        else:
            vgl = "Onbekend (geen planinformatie)"
        rec["vergelijking"] = vgl
        out[nr] = rec
        feats = []
        for z in bz + ma:
            feats.append({"type": "Feature", "geometry": mapping(shp_transform(to_ll, shape(z["geometry"]).simplify(0.5))),
                          "properties": {"soort": "biotoopzone" if z in bz else "molenaanduiding", "naam": z["naam"], "plan": z.get("dossierid"),
                                         "status": z.get("planstatus"), "datum": z.get("datum"), "tekst": z.get("tekst")}})
        if feats:
            (SITE / f"{nr}.json").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")), encoding="utf-8")
    (ROOT / "data" / "zones.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    (ROOT / "site" / "data" / "plantekst.json").write_text(json.dumps(
        {h: {"titel": v["titel"], "tekst": v["tekst"][:5000], "parse": v["parse"], "opgehaald": v["opgehaald"]} for h, v in GEBRUIKT.items()},
        ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    from collections import Counter
    print(Counter(r["status"] for r in out.values()), Counter(r["vergelijking"] for r in out.values()))


if __name__ == "__main__":
    main()
