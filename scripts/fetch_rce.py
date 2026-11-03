"""Haal alle rijksmonumentale molens in Zuid-Holland op bij het RCE CHO SPARQL-endpoint.

Queries zijn eerst ontworpen en gevalideerd via de rce-cho MCP (zelfde endpoint);
dit script draait ze in bulk en schrijft data/rce_raw.json.
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

ENDPOINT = "https://api.linkeddata.cultureelerfgoed.nl/datasets/rce/cho/services/cho/sparql"
OUT = Path(__file__).resolve().parent.parent / "data" / "rce_raw.json"
PFX = """PREFIX ceo: <https://linkeddata.cultureelerfgoed.nl/def/ceo#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX geo: <http://www.opengis.net/ont/geosparql#>
"""
PROV = "<http://standaarden.overheid.nl/owms/terms/Zuid-Holland>"
RM_STATUS = "b2d9a59a-fe1e-4552-9a05-3c2acddff864"  # rijksmonument (uri-pad bevat /rn/2/)


def sparql(q, label="", tries=4):
    data = urllib.parse.urlencode({"query": PFX + q}).encode()
    for t in range(tries):
        req = urllib.request.Request(ENDPOINT, data=data, headers={"Accept": "application/sparql-results+json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                res = json.load(r)
            return [{k: v["value"] for k, v in b.items()} for b in res["results"]["bindings"]]
        except Exception as e:
            print(f"  poging {t + 1} mislukt ({label}): {e}", file=sys.stderr)
            time.sleep(5 * (t + 1))
    raise SystemExit(f"query mislukt: {label}")


# 1. Welke monumenten zijn molens? Via de functiehierarchie in de RCE-thesaurus:
#    elk concept onder "Industrie- en poldermolen" (en het concept "Molen") is een oorspronkelijke functie.
ROOTS = ["a3dbebf9-a237-4caa-9ee6-347c9d30dd9e", "fea024ba-83a0-4418-afbe-3b7b4588797e"]
TERM = "https://data.cultureelerfgoed.nl/term/id/rn/2/"
concepten = {}
for root in ROOTS:
    for r in sparql(f"""SELECT DISTINCT ?c ?l WHERE {{
      GRAPH <{TERM}thesaurus> {{ ?c skos:broader* <{TERM}{root}> . ?c skos:prefLabel ?l }} }}""", "thesaurus"):
        concepten[r["c"]] = r["l"]
# Bijbehorende functies (geen molen zelf): molenaarswoning, molenaarshuis, roedenloods, ...
ANC_IN = {TERM + x for x in ("a4de54e7-a3a6-43aa-ba2c-543f1a124a04",   # Molenaarswoning(M), onder Industrie- en poldermolen
                              "b1504243-3b50-4657-a040-741242c2d40e",   # Molenaarshuis
                              "82659c9d-356f-4d04-b813-053af9fdaa64")}  # Roedenloods
EXTRA = {TERM + x for x in ("a6337da5-873e-489d-a2df-4db31b719bf4",    # Molenaarswoning(K), buiten de molen-tak
                             "f1be4411-59f2-4648-b8b4-3c4b79010df7",    # Zaagmolen, buiten de molen-tak
                             "201130ca-bd97-4d90-adfd-b1aeb0381149")}   # Meelfabriek, buiten de molen-tak
for r in sparql(f"""SELECT ?c ?l WHERE {{ GRAPH <{TERM}thesaurus> {{ VALUES ?c {{ {" ".join(f"<{c}>" for c in EXTRA)} }} ?c skos:prefLabel ?l }} }}""", "extra functies"):
    concepten[r["c"]] = r["l"]
print("functieconcepten:", len(concepten), file=sys.stderr)

mills = sparql(f"""
SELECT DISTINCT ?rm ?nr ?c WHERE {{
  VALUES ?c {{ {" ".join(f"<{c}>" for c in concepten)} }}
  ?rm ceo:heeftOorspronkelijkeFunctie/ceo:heeftFunctieNaam ?c ;
      ceo:heeftBasisregistratieRelatie/ceo:heeftProvincie {PROV} ;
      ceo:rijksmonumentnummer ?nr ; ceo:heeftJuridischeStatus ?st .
  FILTER(CONTAINS(STR(?st),"{RM_STATUS}"))
}}""", "molens")
print("molen-rijen:", len(mills), file=sys.stderr)

recs = {}
for r in mills:
    d = recs.setdefault(r["rm"], {"uri": r["rm"], "rijksmonumentnummer": r["nr"], "functies": []})
    d["functies"].append(concepten[r["c"]])
ANC_LABELS = {concepten[c] for c in ANC_IN | EXTRA if c in concepten}
for d in recs.values():
    d["functies"] = sorted(set(d["functies"]))
    d["categorie"] = "Molen" if any(f not in ANC_LABELS for f in d["functies"]) else "Molengerelateerd"
uris = sorted(recs)
print("unieke molens:", len(uris), file=sys.stderr)


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def values(ch):
    return "VALUES ?rm { " + " ".join(f"<{u}>" for u in ch) + " }"


def put(rm, key, val):
    lst = recs[rm].setdefault(key, [])
    if val not in lst:
        lst.append(val)


for ch in chunks(uris, 40):
    v = values(ch)
    for r in sparql(f"""SELECT ?rm ?choi ?wkt ?rd ?gem ?kom ?datum WHERE {{ {v}
      OPTIONAL {{ ?rm ceo:cultuurhistorischObjectnummer ?choi }}
      OPTIONAL {{ ?rm ceo:datumInschrijvingInMonumentenregister ?datum }}
      OPTIONAL {{ ?rm ceo:heeftGeometrie ?g . ?g geo:asWKT ?wkt . OPTIONAL {{ ?g ceo:asWKT-RD ?rd }} }}
      OPTIONAL {{ ?rm ceo:heeftBasisregistratieRelatie/ceo:heeftGemeente ?gem }}
      OPTIONAL {{ ?rm ceo:heeftBebouwdeKomType/skos:prefLabel ?kom }} }}"""):
        d = recs[r["rm"]]
        for k in ("choi", "wkt", "rd", "gem", "kom", "datum"):
            if k in r:
                d[k] = r[k]
    for r in sparql(f"""SELECT DISTINCT ?rm ?naam WHERE {{ {v} ?rm ceo:heeftNaam/ceo:naam ?naam }}"""):
        put(r["rm"], "namen", r["naam"])
    for r in sparql(f"""SELECT DISTINCT ?rm ?tekst ?soort WHERE {{ {v}
      ?rm ceo:heeftOmschrijving ?o . ?o ceo:omschrijving ?tekst .
      OPTIONAL {{ ?o ceo:heeftOmschrijvingstype/skos:prefLabel ?soort }} }}"""):
        put(r["rm"], "omschrijvingen", {"soort": r.get("soort", ""), "tekst": r["tekst"]})
    for r in sparql(f"""SELECT DISTINCT ?rm ?adres ?straat ?hnr ?pc ?plaats ?vbo ?pand WHERE {{ {v}
      ?rm ceo:heeftBasisregistratieRelatie/ceo:heeftBAGRelatie ?b .
      OPTIONAL {{ ?b ceo:volledigAdres ?adres }} OPTIONAL {{ ?b ceo:openbareRuimte ?straat }}
      OPTIONAL {{ ?b ceo:huisnummer ?hnr }} OPTIONAL {{ ?b ceo:postcode ?pc }}
      OPTIONAL {{ ?b ceo:woonplaatsnaam ?plaats }} OPTIONAL {{ ?b ceo:verblijfsobjectIdentificatie ?vbo }}
      OPTIONAL {{ ?b ceo:pandIdentificatie ?pand }} }}"""):
        put(r["rm"], "bag", {k: r[k] for k in r if k != "rm"})
    for r in sparql(f"""SELECT DISTINCT ?rm ?gebeurtenis ?van ?tot WHERE {{ {v}
      ?rm ceo:heeftGebeurtenis ?e . ?e ceo:heeftGebeurtenisNaam/skos:prefLabel ?gebeurtenis .
      OPTIONAL {{ ?e ceo:heeftDatering/ceo:heeftBeginDatering/ceo:datum ?van }}
      OPTIONAL {{ ?e ceo:heeftDatering/ceo:heeftEindDatering/ceo:datum ?tot }} }}""", "gebeurtenissen"):
        put(r["rm"], "gebeurtenissen", {k: r[k] for k in r if k != "rm"})
    for r in sparql(f"""SELECT DISTINCT ?rm ?hf WHERE {{ {v}
      ?rm ceo:heeftHuidigeFunctie/ceo:heeftFunctieNaam/skos:prefLabel ?hf . FILTER(lang(?hf)="nl") }}""", "huidige functie"):
        put(r["rm"], "huidige_functies", r["hf"])
    print("chunk klaar", file=sys.stderr)

# Beschermde stads- en dorpsgezichten (polygonen, lokaal koppelen met Shapely)
gez = sparql("""SELECT DISTINCT ?g ?nr ?naam ?type ?status ?wkt WHERE {
  ?g a ceo:Gezicht ; ceo:gezichtsnummer ?nr ; ceo:heeftGeometrie/geo:asWKT ?wkt .
  OPTIONAL { ?g ceo:heeftNaam/ceo:naam ?naam }
  OPTIONAL { ?g ceo:heeftType/ceo:heeftTypeNaam/skos:prefLabel ?type }
  OPTIONAL { ?g ceo:heeftGezichtsstatus/skos:prefLabel ?status } }""", "gezichten")
print("gezicht-rijen (alle NL):", len(gez), file=sys.stderr)

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps({"molens": list(recs.values()), "gezichten": gez}, ensure_ascii=False, indent=1), encoding="utf-8")
print("geschreven:", OUT, file=sys.stderr)
