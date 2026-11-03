"""Haal RCE-beeldbankafbeeldingen op voor de rijksmonumentale molens (graph 'image' van het RCE CHO-endpoint).

Alleen RCE-afbeeldingen; per afbeelding blijven titel, licentie en de URL van de beeldbankpagina bewaard (provenance).
Uitvoer: data/rce_images.json  {rijksmonumentnummer: [ {id, titel, licentie, thumb, pagina, commons} ]}
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENDPOINT = "https://api.linkeddata.cultureelerfgoed.nl/datasets/rce/cho/services/cho/sparql"
PFX = """PREFIX ceo: <https://linkeddata.cultureelerfgoed.nl/def/ceo#>
PREFIX edm: <http://www.europeana.eu/schemas/edm/>
PREFIX dc: <http://purl.org/dc/elements/1.1/>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
"""
OPEN = ("creativecommons.org/licenses/by/", "creativecommons.org/publicdomain/", "creativecommons.org/licenses/by-sa/")


def sparql(q, tries=4):
    data = urllib.parse.urlencode({"query": PFX + q}).encode()
    for t in range(tries):
        try:
            req = urllib.request.Request(ENDPOINT, data=data, headers={"Accept": "application/sparql-results+json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                res = json.load(r)
            return [{k: v["value"] for k, v in b.items()} for b in res["results"]["bindings"]]
        except Exception as e:  # noqa: BLE001
            print("  poging", t + 1, e, file=sys.stderr)
            time.sleep(5 * (t + 1))
    raise SystemExit("query mislukt")


molens = json.loads((ROOT / "data" / "rce_raw.json").read_text(encoding="utf-8"))["molens"]
nrs = [m["rijksmonumentnummer"] for m in molens]
out = {}
for i in range(0, len(nrs), 40):
    ch = nrs[i:i + 40]
    rows = sparql("SELECT DISTINCT ?nr ?s ?titel ?rechten ?dep ?at WHERE { GRAPH <https://linkeddata.cultureelerfgoed.nl/graph/image> { VALUES ?nr { "
                  + " ".join(f'"{n}"' for n in ch) + " } ?s ceo:rijksmonumentnummer ?nr . OPTIONAL { ?s dc:title ?titel } OPTIONAL { ?s dc:rights ?rechten } "
                  "OPTIONAL { ?s foaf:depiction ?dep } OPTIONAL { ?s edm:isShownAt ?at } } }")
    per = {}
    for r in rows:
        d = per.setdefault((r["nr"], r["s"]), {"id": r["s"].rsplit("/", 1)[-1], "titel": r.get("titel", ""), "licentie": r.get("rechten", ""),
                                               "thumb": r.get("dep", ""), "pagina": "", "commons": ""})
        at = r.get("at", "")
        if "beeldbank.cultureelerfgoed.nl" in at:
            d["pagina"] = at
        elif "commons.wikimedia.org" in at:
            d["commons"] = at
    for (nr, _), d in per.items():
        d["titel"] = re.sub(r"\.(jpe?g|png|tif+)$", "", d["titel"].replace("_", " ")).strip()
        d["open_licentie"] = any(o in d["licentie"] for o in OPEN)
        out.setdefault(nr, []).append(d)
    print("batch", i // 40 + 1, "klaar", file=sys.stderr)

for v in out.values():
    v.sort(key=lambda d: d["titel"])
(ROOT / "data" / "rce_images.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
tot = sum(len(v) for v in out.values())
print(f"molens met afbeelding: {len(out)}/{len(nrs)} | afbeeldingen: {tot} | met open licentie: {sum(d['open_licentie'] for v in out.values() for d in v)}", file=sys.stderr)
