"""Molenbiotoop per windrichting uit AHN (gebouwen + bomen) en BAG (om gebouw van boom te onderscheiden).

Invoer : data/rce_raw.json (molenlocaties, RD)
Uitvoer: data/biotoop.json

Methode (indicatief, bedoeld om molens onderling te vergelijken):
 - Rond elke molen wordt 400 m (de gangbare molenbiotoopstraal) een genormaliseerd hoogtemodel
   gemaakt: nDSM = AHN-DSM - AHN-DTM (2 m raster). Pixels binnen een BAG-pand zijn "gebouw",
   overige pixels hoger dan 2,5 m zijn "boom/begroeiing".
 - Askophoogte = max(0,9 x hoogste punt volgens AHN, ondergrens per type: stellingmolen 14 m,
   grondzeiler 9 m, wip-/standerdmolen 6 m, tjasker 3 m), want AHN mist hoge, dunne molenkoppen.
 - Per windrichting (sector van 45 graden, 9 stralen) kijken we van 12 tot 400 m afstand.
   Een obstakel met hoogte H op afstand d veroorzaakt windhinder volgens de bekende vuistregel
   (turbulentiezone: 2H hoog, circa 20H lang): hinder = 1 - d/(20 H) als de askophoogte lager is
   dan 2H, anders 0. Bomen tellen voor 60 procent mee (doorlaatbaar).
 - Sectorscore = gemiddelde van de maximale hinder per straal.
   < 0,15 Goed, < 0,45 Matig, anders Slecht.
"""
import io
import json
import math
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from shapely import wkt
from shapely.geometry import shape, Point

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "rce_raw.json"
OUT = ROOT / "data" / "biotoop.json"
CACHE = ROOT / "data" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)

R = 400          # straal molenbiotoop (m)
PX = 2.0         # rasterresolutie (m)
N = int(2 * R / PX)
WCS = "https://service.pdok.nl/rws/ahn/wcs/v1_0"
BAG = "https://api.pdok.nl/kadaster/bag/ogc/v2/collections/pand/items"
CRS = "http://www.opengis.net/def/crs/EPSG/0/28992"
DIRS = ["N", "NO", "O", "ZO", "Z", "ZW", "W", "NW"]


def get(url, tries=4):
    last = None
    for t in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=100) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"{url[:120]}: {last}")


def ahn(cov, x, y, name):
    f = CACHE / f"{name}_{cov}.tif"
    if not f.exists():
        url = (f"{WCS}?service=WCS&version=2.0.1&request=GetCoverage&coverageid={cov}&format=image/tiff"
               f"&subset=x({x - R},{x + R})&subset=y({y - R},{y + R})&scalesize=x({N}),y({N})")
        f.write_bytes(get(url))
    with rasterio.open(f) as s:
        a = s.read(1).astype("float64")
        nod = s.nodata
    a[(a > 1e5) | (a < -1e3)] = np.nan
    if nod is not None:
        a[a == nod] = np.nan
    return a


def panden(x, y, name):
    f = CACHE / f"{name}_bag.json"
    if not f.exists():
        feats, url = [], (f"{BAG}?bbox={x - R},{y - R},{x + R},{y + R}&bbox-crs={CRS}&crs={CRS}&limit=1000&f=json")
        while url:
            d = json.loads(get(url))
            feats += d["features"]
            url = next((l["href"] for l in d.get("links", []) if l.get("rel") == "next"), None)
        f.write_text(json.dumps(feats), encoding="utf-8")
    return json.loads(f.read_text(encoding="utf-8"))


