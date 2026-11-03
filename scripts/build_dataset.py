"""Bouw de molendatabase (CSV + JSON voor de site) uit data/rce_raw.json en data/biotoop.json.

Kolomvolgorde en -namen volgen 'Eerste_opzet_molendatabase_westelijk_Nederland.xlsx' (tabblad Molendatabase),
aangevuld met extra kolommen (herkomst, coördinaten, gezicht, biotoopdetails) achteraan.
Velden die niet in RCE/BAG/AHN staan (eigenaar, POM, SIM, wieken, assen, kruiwerk, vang, wielen) blijven leeg.
"""
import csv
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from pyproj import Transformer
from shapely import wkt
from shapely.geometry import shape, mapping
from shapely.ops import transform as shp_transform

ROOT = Path(__file__).resolve().parent.parent
RAW = json.loads((ROOT / "data" / "rce_raw.json").read_text(encoding="utf-8"))
IMG_F = ROOT / "data" / "rce_images.json"
IMG = json.loads(IMG_F.read_text(encoding="utf-8")) if IMG_F.exists() else {}
BIO_F = ROOT / "data" / "biotoop.json"
BIO = {b["rijksmonumentnummer"]: b for b in json.loads(BIO_F.read_text(encoding="utf-8"))} if BIO_F.exists() else {}
CACHE = ROOT / "data" / "cache"
SITE = ROOT / "site" / "data"
SITE.mkdir(parents=True, exist_ok=True)

to_rd = Transformer.from_crs(4326, 28992, always_xy=True).transform
to_ll = Transformer.from_crs(28992, 4326, always_xy=True).transform


