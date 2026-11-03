# Molens (eerste opzet)

Eerste dataset: 237 rijksmonumentale molens en 6 molengerelateerde monumenten in Zuid-Holland uit de RCE-data, in de veldopzet van `Eerste_opzet_molendatabase_westelijk_Nederland.xlsx`.

## Uitvoer
- `site/molens.csv`: puntkomma-gescheiden, UTF-8 met BOM (opent direct in Excel). Kolommen A t/m BU volgen het tabblad *Molendatabase*; daarachter extra kolommen (gezicht, biotoopdetails, herkomst, coördinaten, links).
- `site/stads_en_dorpsgezichten.csv`: tabblad *stads_en_dorpsgezichten*, per beschermd gezicht in Zuid-Holland met de molens erbinnen.
- `site/`: de statische site (kaart, filters, lijst, windroos per molen). De CSV's worden door `scripts/build_dataset.py` direct in `site/` gezet.
- **Selectie downloaden:** in de site toont de knop "Download selectie" de rijen die de filters tonen, of alleen de aangevinkte rijen in de lijst. Dat geldt voor rijen; alle kolommen zitten altijd in de download. Het bestand wordt in de browser gemaakt (`molens-selectie-<datum>.csv`, zelfde opmaak als de volledige CSV).

## Cloudflare (wrangler)
Projectnaam `molens` (zie `wrangler.jsonc`, statische assets uit `site/`).
```
npm install
npm run dev          # lokaal via wrangler
npm run deploy:dry   # controle zonder te publiceren
npm run deploy       # publiceert naar Cloudflare (eerst inloggen met: npx wrangler login)
```
De data bijwerken: `npm run data` (draait `scripts/build_dataset.py`).

## Hoe de selectie werkt
Rijksmonumenten (juridische status *rijksmonument*) in provincie Zuid-Holland (OWMS) met een **oorspronkelijke functie** onder het concept *Industrie- en poldermolen* of *Molen* in de RCE-thesaurus (`skos:broader*`). Geen tekstmatching op namen.

Kolom *Categorie*:
- **Molen** (237): minstens één functie die een molen zelf is.
- **Molengerelateerd** (6): alleen functies als *Molenaarswoning(M)*, *Roedenloods* (onder de molen-tak) of *Molenaarswoning(K)*, *Zaagmolen*, *Meelfabriek* (erbuiten). Op de kaart paars. Molenspecifieke velden en biotoop zijn bij deze rijen leeg. Zaagmolen komt in Zuid-Holland niet voor als rijksmonument. Meer functies toevoegen kan in `ANC_IN` en `EXTRA` in `scripts/fetch_rce.py`.

## Erf en kadastrale percelen
`scripts/build_erf.py` bepaalt per molen het kadastrale perceel (BRK kadastrale kaart, PDOK) en classificeert BAG-gebouwen binnen 100 m als **tegenaan** (binnen 1 m), **zelfde perceel**, **aangrenzend perceel** of **ander perceel** (een gebouw hoort bij een perceel als minstens de helft van de voetafdruk erop ligt). Gebruiksdoel komt uit de BAG-verblijfsobjecten; een pand zonder verblijfsobject is een bijgebouw. Nabije panden die zelf rijksmonument zijn worden herkend via de RCE-koppeling en geometrisch. Gerelateerde monumenten (molenaarswoning e.d.) worden aan de molen gekoppeld. Per molen staat een klein GeoJSON-bestand in `site/data/erf/` dat de site bij selectie op de kaart toont.

CSV-kolommen: *Kadastraal perceel molen*, *Perceelgrootte*, de vier tellingen, *Woning op erf*, *Bijgebouwen op erf*, *Dichtstbijzijnde gebouw*, *Gerelateerde rijksmonumenten bij de molen*. De kolom *Erf: Molenaarshuisje* uit de opzet is alleen "Ja" bij bewijs: genoemd in de RCE-omschrijving of een RCE-molenaarswoning op hetzelfde of aangrenzende perceel. De BAG-afgeleide kolommen zijn indicaties.