def analyse(m):
    nr = m["rijksmonumentnummer"]
    geom = wkt.loads(m["rd"])
    c = geom.centroid
    x, y = round(c.x), round(c.y)
    dsm, dtm = ahn("dsm_05m", x, y, nr), ahn("dtm_05m", x, y, nr)
    ndsm = np.clip(dsm - dtm, 0, 60)
    feats = panden(x, y, nr)
    tf = from_bounds(x - R, y - R, x + R, y + R, N, N)  # rij 0 = noord
    own_ids = {b.get("pand") for b in m.get("bag", [])}
    shapes_b, own_geoms, bj_own = [], [], []
    for ft in feats:
        g = shape(ft["geometry"])
        p = ft["properties"]
        if p.get("identificatie") in own_ids or g.distance(geom) < 3:
            own_geoms.append(g)
            if p.get("bouwjaar"):
                bj_own.append(int(p["bouwjaar"]))
        else:
            shapes_b.append((g, 1))
    bld = rasterize(shapes_b, out_shape=(N, N), transform=tf, fill=0, dtype="uint8") if shapes_b else np.zeros((N, N), "uint8")
    # hoogte molen: hoogste punt binnen de voetafdruk (+3 m)
    own = rasterize([(g, 1) for g in own_geoms] + [(geom.buffer(3 if geom.area > 5 else 7), 1)], out_shape=(N, N), transform=tf, fill=0, dtype="uint8").astype(bool)
    vals = ndsm[own & ~np.isnan(ndsm)]
    h_top = float(np.nanmax(vals)) if vals.size else 12.0
    h_top = max(h_top, 4.0)
    # AHN onderschat hoge, dunne molenkoppen (De Walvisch: 24 m gemeten, 33 m werkelijk): ondergrens per type
    txt = " ".join(o["tekst"] for o in m.get("omschrijvingen", [])).lower()
    if "tjasker" in txt:
        floor = 3.0
    elif re.search(r"stelling", txt):
        floor = 14.0
    elif re.search(r"wip|standerd|paltrok|spinne?kop", txt):
        floor = 6.0
    else:
        floor = 9.0
    h_as = max(0.9 * h_top, floor)
    ndsm = np.nan_to_num(ndsm, nan=0.0)
    veg = (bld == 0) & (ndsm >= 2.5)
    obj = np.where(bld == 1, ndsm, np.where(veg, ndsm * 0.6, 0.0))  # bomen tellen voor 60%
    # polar sampling
    rs = np.arange(12, R, 3.0)
    scores, det = {}, {}
    cx = cy = N / 2.0
    for k, d in enumerate(DIRS):
        ray_max, dom = [], (0.0, None)
        for a in np.arange(k * 45 - 20, k * 45 + 21, 5):
            th = math.radians(a)
            col = (cx + rs * math.sin(th) / PX).astype(int)
            row = (cy - rs * math.cos(th) / PX).astype(int)
            ok = (col >= 0) & (col < N) & (row >= 0) & (row < N)
            col, row, rr = col[ok], row[ok], rs[ok]
            H = ndsm[row, col]
            w = np.where(bld[row, col] == 1, 1.0, np.where(H >= 2.5, 0.6, 0.0))
            Hh = np.where(w > 0, H, 0.0)
            sev = np.where((Hh >= 2.5) & (h_as < 2 * Hh), np.clip(1 - rr / (20 * np.maximum(Hh, 1e-6)), 0, 1), 0.0) * w
            ray_max.append(float(sev.max()))
            if sev.size and sev.max() > dom[0]:
                i = int(sev.argmax())
                dom = (float(sev.max()), {"type": "gebouw" if bld[row[i], col[i]] else "boom", "afstand": int(rr[i]), "hoogte": round(float(H[i]), 1)})
        s = float(np.mean(ray_max))
        scores[d] = s
        det[d] = dom[1]
    cls = {d: ("Goed" if s < 0.15 else "Matig" if s < 0.45 else "Slecht") for d, s in scores.items()}
    yy, xx = np.mgrid[0:N, 0:N]
    dist = np.hypot((xx + .5) * PX - R, (yy + .5) * PX - R)
    def dens(mask, rad):
        z = dist <= rad
        return round(float(mask[z].mean()), 3)
    return {
        "rijksmonumentnummer": nr, "x": x, "y": y,
        "hoogte_molen_ahn": round(h_top, 1), "askop_hoogte_schatting": round(h_as, 1), "askop_ondergrens": floor,
        "score": {d: round(s, 3) for d, s in scores.items()}, "klasse": cls, "dominant": det,
        "bebouwd_100m": dens(bld == 1, 100), "bebouwd_400m": dens(bld == 1, 400),
        "boomdek_100m": dens(veg, 100), "boomdek_400m": dens(veg, 400),
        "hoogste_obstakel_400m": round(float(ndsm[(dist > 12) & (dist <= R)].max()), 1),
        "bag_bouwjaar_pand": min(bj_own) if bj_own else None,
        "aantal_panden_400m": len(feats),
    }


def safe(m):
    try:
        r = analyse(m)
        print("ok", m["rijksmonumentnummer"], flush=True)
        return r
    except Exception as e:  # noqa: BLE001
        print("FOUT", m["rijksmonumentnummer"], e, file=sys.stderr)
        return {"rijksmonumentnummer": m["rijksmonumentnummer"], "fout": str(e)}


if __name__ == "__main__":
    molens = json.loads(RAW.read_text(encoding="utf-8"))["molens"]
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    if lim:
        molens = molens[:lim]
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(safe, molens))
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("klaar:", sum(1 for r in res if "fout" not in r), "ok,", sum(1 for r in res if "fout" in r), "fout", file=sys.stderr)
