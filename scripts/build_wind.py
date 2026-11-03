"""Windgewogen molenbiotoop: de hinderscore per windrichting wegen met de lokale windroos.

Per molen: de 3 dichtstbijzijnde KNMI-stations, gewogen op 1/afstand^2, leveren een windroos
(frequentie en energieaandeel per richting). De windgewogen index is de som over de 8 richtingen van
gewicht x hinderscore (de scores uit build_biotoop.py). Klassegrenzen zijn dezelfde als bij het gemiddelde
(Goed < 0,15, Matig < 0,45, anders Slecht).
Invoer : data/rce_raw.json, data/biotoop.json, data/knmi_windroos.json
Uitvoer: data/wind.json
"""
import json
import math
from pathlib import Path

from pyproj import Transformer
from shapely import wkt
from shapely.ops import transform as shp_transform

ROOT = Path(__file__).resolve().parent.parent
DIRS = ["N", "NO", "O", "ZO", "Z", "ZW", "W", "NW"]
PERIODE = "1991-2020"   # klimaatnormaal; "2014-2023" is ook beschikbaar
K = 3                   # aantal stations
MIN_DEKKING = 0.8       # station telt mee als minstens 80% van de uren in de periode geldig is
to_ll = Transformer.from_crs(28992, 4326, always_xy=True).transform


def klasse(x):
    return "Goed" if x < 0.15 else "Matig" if x < 0.45 else "Slecht"


def afstand_km(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(a))


def main():
    raw = {m["rijksmonumentnummer"]: m for m in json.loads((ROOT / "data" / "rce_raw.json").read_text(encoding="utf-8"))["molens"]}
    bio = {b["rijksmonumentnummer"]: b for b in json.loads((ROOT / "data" / "biotoop.json").read_text(encoding="utf-8")) if "score" in b}
    knmi = json.loads((ROOT / "data" / "knmi_windroos.json").read_text(encoding="utf-8"))
    y0, y1 = (int(x) for x in PERIODE.split("-"))
    verwacht = (y1 - y0 + 1) * 8766
    st = {k: v for k, v in knmi["stations"].items() if PERIODE in v.get("perioden", {}) and "lat" in v
          and (v["perioden"][PERIODE]["geldig"] + v["perioden"][PERIODE]["stil_of_variabel"]) >= MIN_DEKKING * verwacht}
    print("stations gebruikt:", {k: v["naam"] for k, v in st.items()}, "| uitgesloten (te weinig data):", [v["naam"] for k, v in knmi["stations"].items() if k not in st])
    out = {}
    for nr, b in bio.items():
        m = raw.get(nr)
        if not m or m.get("categorie", "Molen") != "Molen":
            continue
        c = shp_transform(to_ll, wkt.loads(m["rd"])).centroid
        naast = sorted(((afstand_km(c.y, c.x, v["lat"], v["lon"]), k) for k, v in st.items()))[:K]
        gew = [1 / max(d, 1.0) ** 2 for d, _ in naast]
        s = sum(gew)
        gew = [g / s for g in gew]
        freq = [sum(g * st[k]["perioden"][PERIODE]["freq"][i] for g, (_, k) in zip(gew, naast)) for i in range(8)]
        en = [sum(g * st[k]["perioden"][PERIODE]["energie"][i] for g, (_, k) in zip(gew, naast)) for i in range(8)]
        sc = [b["score"][d] for d in DIRS]
        ie, i_f, im = (sum(w * x for w, x in zip(en, sc)), sum(w * x for w, x in zip(freq, sc)), sum(sc) / 8)
        out[nr] = {
            "periode": PERIODE,
            "stations": [{"id": k, "naam": st[k]["naam"], "afstand_km": round(d, 1), "gewicht": round(g, 3)} for g, (d, k) in zip(gew, naast)],
            "freq": [round(x, 4) for x in freq], "energie": [round(x, 4) for x in en],
            "index_energie": round(ie, 3), "klasse_energie": klasse(ie),
            "index_freq": round(i_f, 3), "klasse_freq": klasse(i_f),
            "index_gemiddeld": round(im, 3), "klasse_gemiddeld": klasse(im),
            "overheersend_energie": DIRS[max(range(8), key=lambda i: en[i])],
            "overheersend_freq": DIRS[max(range(8), key=lambda i: freq[i])],
            "bijdrage_energie": [round(w * x, 4) for w, x in zip(en, sc)],
        }
    (ROOT / "data" / "wind.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    verschil = sum(1 for r in out.values() if r["klasse_energie"] != r["klasse_gemiddeld"])
    print(f"{len(out)} molens; klasse windgewogen (energie) anders dan gemiddeld: {verschil}")


if __name__ == "__main__":
    main()
