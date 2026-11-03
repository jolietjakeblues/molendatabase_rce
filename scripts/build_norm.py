"""Norm-toets: voldoen de bestaande gebouwen (en bomen) in de formele molenbiotoopzone aan de norm uit het bestemmingsplan?

De regels (uit de plantekst, zie fetch_plantekst.py) zijn in Zuid-Holland meestal:
  a. binnen 100 m van het middelpunt van de molen geen bebouwing hoger dan de onderste punt van de verticaal staande wiek;
  b. tussen 100 en 400 m een hoogte van maximaal  h_wiek + afstand x helling  (helling 1/30, 1/50 of 1/100 van de afstand).
Vaak geldt dit ook voor beplanting.

Toetsing: AHN-hoogte (DSM min DTM, 2 m raster) per pixel binnen de zone, gebouwen uit de BAG-voetafdrukken, bomen = overige objecten >= 2,5 m.
Een gebouw overschrijdt de norm als minstens 2 pixels en 25% van zijn oppervlak boven de grens uitkomen.

De onderste wiekpunt (h_wiek) staat niet in de data en is een AANNAME (zie wiekhoogte()). Daarom wordt met drie waarden getoetst
(-1,5 m, midden, +1,5 m). Uitkomst: 'Voldoet' als het ook bij de strenge aanname klopt, 'Overschrijding' als het ook bij de ruime aanname
misgaat, anders 'Afhankelijk van wiekhoogte'.
Let op: de norm geldt voor het OPRICHTEN van bouwwerken; bestaande bebouwing mag er vaak overheen zitten. Daarom wordt apart geteld welke
overschrijdende gebouwen na de plandatum zijn gebouwd (BAG-bouwjaar).

Invoer : data/plannen.json, data/plantekst.json, data/rce_raw.json, data/biotoop.json, data/cache/<nr>_bag.json en <nr>_dsm_05m.tif / _dtm_05m.tif
Uitvoer: data/norm.json en site/data/norm/<nr>.json (gebouwen boven de norm, WGS84)
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
SITE = ROOT / "site" / "data" / "norm"
SITE.mkdir(parents=True, exist_ok=True)
to_ll = Transformer.from_crs(28992, 4326, always_xy=True).transform
R, N, PX = 400, 400, 2.0
MIN_PIXELS, MIN_AANDEEL = 2, 0.25


def wiekhoogte(m):
    """AANNAME voor de onderste punt van de verticaal staande wiek (m boven maaiveld), afgeleid van het type molen.
    De werkelijke waarde staat niet in de data; de AHN meet de molenkop te laag om er een vlucht uit af te leiden.
      grondzeiler / poldermolen / wipmolen : 2,5 m (wieken strijken net boven de grond), spreiding 1,5 m
      beltmolen                            : 5,5 m (belt + vrije hoogte), spreiding 1,5 m
      stellingmolen                        : 8 m (stelling van ongeveer 6 m + 2 m), spreiding 2,5 m
    Geeft (h_wiek, spreiding, bron)."""
    t = " ".join(o["tekst"] for o in m.get("omschrijvingen", [])).lower()
    if "tjasker" in t:
        return 2.0, 1.0, "aanname: tjasker"
    if re.search(r"stelling", t):
        return 8.0, 2.5, "aanname: stellingmolen (stelling ongeveer 6 m + 2 m)"
    if re.search(r"beltmolen|op (een )?(molen)?belt\b", t):
        return 5.5, 1.5, "aanname: beltmolen"
    return 2.5, 1.5, "aanname: grondzeiler, poldermolen of wipmolen"


def norm_params(tekst, parse):
    """Straal van zone a, helling en bovengrens van band b uit de regeltekst."""
    t = tekst.lower()
    a = parse.get("afstanden_m") or []
    if not a:
        return None
    r_a = next((x[0] for x in a if x[1] is None), a[0][0])
    top = max([x[1] for x in a if x[1]], default=None)
    slope = None
    m = re.search(r"100\s*(?:m|meter)?\s*(?:tot|en)\s*(\d+)\s*(?:m|meter)?[^;]{0,500}?\b1\s*[/:]\s*(\d+)\b", t)
    if m:
        slope, top = int(m.group(2)), top or int(m.group(1))
    elif parse.get("helling"):
        slope = int(parse["helling"].split(";")[0].split("/")[1])
    if slope and not top:
        top = 400
    return {"straal_a": r_a, "tot": top if slope else None, "helling": slope, "beplanting": bool(parse.get("beplanting_genoemd"))}


def toets(nr, m, zones, norm_per_zone, h_low, spreiding):
    d, t = CACHE / f"{nr}_dsm_05m.tif", CACHE / f"{nr}_dtm_05m.tif"
    pf = CACHE / f"{nr}_bag.json"
    if not (d.exists() and t.exists() and pf.exists()):
        return None
    geom = wkt.loads(m["rd"])
    c = geom.centroid
    x, y = round(c.x), round(c.y)
    with rasterio.open(d) as s1, rasterio.open(t) as s2:
        a, b = s1.read(1).astype(float), s2.read(1).astype(float)
    for arr in (a, b):
        arr[(arr > 1e5) | (arr < -1e3)] = np.nan
    n = np.clip(a - b, 0, 60)
    ok = np.isfinite(n)
    n = np.nan_to_num(n, nan=0.0)
    tf = from_bounds(x - R, y - R, x + R, y + R, N, N)
    yy, xx = np.mgrid[0:N, 0:N]
    dist = np.hypot((xx + .5) * PX - R, (yy + .5) * PX - R)
    own_ids = {bb.get("pand") for bb in m.get("bag", [])}
    gb = geom if geom.area > 0 else geom.buffer(1)
    panden, eigen = [], []
    for f in json.loads(pf.read_text(encoding="utf-8")):
        g, p = shape(f["geometry"]), f["properties"]
        if g.intersection(gb).area > 0.3 * gb.area or (not eigen and p.get("identificatie") in own_ids and g.distance(geom) < 1):
            eigen.append(g)
        else:
            panden.append((g, p))
    uitgesloten = rasterize([(g.buffer(3), 1) for g in eigen] + [(gb.buffer(8), 1)], out_shape=(N, N), transform=tf, fill=0, dtype="uint8").astype(bool)
    lab = rasterize([(g, i + 1) for i, (g, _) in enumerate(panden)], out_shape=(N, N), transform=tf, fill=0, dtype="int32") if panden else np.zeros((N, N), "int32")
    resultaat = {k: {"panden": {}, "bomen_m2": 0} for k in ("streng", "midden", "ruim")}
    feats_info = {}
    for z, nm in norm_per_zone:
        Z = rasterize([(shape(z["geometry"]), 1)], out_shape=(N, N), transform=tf, fill=0, dtype="uint8").astype(bool) & ok & ~uitgesloten
        plan_jaar = int((z.get("datum") or "0000")[:4]) or None
        for sleutel, hl in (("streng", h_low - spreiding), ("midden", h_low), ("ruim", h_low + spreiding)):
            hl = max(hl, 1.0)
            grens = np.full((N, N), np.inf)
            grens[dist <= nm["straal_a"]] = hl
            if nm["helling"]:
                band = (dist > nm["straal_a"]) & (dist <= nm["tot"])
                grens[band] = hl + dist[band] / nm["helling"]
            reg = Z & np.isfinite(grens)
            ov = n - grens
            bouw = reg & (lab > 0)
            tot = np.bincount(lab[bouw], minlength=len(panden) + 1)
            ex_mask = bouw & (ov > 0)
            ex = np.bincount(lab[ex_mask], minlength=len(panden) + 1)
            maxov = np.zeros(len(panden) + 1)
            np.maximum.at(maxov, lab[ex_mask], ov[ex_mask])
            for i in np.nonzero((ex >= MIN_PIXELS) & (tot > 0) & (ex / np.maximum(tot, 1) >= MIN_AANDEEL))[0]:
                g, p = panden[i - 1]
                bj = p.get("bouwjaar")
                resultaat[sleutel]["panden"][i] = {"ov": float(maxov[i]), "d": float(g.distance(c)), "bj": bj if bj and bj != 9999 else None,
                                                   "jonger": bool(plan_jaar and bj and bj != 9999 and int(bj) > plan_jaar), "pand": p.get("identificatie")}
            if nm["beplanting"]:
                tree = reg & (lab == 0) & (n >= 2.5) & (ov > 0)
                resultaat[sleutel]["bomen_m2"] += int(tree.sum() * PX * PX)
        # kaartlaag: panden boven de norm bij de middenaanname
        feats_info[id(z)] = (z, nm)
    return resultaat, panden


def main():
    raw = {mm["rijksmonumentnummer"]: mm for mm in json.loads((ROOT / "data" / "rce_raw.json").read_text(encoding="utf-8"))["molens"]}
    plannen = json.loads((ROOT / "data" / "plannen.json").read_text(encoding="utf-8"))
    pt = json.loads((ROOT / "data" / "plantekst.json").read_text(encoding="utf-8"))
    bio = {b["rijksmonumentnummer"]: b for b in json.loads((ROOT / "data" / "biotoop.json").read_text(encoding="utf-8")) if "askop_hoogte_schatting" in b}
    out = {}
    for nr, p in plannen.items():
        zs = {}
        for z in p.get("zones", []):
            if "biotoop" in z["naam"].lower() and z.get("historisch") == "0" and z.get("planstatus") not in ("ontwerp", "voorontwerp") and z.get("geometry"):
                zs.setdefault(z["identificatie"], z)
        if not zs:
            continue
        m = raw[nr]
        if nr not in bio:
            out[nr] = {"uitkomst": "Niet getoetst", "reden": "geen hoogtegegevens"}
            continue
        norm_per_zone = []
        for ga, z in zs.items():
            for h in pt["zones"].get(ga, {}).get("teksten", []):
                tk = pt["teksten"].get(h)
                if tk and tk["parse"].get("norm_herkend"):
                    nm = norm_params(tk["tekst"], tk["parse"])
                    if nm:
                        norm_per_zone.append((z, nm))
                        break
        if not norm_per_zone:
            out[nr] = {"uitkomst": "Niet getoetst", "reden": "norm niet herkend in de plantekst"}
            continue
        h_low, spreiding, wbron = wiekhoogte(m)
        res = toets(nr, m, zs, norm_per_zone, h_low, spreiding)
        if not res:
            out[nr] = {"uitkomst": "Niet getoetst", "reden": "hoogte- of gebouwdata ontbreekt"}
            continue
        r, panden = res
        n = {k: len(v["panden"]) for k, v in r.items()}
        if n["streng"] == 0:
            uitkomst = "Voldoet"
        elif n["ruim"] > 0:
            uitkomst = "Overschrijding"
        else:
            uitkomst = "Afhankelijk van wiekhoogte"
        mid = r["midden"]["panden"]
        rec = {
            "uitkomst": uitkomst,
            "norm": [{"straal_a": nm["straal_a"], "tot": nm["tot"], "helling": f"1/{nm['helling']}" if nm["helling"] else None, "beplanting": nm["beplanting"],
                      "plan": z.get("dossierid"), "plandatum": z.get("datum")} for z, nm in norm_per_zone],
            "aanname": {"h_wiek_m": h_low, "spreiding_m": spreiding, "bron": wbron,
                        "bereik_m": [round(max(h_low - spreiding, 1.0), 1), round(h_low + spreiding, 1)]},
            "gebouwen_boven_norm": {"streng": n["streng"], "midden": n["midden"], "ruim": n["ruim"]},
            "waarvan_na_plandatum": sum(1 for v in mid.values() if v["jonger"]),
            "hoogste_overschrijding_m": round(max((v["ov"] for v in mid.values()), default=0), 1),
            "bomen_boven_norm_m2": {k: v["bomen_m2"] for k, v in r.items()} if any(nm["beplanting"] for _, nm in norm_per_zone) else None,
        }
        out[nr] = rec
        feats = []
        for i, v in r["midden"]["panden"].items():
            g, pp = panden[i - 1]
            feats.append({"type": "Feature", "geometry": mapping(shp_transform(to_ll, g.simplify(0.2))),
                          "properties": {"pand": v["pand"], "afstand": round(v["d"]), "overschrijding": round(v["ov"], 1), "bouwjaar": v["bj"], "na_plandatum": v["jonger"],
                                         "robuust": i in r["ruim"]["panden"]}})
        if feats:
            (SITE / f"{nr}.json").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")), encoding="utf-8")
    (ROOT / "data" / "norm.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    from collections import Counter
    print(Counter(r["uitkomst"] for r in out.values()))
    print("niet getoetst, redenen:", Counter(r.get("reden") for r in out.values() if r["uitkomst"] == "Niet getoetst"))


if __name__ == "__main__":
    main()
