"""Erf- en perceelanalyse per molen: welke gebouwen staan op hetzelfde kadastrale perceel, tegenaan, of op een aangrenzend perceel?

Bronnen (PDOK): BRK Kadastrale kaart (percelen), BAG (panden en verblijfsobjecten met gebruiksdoel),
en het RCE CHO-endpoint om te zien of een nabij pand zelf rijksmonument is (en met welke functie).
Invoer : data/rce_raw.json, data/cache/<nr>_bag.json (panden, uit build_biotoop.py)
Uitvoer: data/erf.json en site/data/erf/<nr>.json (GeoJSON voor de kaart, WGS84)
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pyproj import Transformer
from shapely import wkt
from shapely.geometry import shape, mapping, Point
from shapely.ops import transform as shp_transform, unary_union

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
OUT = ROOT / "data" / "erf.json"
SITE = ROOT / "site" / "data" / "erf"
SITE.mkdir(parents=True, exist_ok=True)
CRS = "http://www.opengis.net/def/crs/EPSG/0/28992"
PERCEEL = "https://api.pdok.nl/kadaster/brk-kadastrale-kaart/ogc/v1_0/collections/perceel/items"
VBO = "https://api.pdok.nl/kadaster/bag/ogc/v2/collections/verblijfsobject/items"
BAG = "https://api.pdok.nl/kadaster/bag/ogc/v2/collections/pand/items"
RCE = "https://api.linkeddata.cultureelerfgoed.nl/datasets/rce/cho/services/cho/sparql"
R = 150          # zoekstraal voor percelen en gebouwen (m)
NABIJ = 100      # gebouwen binnen deze afstand worden meegeteld
to_ll = Transformer.from_crs(28992, 4326, always_xy=True).transform


def get(url, tries=4):
    last = None
    for _ in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=100) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2)
    raise RuntimeError(f"{url[:100]}: {last}")


def paged(base, bbox, name):
    f = CACHE / name
    if not f.exists():
        feats, url = [], f"{base}?bbox={bbox}&bbox-crs={CRS}&crs={CRS}&limit=1000&f=json"
        while url:
            d = json.loads(get(url))
            feats += d["features"]
            url = next((l["href"] for l in d.get("links", []) if l.get("rel") == "next"), None)
        f.write_text(json.dumps(feats), encoding="utf-8")
    return json.loads(f.read_text(encoding="utf-8"))


def sparql(q):
    data = urllib.parse.urlencode({"query": q}).encode()
    for t in range(4):
        try:
            req = urllib.request.Request(RCE, data=data, headers={"Accept": "application/sparql-results+json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return [{k: v["value"] for k, v in b.items()} for b in json.load(r)["results"]["bindings"]]
        except Exception:  # noqa: BLE001
            time.sleep(5 * (t + 1))
    raise SystemExit("sparql mislukt")


def aanduiding(p):
    return f'{p["akr_kadastrale_gemeente_code_waarde"]} {p["sectie"]} {p["perceelnummer"]}'


def analyse(m, panden_rm, gerelateerd):
    nr = m["rijksmonumentnummer"]
    geom = wkt.loads(m["rd"])
    c = geom.centroid
    x, y = round(c.x), round(c.y)
    bbox = f"{x - R},{y - R},{x + R},{y + R}"
    panden = paged(BAG, bbox, f"{nr}_bag150.json")
    percelen = paged(PERCEEL, bbox, f"{nr}_perceel.json")
    vbos = paged(VBO, bbox, f"{nr}_vbo.json")
    doel = {}
    for v in vbos:
        p = v["properties"]
        for h in p.get("pand.href", []) or []:
            d = doel.setdefault(h.rsplit("/", 1)[-1], {"doelen": set(), "m2": 0, "n": 0})
            d["doelen"].add(p.get("gebruiksdoel") or "onbekend")
            d["m2"] += p.get("oppervlakte") or 0
            d["n"] += 1
    P = [(shape(f["geometry"]), f["properties"]) for f in percelen]
    fp = geom.buffer(1.5) if geom.area < 5 else geom
    # perceel van de molen: percelen die de voetafdruk raken, meest overlappende eerst
    cand = sorted(((g.intersection(fp).area, g, p) for g, p in P if g.intersects(fp)), key=lambda t: -t[0])
    mp = [t for t in cand if t[0] > 0.15 * max(cand[0][0], 1e-9)] if cand else []
    if not mp:
        raise RuntimeError("geen perceel gevonden")
    MP = unary_union([t[1] for t in mp])
    mill_percelen = [aanduiding(t[2]) for t in mp]
    adj_geoms = [(g, p) for g, p in P if not any(g.equals(t[1]) for t in mp) and g.distance(MP) < 0.5]
    adj = unary_union([g for g, _ in adj_geoms]) if adj_geoms else None

    own = {b.get("pand") for b in m.get("bag", [])}
    rijen, feats = [], []
    gerel_g = [(o, wkt.loads(o["rd"])) for o in gerelateerd]
    gb = geom if geom.area > 0 else geom.buffer(1)
    eigen_ids = {f["properties"].get("identificatie") for f in panden if shape(f["geometry"]).intersection(gb).area > 0.3 * gb.area}
    if not eigen_ids:  # terugval: BAG-pand uit de RCE-koppeling
        eigen_ids = set(own)
    for f in panden:
        g, p = shape(f["geometry"]), f["properties"]
        pid, uuid = p.get("identificatie"), f.get("id")
        if g.distance(geom) > NABIJ:
            continue
        eigen = pid in eigen_ids
        dist = g.distance(geom)
        ov = g.intersection(MP).area / g.area if g.area else 0
        pc = max(((g.intersection(pg).area, pp) for pg, pp in P if g.intersects(pg)), default=(0, None), key=lambda t: t[0])[1]
        if eigen:
            rel = "de molen zelf"
        elif dist <= 1.0:
            rel = "tegenaan"
        elif ov >= 0.5:
            rel = "zelfde perceel"
        elif adj is not None and g.intersection(adj).area >= 0.5 * g.area:
            rel = "aangrenzend perceel"
        else:
            rel = "ander perceel"
        d = doel.get(uuid, {"doelen": set(), "m2": 0, "n": 0})
        gebruik = ", ".join(sorted(d["doelen"])) if d["doelen"] else "geen verblijfsobject (bijgebouw)"
        rm = panden_rm.get(pid)
        if not rm:  # geometrische koppeling met een gerelateerd RCE-monument (RCE en BAG wijzen soms naar verschillende panden)
            for o, og in gerel_g:
                if og.area and g.intersection(og).area > 0.5 * min(g.area, og.area):
                    rm = {"nr": o["rijksmonumentnummer"], "functies": o["functies"]}
                    break
        rij = {"pand": pid, "afstand": round(dist, 1), "relatie": rel, "gebruik": gebruik, "m2": round(g.area),
               "bouwjaar": p.get("bouwjaar"), "status": p.get("status"), "perceel": aanduiding(pc) if pc else "",
               "rijksmonument": rm}
        rijen.append(rij)
        feats.append({"type": "Feature", "geometry": mapping(shp_transform(to_ll, g.simplify(0.2))),
                      "properties": {"soort": "pand", **{k: v for k, v in rij.items() if k in ("relatie", "afstand", "gebruik", "bouwjaar", "rijksmonument", "perceel")}}})
    rijen.sort(key=lambda r: r["afstand"])
    ander = [r for r in rijen if r["relatie"] != "de molen zelf"]
    tel = {k: sum(1 for r in ander if r["relatie"] == k) for k in ("tegenaan", "zelfde perceel", "aangrenzend perceel", "ander perceel")}
    woon_erf = [r for r in ander if r["relatie"] in ("tegenaan", "zelfde perceel") and "woonfunctie" in r["gebruik"]]
    bijgeb_erf = [r for r in ander if r["relatie"] in ("tegenaan", "zelfde perceel") and "woonfunctie" not in r["gebruik"]]
    # gerelateerde rijksmonumenten (molenaarswoning e.d.) bij deze molen
    rel_m = []
    for o in gerelateerd:
        og = wkt.loads(o["rd"])
        d = og.distance(geom)
        if og.intersects(MP) or og.centroid.within(MP):
            r_ = "zelfde perceel"
        elif d <= 1.0:
            r_ = "tegenaan"
        elif adj is not None and (og.intersects(adj) or og.centroid.within(adj)):
            r_ = "aangrenzend perceel"
        elif d <= NABIJ:
            r_ = f"{round(d)} m"
        else:
            continue
        rel_m.append({"rijksmonumentnummer": o["rijksmonumentnummer"], "functies": o["functies"], "relatie": r_, "afstand": round(d, 1)})
    view = Point(c.x, c.y).buffer(110)  # grote percelen (wegen e.d.) afknippen voor de kaart
    for g_, p_ in [(t[1], t[2]) for t in mp] + adj_geoms:
        mijn = any(g_.equals(t[1]) for t in mp)
        gk = g_.intersection(view)
        if gk.is_empty:
            continue
        feats.append({"type": "Feature", "geometry": mapping(shp_transform(to_ll, gk.simplify(0.1))),
                      "properties": {"soort": "perceel", "perceel": aanduiding(p_), "molenperceel": mijn, "m2": p_.get("kadastrale_grootte_waarde")}})
    feats.append({"type": "Feature", "geometry": mapping(shp_transform(to_ll, geom if geom.area > 0 else Point(c.x, c.y))), "properties": {"soort": "molen"}})
    (SITE / f"{nr}.json").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")), encoding="utf-8")
    return {
        "rijksmonumentnummer": nr, "molenpercelen": mill_percelen,
        "molenperceel_m2": sum(t[2].get("kadastrale_grootte_waarde") or 0 for t in mp),
        "aantal_aangrenzende_percelen": len(adj_geoms),
        "tel": tel, "woning_op_erf": len(woon_erf), "bijgebouwen_op_erf": len(bijgeb_erf),
        "dichtstbij": ander[:5], "gerelateerd": rel_m,
    }


def safe(args):
    try:
        return analyse(*args)
    except Exception as e:  # noqa: BLE001
        print("FOUT", args[0]["rijksmonumentnummer"], e, file=sys.stderr, flush=True)
        return {"rijksmonumentnummer": args[0]["rijksmonumentnummer"], "fout": str(e)}


if __name__ == "__main__":
    raw = json.loads((ROOT / "data" / "rce_raw.json").read_text(encoding="utf-8"))["molens"]
    molens = [m for m in raw if m.get("categorie", "Molen") == "Molen"]
    gerel = [m for m in raw if m.get("categorie") == "Molengerelateerd"]
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    if lim:
        molens = molens[:lim]
    # welke panden in de buurt zijn zelf rijksmonument? (RCE-koppeling BAG-pand -> rijksmonument en functie)
    pids = set()
    for m in molens:
        c = wkt.loads(m["rd"]).centroid
        x, y = round(c.x), round(c.y)
        try:
            for f in paged(BAG, f"{x - R},{y - R},{x + R},{y + R}", f"{m['rijksmonumentnummer']}_bag150.json"):
                pids.add(f["properties"]["identificatie"])
        except Exception as e:  # noqa: BLE001
            print("bag-fout", m["rijksmonumentnummer"], e, file=sys.stderr)
    pids = sorted(pids)
    print("panden in de buurt:", len(pids), file=sys.stderr, flush=True)
    pandrm = {}
    for i in range(0, len(pids), 150):
        ch = pids[i:i + 150]
        q = ("PREFIX ceo: <https://linkeddata.cultureelerfgoed.nl/def/ceo#> PREFIX skos: <http://www.w3.org/2004/02/skos/core#> "
             "SELECT DISTINCT ?pid ?nr ?f WHERE { VALUES ?pid { " + " ".join(f'"{p}"' for p in ch) + " } "
             "?b ceo:pandIdentificatie ?pid . ?rm ceo:heeftBasisregistratieRelatie/ceo:heeftBAGRelatie ?b ; ceo:rijksmonumentnummer ?nr . "
             "OPTIONAL { ?rm ceo:heeftOorspronkelijkeFunctie/ceo:heeftFunctieNaam/skos:prefLabel ?f . FILTER(lang(?f)=\"nl\") } }")
        for r in sparql(q):
            e = pandrm.setdefault(r["pid"], {"nr": r["nr"], "functies": []})
            if r.get("f") and r["f"] not in e["functies"]:
                e["functies"].append(r["f"])
    print("nabije rijksmonument-panden:", len(pandrm), file=sys.stderr, flush=True)
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(safe, [(m, pandrm, gerel) for m in molens]))
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("klaar:", sum(1 for r in res if "fout" not in r), "ok,", sum(1 for r in res if "fout" in r), "fout", file=sys.stderr)