Beperking: RCE en BAG wijzen soms naar verschillende panden (bijvoorbeeld wanneer molen en molenaarswoning één adres delen); een kleine woning zonder verblijfsobject telt dan als bijgebouw.

## Windgewogen biotoop
`scripts/fetch_knmi.py` haalt KNMI-uurgegevens (windrichting en uurgemiddelde snelheid, open data) op voor acht stations in en rond Zuid-Holland en bewaart per station en periode (1991-2020 en 2014-2023) de windroos: frequentie en energieaandeel (som van v³) per richting. `scripts/build_wind.py` kiest per molen de drie dichtstbijzijnde stations (alleen stations met minstens 80% geldige uren in de periode, dus Voorschoten valt af voor 1991-2020), weegt ze op 1/afstand² en berekent de windgewogen index: som over de richtingen van gewicht × hinderscore, met dezelfde klassegrenzen als het gemiddelde. Standaard weegt het energieaandeel; de frequentieweging en het ongewogen gemiddelde staan er ook. In Zuid-Holland is zuidwest overal de overheersende richting (ongeveer 35-40% van de windenergie).

Beperkingen: stations staan 20-30 km van de molen en meten op 10 m; de periode (`PERIODE` in `build_wind.py`) en het aantal stations zijn instelbaar. De windweging verandert de klasse van 19 molens.

## Formele molenbiotoopzone
`scripts/fetch_plannen.py` bevraagt de PDOK Ruimtelijke Plannen WMS (GetFeatureInfo) per molen op de lagen gebiedsaanduiding, dubbelbestemming, functieaanduiding, bouwaanduiding en enkelbestemming. `scripts/build_zones.py` houdt vigerende aanduidingen over (niet historisch, geen ontwerp) en scheidt **biotoopzones** (naam met "biotoop") van **molenaanduidingen** ("molen", "overig - molen", ...). Per molen: zone ja, nee of onbekend, straal (uit de naam, anders geschat uit het polygoon en alleen als die ≤ 450 m is), plan, status, datum, plantekst-URL, dekking van de cirkels van 100 en 400 m, gebouwen in de zone (BAG) en hoge objecten (≥ 3 m, AHN). De vergelijking met de berekende biotoop is een indicatie; de regels uit de plantekst (zoals maximale bouwhoogte) zijn niet gelezen.

Uitkomst: 212 molens hebben een biotoopzone, 21 niet (wel een bestemmingsplan) en 4 zijn onbekend (geen bestemmingsplan in de bron). Bij 15 molens is de zone niet op het molenpunt gevonden maar op 60 of 150 m (staat in *Zone: gevonden op*).

### Regelteksten (API Ruimtelijke Plannen)
`scripts/fetch_plantekst.py` haalt met de API Ruimtelijke Plannen (v4, Ruimtelijkeplannen.nl) per zone het artikel met de regels op: de WMS-`identificatie` is het ID van het gebiedsaanduiding-object, dat linkt naar het artikel; onderliggende artikelen worden meegelezen. Uit de tekst worden afstanden, de hoogtehelling en de referentie (onderste punt van de wiek) herkend. Voor 226 zones is een artikel gevonden; bij 191 van de 212 molens met zone is de norm herkend. De regels verschillen per gemeente: binnen 100 m geen bebouwing hoger dan de onderste wiekpunt, en tussen 100 en 400 m een toegestane hoogte van 1/30, 1/50 of 1/100 van de afstand (tot de molen), vaak ook voor beplanting. De site toont de volledige tekst per zone onder *Regels uit het plan*; de CSV heeft *Zone: norm uit plantekst (herkend)* en een uittreksel. Herkenning is tekstmatig en kan een afwijkende formulering missen; de plantekst zelf blijft leidend.

De sleutel staat in `.env` (zie `.env.example`; `.env` staat in `.gitignore`) of in de omgevingsvariabele `RUIMTELIJKE_PLANNEN_API_KEY`. Het script schrijft de sleutel nooit weg.