def get_json(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.load(r)


# ---------- tekstverwerking ----------
def schoon(t):
    t = t.replace("�", '"').replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return re.sub(r"\s+", " ", t).strip()


YEAR = r"(1[4-9]\d\d|20[0-2]\d)"


def jaar_na(t, woorden, ruimte=40, laatste=False):
    hits = [int(m.group(2)) for m in re.finditer(rf"\b({woorden})\b[^.;]{{0,{ruimte}}}?\b{YEAR}\b", t, re.I)]
    return (hits[-1] if laatste else hits[0]) if hits else None


def eerste(t, opties):
    for label, pat in opties:
        if re.search(pat, t, re.I):
            return label
    return ""


def alle(t, opties):
    return [label for label, pat in opties if re.search(pat, t, re.I)]


FUNCTIES = [
    ("Korenmolen", r"koren(molen)?|graan|meel"), ("Oliemolen", r"olie"), ("Pelmolen", r"pel(molen|ler)"),
    ("Papiermolen", r"papier"), ("Krijtmolen", r"krijt"), ("Houtenzaagmolen", r"zaagmolen|houtzaag"),
    ("Cementmolen", r"cement"), ("Hennepklopper", r"hennep"), ("Kruidenmolen", r"kruiden"),
    ("Mosterdmolen", r"mosterd"), ("Verfmolen", r"verfmolen|verfhout"),
    ("Poldermolen", r"polder|boezem|bemaling|bemaal|gemaal|vijzel|scheprad|wateropvoer|uitmalen|uitmaler|waterschap|wipwater|watermolen"),
]
TYPES = [
    ("Boktjasker", r"boktjasker"), ("Paaltjasker", r"paaltjasker"), ("Paaltjasker", r"tjasker"),
    ("Spinnenkop", r"spinne?kop"), ("Paltrok", r"paltrok"), ("Standerdmolen", r"standerd"),
    ("Wipmolen", r"\bwip(water|koren|poldermolen|molen|-)|wipmolen|wipwatermolen|\bwip\b"),
    ("Weidemolen", r"weidemolen"), ("Zestienkante molen", r"zestienkant"), ("Twaalfkante molen", r"twaalfkant"),
    ("Zeskante molen", r"zeskant"), ("Achtkante molen", r"achtkant"), ("Torenmolen", r"torenmolen"),
    ("Ronde stenen molen", r"ronde?\b|\brond\b"),
]
PLAATSING = [
    ("Stelling op een schuur", r"stelling op (een )?schuur"), ("Beltmolen", r"beltmolen|op (een )?(molen)?belt\b"),
    ("Stellingmolen", r"stellingmolen|\bstelling\b|gestelling"), ("Grondzeiler", r"grondzeiler"),
]
ROMP = [
    ("Zestienkant", r"zestienkant"), ("Twaalfkant", r"twaalfkant"), ("Zeskant", r"zeskant"),
    ("Achtkant", r"achtkant"), ("Rond", r"ronde?\b|\brond\b"),
]
WIEK = [
    ("Zelfzwichting", r"zelfzwicht"), ("Dekker wieksystemen-Dekkerwiek", r"dekker"), ("Fokwiek", r"fokwiek|\bfok\b"),
    ("Van Bussel-stroomlijnroede", r"van bussel"), ("Bilau-wieksysteem", r"bilau"),
    ("Van Riet-wieksysteem", r"van riet"), ("Ten Have-wieksysteem", r"ten have"), ("Remkleppen", r"remklep"),
    ("Oud-Hollands (niet in keuzelijst)", r"oud[- ]?hollands"),
]
VERSIER = [("makelaar", r"makelaar"), ("windvaan", r"windvaan"), ("gevelsteen", r"gevelsteen|sluitsteen|wapensteen"),
           ("baard met jaartal", r"baard")]
ERF = {
    "Erf: Molenaarshuisje": r"molenaarswoning|molenaarshuis|mulderswoning|machinistenwoning|molenaarshuisje",
    "Erf: Winkelhuisje": r"winkel", "Erf: Schuur": r"schuur", "Erf: Moestuintje": r"moestuin",
    "Erf: Dierenhokje": r"dierenhok|geitenhok|kippenhok|hok\b",
}


GENERIEK = {"molen", "watermolen", "poldermolen", "korenmolen", "wipmolen", "windmolen", "stellingmolen", "weidemolen",
            "standerdmolen", "boezemmolen", "wipwatermolen", "oliemolen", "pelmolen", "zaagmolen", "industriemolen"}


def naam_uit_tekst(t):
    for pat in (r'"([^"]{3,45})"', r"'([^']{3,45})'"):
        m = re.search(pat, t)
        if m:
            n = m.group(1).strip(" .,")
            if not re.fullmatch(r"(de )?(achtkante|ronde|houten) molen", n, re.I) and n.lower() not in GENERIEK:
                return n
    m = re.match(r"^([A-Z][\w\- ]{3,40}?(molen|meul|korenmolen))\b[ .,]", t)
    return m.group(1) if m else ""


def bestemming(t):
    m = re.search(r"(?:thans|nu|tegenwoordig)\s+(?:een\s+)?(?:functie als|in gebruik als|gebruikt als|als)\s+([^.;]{3,60})", t, re.I)
    if m:
        return m.group(1).strip()
    if re.search(r"(?:heeft|heeft thans|heeft nu) geen (?:functie|gebruiksfunctie)", t, re.I):
        return "geen functie"
    m = re.search(r"functie als ([^.;]{3,50})", t, re.I)
    return m.group(1).strip() if m else ""


def md_link(naam, plaats):
    """Alleen een zoeklink naar molendatabase.nl (links zijn toegestaan); er worden geen gegevens van die site overgenomen."""
    term = re.sub(r"^(de|het|'t)\s+", "", naam or "", flags=re.I).strip() or plaats
    return ("https://www.molendatabase.nl/molens?mill_search%5Bterm%5D=" + urllib.parse.quote(term)
            + "&mill_search%5Bstate%5D=existing") if term else ""


def gemeente_naam(uri):
    n = uri.rsplit("/", 1)[-1].replace("_(gemeente)", "").replace("_", " ")
    return n


# ---------- gebiedsdata ----------
gem_f = CACHE / "gemeenten_zh.json"
if not gem_f.exists():
    gem_f.write_text(json.dumps(get_json(
        "https://api.pdok.nl/kadaster/bestuurlijkegebieden/ogc/v1/collections/gemeentegebied/items?f=json&limit=100"
        "&crs=http://www.opengis.net/def/crs/EPSG/0/28992&ligt_in_provincie_naam=Zuid-Holland")), encoding="utf-8")
GEM = [(f["properties"]["naam"], shape(f["geometry"])) for f in json.loads(gem_f.read_text(encoding="utf-8"))["features"]
       if f["properties"].get("ligt_in_provincie_naam") == "Zuid-Holland"]
print("gemeenten ZH:", len(GEM))
from shapely.ops import unary_union
ZH = unary_union([g for _, g in GEM])


def gemeente_van(g):
    best = max(GEM, key=lambda a: a[1].intersection(g).area if g.geom_type != "Point" else (1 if a[1].contains(g) else 0))
    return best[0]


# gezichten
gez = {}
for r in RAW["gezichten"]:
    if (r.get("status") or "").lower() != "beschermd":
        continue
    d = gez.setdefault(r["nr"], {"nr": r["nr"], "naam": r.get("naam", ""), "type": r.get("type", ""), "wkt": r["wkt"]})
GEZ = []
for d in gez.values():
    g_ll = wkt.loads(d["wkt"])
    g = shp_transform(to_rd, g_ll)
    if g.intersects(ZH):
        t = d["type"].lower()
        kind = "stadsgezicht" if "stad" in t else "dorpsgezicht" if "dorp" in t else d["type"] or "gezicht"
        GEZ.append({**d, "geom": g, "geom_ll": g_ll, "soort": kind, "gemeente": gemeente_van(g.intersection(ZH))})
print("beschermde gezichten ZH:", len(GEZ))

# ---------- molen per molen ----------
rows, js = [], []
for m in sorted(RAW["molens"], key=lambda m: int(m["rijksmonumentnummer"])):
    nr = m["rijksmonumentnummer"]
    tekst = " ".join(schoon(o["tekst"]) for o in m["omschrijvingen"] if o["soort"] == "rijksmonumentomschrijving")
    alle_tekst = " ".join(schoon(o["tekst"]) for o in m["omschrijvingen"])
    t = tekst
    geom = shp_transform(to_rd, wkt.loads(m["wkt"]))
    pt = geom.centroid
    lon, lat = to_ll(pt.x, pt.y)
    b = BIO.get(nr, {})
    herkomst = []

    # adres
    bag = [a for a in m.get("bag", []) if a.get("straat") or a.get("adres")]
    straat = huisnr = pc = plaats = ""
    if bag:
        a = bag[0]
        straat, huisnr, pc, plaats = a.get("straat", ""), a.get("hnr", ""), a.get("pc", ""), a.get("plaats", "")
        if len(bag) > 1:
            huisnr = ", ".join(sorted(dict.fromkeys(x.get("hnr", "") for x in bag if x.get("hnr")), key=lambda h: (int(re.match(r"\d+", h).group()) if re.match(r"\d+", h) else 0, h)))
        herkomst.append("adres: BAG via RCE")
    else:
        ls = get_json(f"https://api.pdok.nl/bzk/locatieserver/search/v3_1/reverse?lon={lon:.6f}&lat={lat:.6f}&type=adres&rows=1"
                      "&fl=straatnaam,huisnummer,huisletter,huisnummertoevoeging,postcode,woonplaatsnaam,afstand")["response"]["docs"]
        if ls:
            a = ls[0]
            straat = a.get("straatnaam", "")
            huisnr = f'{a.get("huisnummer", "")}{a.get("huisletter", "")}{("-" + a["huisnummertoevoeging"]) if a.get("huisnummertoevoeging") else ""}'
            pc, plaats = a.get("postcode", ""), a.get("woonplaatsnaam", "")
            herkomst.append(f'adres: dichtstbijzijnde BAG-adres ({a.get("afstand", "?")} m, PDOK)')
    gemeente = gemeente_naam(m["gem"]) if m.get("gem") else gemeente_van(pt)

    # naam
    naam = m["namen"][0] if m.get("namen") else naam_uit_tekst(tekst)
    naam_bron = "RCE naam" if m.get("namen") else ("uit omschrijving" if naam else "")

    # jaren
    jb, jb_bron = None, ""
    for g in m.get("gebeurtenissen", []):
        if g["gebeurtenis"].lower() == "vervaardiging" and g.get("van") and g.get("tot") and g["van"][:4] == g["tot"][:4]:
            jb, jb_bron = int(g["van"][:4]), "RCE datering"
            break
    if not jb:
        jb = jaar_na(t, r"gebouwd|bouwjaar|gedateerd|dateert|uit|opgericht|gesticht|vervaardigd", 25)
        jb_bron = "RCE omschrijving" if jb else ""
    if not jb:
        rest = re.sub(rf"(gerestaureerd|restauratie\w*|hersteld|brand|afgebrand|verbrand|verplaatst|overgeplaatst|herbouwd|verbouwd)[^.;]{{0,40}}?{YEAR}", " ", t, flags=re.I)
        jaren = set(re.findall(rf"{YEAR}", rest))
        if len(jaren) == 1:
            jb, jb_bron = int(jaren.pop()), "RCE omschrijving (enige jaartal, onzeker)"
    if not jb and b.get("bag_bouwjaar_pand"):
        jb, jb_bron = b["bag_bouwjaar_pand"], "BAG bouwjaar pand"
    jherb = jaar_na(t, r"herbouwd|herbouw|verplaatst|overgeplaatst|herplaatst|opnieuw opgebouwd|verbouwd", 40)
    jbrand = jaar_na(t, r"brand|afgebrand|verbrand|uitgebrand|door brand", 30)
    jrest = jaar_na(t, r"gerestaureerd|restauratie|restauraties|hersteld", 25, laatste=True)

    aandrijving = "Watermolen" if re.search(r"onderslag|bovenslag|middenslag|waterrad|getijmolen|turbine", t, re.I) else "Windmolen"
    typ = eerste(t, TYPES) if aandrijving == "Windmolen" else ""
    plaatsing = eerste(t, PLAATSING) if typ not in ("Wipmolen", "Standerdmolen", "Paltrok", "Spinnenkop", "Paaltjasker", "Boktjasker") else ""
    funcs = alle(t, FUNCTIES)
    if "Poldermolen" in funcs and len(funcs) > 1 and "Korenmolen" in funcs and not re.search(r"polder|boezem|bemaling", t, re.I):
        funcs.remove("Poldermolen")
    if not funcs and "Molen" in m["functies"] and b:
        funcs = []
    romp = eerste(t, ROMP)
    steen = re.search(r"stenen|gemetseld|baksteen|bakstenen|metselwerk", t, re.I)
    hout = re.search(r"houten|hout\b|wip|standerd|tjasker|paltrok|spinne?kop", t, re.I)
    if steen and hout and re.search(r"(op|met) (een )?(stenen|bakstenen|gemetselde) (voet|onderbouw|romp|veldmuren|fundering)", t, re.I):
        bouwk = "Hout op stenen voet"
    elif romp == "Rond" and steen:
        bouwk = "Steen"
    else:
        bouwk = "Steen" if steen and not hout else "Hout" if hout and not steen else ("Hout en steen" if steen and hout else "")
    vlucht = re.search(r"vlucht[^0-9]{0,20}(\d{2}(?:[.,]\d)?)\s*m", t, re.I)
    wieksys = "; ".join(alle(t, WIEK))
    eigenaar = ""
    mo = re.search(r"eigendom van (?:de |het )?([^.,;]{3,60})", t, re.I)
    if mo:
        eigenaar = mo.group(1).strip()

    # gezichten
    binnen, gz_namen, gz_soort, afstand = "Nee", [], [], None
    for z in GEZ:
        if z["geom"].intersects(pt) or z["geom"].intersects(geom):
            binnen = "Ja"
            gz_namen.append(z["naam"])
            gz_soort.append(z["soort"])
        else:
            dd = z["geom"].distance(pt)
            afstand = dd if afstand is None else min(afstand, dd)

    # biotoop
    kl = b.get("klasse", {})
    rd_row = {
        "Monumentnummer": nr, "Naam": naam or "Naamloos", "Jaar bouw": jb or "", "Jaar herbouw": jherb or "", "Brand jaar": jbrand or "",
        "Straat": straat, "Huisnr.": huisnr, "Postcode": pc, "Plaats": plaats, "Gemeente": gemeente, "Provincie": "Zuid-Holland",
        "Eigenaar": eigenaar, "POM: Ja of nee": "", "Laatste SIM/jaar aanvraag": "", "Laatste restauratie jaar": jrest or "",
        "Aandrijving: Windmolen, Watermolen, Rosmolen": aandrijving,
        "TYPE WINDMOLEN: Standerdmolen, Wipmolen, Spinnenkop, Weidemolen, Paltrok, Achtkante molen, Zeskante molen, Twaalfkante molen, Zestienkante molen, Torenmolen, Ronde stenen molen, Paaltjasker, Boktjasker": typ,
        "Plaatsing van de molen: Grondzeiler, Beltmolen, Stellingmolen, Stelling op een schuur": plaatsing,
        "Hoogte van de stelling of belt(m)": "",
        "TYPE WATERRAD: Onderslagmolen, Middenslagmolen, Bovenslagmolen, Turbinemolen": eerste(t, [("Onderslagmolen", r"onderslag"), ("Middenslagmolen", r"middenslag"), ("Bovenslagmolen", r"bovenslag"), ("Turbinemolen", r"turbine")]),
        "SITUERING MOLEN: Enkele watermolen, dubbele watermolen": "",
        "Standplaats: Rivier, Beek, Molenvijver": "",
        "Functie: Korenmolen, Oliemolen, Papiermolen, Krijtmolen,  Houtenzaagmolen, Cementmolen, Hennepklopper, Kruidenmolen, Mosterdmolen, Pelmolen, Poldermolen, Verfmolen, ": ", ".join(funcs),
        "Hiudige Bestemming": bestemming(t),
        "Bouwkenmerken: Hout, Steen": bouwk, "Romptype": romp, "Kap type": "",
        "Versieringen": ", ".join(alle(t, VERSIER)),
        "Vlucht (m)": vlucht.group(1).replace(",", ".") if vlucht else "",
    }
    # lege template-kolommen (wieken t/m erf) in volgorde
    for h in ("Binnenroede lengte (m)", "Buitenroede lengte (m)", "Fabrikant", "Roedenummer", "Fabricagejaar",
              "Binnenroede/ Gestoken jaar", "Buitenroeden/ Gestoken jaar"):
        rd_row[h] = ""
    rd_row["Wieksysteem: Zelfzwichting, Dekker wieksystemen- Dekkerwiek,  Dekker wieksystemen-Spleet- of half-Dekkerwiek, Van Bussel-stroomlijnroede, Fokwiek, Bilau-wieksysteem, Van Riet-wieksysteem, Ten Have-wieksysteem, Remkleppen"] = wieksys
    for h in ("Wieksysteem/verbetering jaar", "Bovenas: Hout of ijzer", " Bovenas fabrikant", "Asnummer", "Fabricagejaar (bovenas)", "Lengte(m)",
              "Plaats van Bediening: Binnenkruier, Buitenkruier", "Plaats van het draaipunt: Bovenkruier, Onderkruier, Middenkruier",
              "Uitvoering van het kruiwerk: Zetelkruiwerk, Sleepkruiwerk, Rollekruiwerk",
              "Type kruiwerk: Neutenkruiwerk, voeghoutenkruiwerk, houtenrollen, ijzerenrollen, Engels kruiwerk, zetel",
              "Staart: geklonken staal, gelaast staal, Hout", "Staart met galg: ja, nee", "Bediening kruiwerk", "Vang: Type",
              "Vang: Soort vangbalk", "Vang: Vangstok", "Vang: Trekvang", "Vang: Pal",
              "Wielen en werktuigen: Bovenwiel aantal kammen", "Wielen en werktuigen: Bovenschijfloop aantal staven",
              "Wielen en werktuigen: Spoorwiel aantal kammen", "Wielen en werktuigen: Steenschijfloop aantal staven",
              "Wielen en werktuigen: Overbrengingsverhouding"):
        rd_row[h] = ""
    for h, pat in ERF.items():
        rd_row[h] = "Ja" if re.search(pat, t, re.I) else ""
    for d in ("N", "NO", "O", "ZO", "Z", "ZW", "W", "NW"):
        rd_row[f"Molenbiotoop: {d}"] = kl.get(d, "")
    # extra kolommen
    rd_row.update({
        "Binnen beschermd stads-/dorpsgezicht (Ja/Nee)": binnen,
        "Beschermd gezicht": "; ".join(dict.fromkeys(gz_namen)),
        "Soort gezicht": "; ".join(dict.fromkeys(gz_soort)),
        "Afstand tot dichtstbijzijnd beschermd gezicht (m)": "" if binnen == "Ja" or afstand is None else round(afstand),
        "Bebouwde kom (RCE)": m.get("kom", ""),
        "Functie volgens RCE-thesaurus (oorspronkelijk)": "; ".join(m["functies"]),
        "Omschrijving RCE": tekst,
        "Hoogte molen (m, uit AHN)": b.get("hoogte_molen_ahn", ""),
        "Bebouwd oppervlak binnen 100 m (aandeel)": b.get("bebouwd_100m", ""),
        "Bebouwd oppervlak binnen 400 m (aandeel)": b.get("bebouwd_400m", ""),
        "Boomkruinen binnen 100 m (aandeel)": b.get("boomdek_100m", ""),
        "Boomkruinen binnen 400 m (aandeel)": b.get("boomdek_400m", ""),
        "Hoogste obstakel binnen 400 m (m)": b.get("hoogste_obstakel_400m", ""),
        "Herkomst jaar bouw": jb_bron, "Herkomst naam": naam_bron, "Herkomst adres": "; ".join(herkomst),
        "Breedtegraad": round(lat, 6), "Lengtegraad": round(lon, 6), "RD x": round(pt.x), "RD y": round(pt.y),
        "Aantal RCE-afbeeldingen": len(IMG.get(nr, [])),
        "RCE-afbeelding (miniatuur)": IMG[nr][0]["thumb"] if IMG.get(nr) else "",
        "RCE-beeldbankpagina": IMG[nr][0]["pagina"] if IMG.get(nr) else "",
        "Licentie afbeelding": IMG[nr][0]["licentie"] if IMG.get(nr) else "",
        "Zoeklink Nederlandse Molendatabase": md_link(naam, plaats),
        "Monumentenregister": f"https://monumentenregister.cultureelerfgoed.nl/monumenten/{nr}",
        "Linked data RCE": m["uri"],
    })
    rows.append(rd_row)
    js.append({"nr": nr, "naam": rd_row["Naam"], "lat": round(lat, 6), "lon": round(lon, 6), "row": rd_row,
               "afbeeldingen": [{k: v for k, v in i.items() if k != "open_licentie"} for i in IMG.get(nr, []) if i["open_licentie"] and i["thumb"]],
               "biotoop": {"score": b.get("score"), "dominant": b.get("dominant"), "klasse": kl}})

cols = list(rows[0].keys())
with open(ROOT / "site" / "molens.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=cols, delimiter=";")
    w.writeheader()
    w.writerows(rows)

# tabblad stads- en dorpsgezichten (alle beschermde gezichten in Zuid-Holland, met molens erbinnen)
gz_rows = []
for z in sorted(GEZ, key=lambda z: (z["gemeente"], z["naam"])):
    inside = [r for r in rows if z["naam"] in r["Beschermd gezicht"].split("; ") and r["Binnen beschermd stads-/dorpsgezicht (Ja/Nee)"] == "Ja"]
    base = {"Provincie": "Zuid-Holland", "Gemeente": z["gemeente"],
            "Beschermd stadsgezicht": z["naam"] if z["soort"] == "stadsgezicht" else "",
            "Beschermd dorpsgezicht": z["naam"] if z["soort"] == "dorpsgezicht" else ""}
    if not inside:
        gz_rows.append({**base, "MN": "Geen", "Molennaam": "", "adres": "", "Binnen beschermde stads_ en dorpsgezichten(Ja/Nee)": "Nee"})
    for r in inside:
        gz_rows.append({**base, "MN": r["Monumentnummer"], "Molennaam": r["Naam"],
                        "adres": f'{r["Straat"]} {r["Huisnr."]}, {r["Postcode"]} {r["Plaats"]}'.strip(", "),
                        "Binnen beschermde stads_ en dorpsgezichten(Ja/Nee)": "Ja"})
with open(ROOT / "site" / "stads_en_dorpsgezichten.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(gz_rows[0].keys()), delimiter=";")
    w.writeheader()
    w.writerows(gz_rows)

# site-data
(SITE / "molens.json").write_text(json.dumps({"kolommen": cols, "molens": js}, ensure_ascii=False), encoding="utf-8")
feats = []
for z in GEZ:
    if any(r["Beschermd gezicht"] and z["naam"] in r["Beschermd gezicht"].split("; ") for r in rows) or True:
        g = z["geom_ll"].simplify(0.00005)
        feats.append({"type": "Feature", "geometry": mapping(g),
                      "properties": {"naam": z["naam"], "soort": z["soort"], "gemeente": z["gemeente"], "nr": z["nr"]}})
(SITE / "gezichten.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")
print("molens:", len(rows), "| in gezicht:", sum(r["Binnen beschermd stads-/dorpsgezicht (Ja/Nee)"] == "Ja" for r in rows),
      "| gezichten-rijen:", len(gz_rows))
for c in ("Naam", "Jaar bouw", "Jaar herbouw", "Brand jaar", "Laatste restauratie jaar", "TYPE WINDMOLEN: Standerdmolen, Wipmolen, Spinnenkop, Weidemolen, Paltrok, Achtkante molen, Zeskante molen, Twaalfkante molen, Zestienkante molen, Torenmolen, Ronde stenen molen, Paaltjasker, Boktjasker", "Bouwkenmerken: Hout, Steen", "Eigenaar", "Hiudige Bestemming", "Molenbiotoop: N"):
    n = sum(1 for r in rows if r[c] not in ("", "Naamloos"))
    print(f"  gevuld {n:3d}/{len(rows)}  {c[:40]}")

