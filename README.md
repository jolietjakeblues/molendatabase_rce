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

## Scripts (in volgorde)
1. `scripts/fetch_rce.py`: SPARQL op het RCE CHO-endpoint, schrijft `data/rce_raw.json`.
2. `scripts/build_biotoop.py`: AHN + BAG via PDOK, schrijft `data/biotoop.json` (cache in `data/cache`, ruim 300 MB, mag weg).
3. `scripts/fetch_images.py`: RCE-beeldbank (graph `image`), schrijft `data/rce_images.json`.
4. `scripts/build_erf.py`: percelen, gebouwen en erf, schrijft `data/erf.json` en `site/data/erf/*.json`.
5. `scripts/build_dataset.py`: tekstherkenning, gezichten, CSV's en `site/data/*`.

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