### Normtoets (hoogte volgens het bestemmingsplan)
`scripts/build_norm.py` toetst per molen met een zone en een volledig herkende norm (166 molens) of gebouwen en bomen in de zone aan de norm voldoen: binnen de straal (meestal 100 m) niet hoger dan de onderste wiekpunt, daarbuiten tot 400 m maximaal `h_wiek + afstand × helling` (1/30, 1/50 of 1/100; helling en afstanden uit de plantekst). De hoogtes komen uit de AHN (DSM min DTM, 2 m raster); gebouwen zijn BAG-voetafdrukken, een gebouw telt als overschrijdend bij minstens 2 pixels en 25% van de oppervlakte boven de grens. Bomen (alleen als het plan beplanting noemt) worden als oppervlak in m² gerapporteerd en zijn indicatief.

**De onderste wiekpunt is een aanname**, want die staat niet in de data: grondzeiler, poldermolen en wipmolen 2,5 m (± 1,5 m), beltmolen 5,5 m (± 1,5 m), stellingmolen 8 m (± 2,5 m). Er wordt getoetst met de strenge, midden- en ruime aanname. Uitkomst: *Voldoet* (ook bij de strenge aanname), *Overschrijding* (ook bij de ruime aanname) of *Afhankelijk van wiekhoogte*. Uitkomst voor Zuid-Holland: 20 voldoen, 79 overschrijden, 67 hangen af van de aanname, 46 zijn niet getoetst (norm niet automatisch herkend of alleen een straal zonder helling die ik niet kon uitlezen).

Lees de uitkomst voorzichtig: de norm geldt voor het **oprichten** van bouwwerken, en bestaande bebouwing mag er vaak overheen. Daarom staat apart hoeveel overschrijdende gebouwen na de plandatum zijn gebouwd (BAG-bouwjaar): bij 26 molens is er minstens één, bij 4 zijn het alle overschrijders. Verder zijn alleen de zones uit de WMS gebruikt; afwijkende regels voor een deel van de zone (bijvoorbeeld een lagere maximale bouwhoogte uit een andere bestemming) zijn niet meegenomen. Kolommen: *Normtoets …* in de CSV; op de kaart staan overschrijdende gebouwen rood omlijnd.

**Wat ontbreekt:** omgevingsplannen onder de Omgevingswet (vanaf 2024). Die staan niet in de PDOK-plannenlaag en ook niet in de API Ruimtelijke Plannen; ze zijn alleen via de DSO-API ("Omgevingsdocumenten presenteren") op te vragen, met een eigen sleutel. De sleutel voor Ruimtelijke Plannen werkt daar niet voor. `DSO_API_KEY` is nog niet ingesteld; de MCP-tool voor DSO geeft bovendien alleen documentmetadata. Zodra er een DSO-sleutel is, kan die bron dezelfde velden vullen voor de molens met status *Onbekend*.

## Scripts (in volgorde)
1. `scripts/fetch_rce.py`: SPARQL op het RCE CHO-endpoint, schrijft `data/rce_raw.json`.
2. `scripts/build_biotoop.py`: AHN + BAG via PDOK, schrijft `data/biotoop.json` (cache in `data/cache`, ruim 300 MB, mag weg).
3. `scripts/fetch_images.py`: RCE-beeldbank (graph `image`), schrijft `data/rce_images.json`.
4. `scripts/build_erf.py`: percelen, gebouwen en erf, schrijft `data/erf.json` en `site/data/erf/*.json`.
5. `scripts/fetch_knmi.py`, `scripts/build_wind.py`: KNMI-windrozen en windgewogen biotoop (`data/knmi_windroos.json`, `data/wind.json`).
6. `scripts/fetch_plannen.py`, `scripts/fetch_plantekst.py` (sleutel nodig), `scripts/build_zones.py`, `scripts/build_norm.py`: formele zones, hun regels en de normtoets (`data/plannen.json`, `data/plantekst.json`, `data/zones.json`, `site/data/zone/*.json`, `site/data/plantekst.json`, `data/norm.json`, `site/data/norm/*.json`).
7. `scripts/build_dataset.py`: tekstherkenning, gezichten, CSV's en `site/data/*`.

## Wat is gevuld en waar komt het vandaan
| Veld | Bron | Gevuld |
|---|---|---|
| Monumentnummer, gemeente, provincie | RCE | 239 |
| Adres | BAG via RCE; 23 molens zonder BAG-koppeling via dichtstbijzijnd PDOK-adres (staat in *Herkomst adres*) | 239 |
| Jaar bouw | RCE datering, omschrijving of BAG-bouwjaar (staat in *Herkomst jaar bouw*) | 238 |
| Naam | RCE naam of tussen aanhalingstekens in de omschrijving | 176 |
| Type, plaatsing, functie, bouwkenmerken, romptype | tekstherkenning op de RCE-omschrijving | 63 tot 203 |
| Jaar herbouw, brand, restauratie, eigenaar, bestemming | tekstherkenning, komt zelden in de tekst voor | 5 tot 18 |
| Binnen stads- of dorpsgezicht | RCE-polygonen (status *beschermd*), ruimtelijke koppeling met Shapely | 239 (47 binnen) |
| Molenbiotoop N t/m NW | berekend uit AHN en BAG, zie hieronder | 239 |
| POM, SIM, wieken, assen, kruiwerk, vang, wielen | niet in RCE, BAG of AHN; later aan te vullen (Hollandsche Molen, SIM-dossiers, eigenaren) | 0 |

## Afbeeldingen
Alleen RCE-beeldbank-afbeeldingen, rechtstreeks uit de RCE linked data: 679 foto's bij 95 van de 239 molens, allemaal CC BY 4.0. De site toont miniaturen met titel, "Foto: RCE", licentielink en link naar de beeldbankpagina. De CSV bevat de eerste afbeelding per molen (miniatuur, beeldbankpagina, licentie).

## Nederlandse Molendatabase (molendatabase.nl)
Alleen links, geen overgenomen gegevens. De CSV-kolom *Zoeklink Nederlandse Molendatabase* en de link in de site verwijzen naar hun zoekresultaat (op naam, of op plaats als de molen geen naam heeft); de koppeling is dus niet altijd exact. Reden: hun gebruiksvoorwaarden staan overname van gegevens van meer dan één molen in samenhang niet toe, teksten zijn niet bewerkbaar en foto's mogen niet worden overgenomen zonder toestemming van de fotograaf (https://www.molendatabase.nl/overig/doel-auteursrecht-gebruiksvoorwaarden-privacy-en-oorsprong). Links zijn wel uitdrukkelijk welkom. Er is toestemming gevraagd aan de redactie; zonder die toestemming blijven eigenaar, wieken, assen, kruiwerk, vang en wielen leeg.

## Molenbiotoop
Zie de uitleg onderaan de site en de docstring van `scripts/build_biotoop.py`. Samengevat: genormaliseerd hoogtemodel (AHN DSM min DTM, 2 m) in 400 m straal, BAG-voetafdrukken scheiden gebouwen van bomen, hinder per obstakel = 1 − d/(20H) wanneer de askop lager ligt dan 2H, bomen voor 60%, sectorscore = gemiddelde van de zwaarste hinder over 9 stralen (Goed < 0,15, Matig < 0,45, anders Slecht).

Dit is een indicatie, geen molenbiotoopadvies. Bekende beperkingen:
- AHN mist hoge, dunne molenkoppen (De Walvisch: 24 m gemeten, 33 m werkelijk); de askophoogte heeft daarom een ondergrens per type.
- Drempels en de vuistregel zijn een keuze en niet getoetst aan het oordeel van molenaars of de Hollandsche Molen. Valideer op een paar bekende molens voordat je ze gebruikt.
- AHN is een momentopname; zomer of winter (blad aan de bomen) maakt niet uit, maar nieuwbouw na de opname ontbreekt.
- Een molen op een belt of stelling krijgt geen aparte hoogtecorrectie voor de maaiveldhoogte.

## Aandachtspunten
- Mill-selectie levert 239 monumenten; de verkenner van de LAYRS-demo noemt er 242. Het verschil is niet onderzocht.
- Teksten zijn korte registeromschrijvingen, dus tekstherkenning is bewust conservatief: leeg betekent *onbekend*, niet *nee*.
- De MCP-documentatie (`legal_status`) noemt de status-URI zonder `/2/`; de live data gebruikt `…/term/id/rn/2/…`.
