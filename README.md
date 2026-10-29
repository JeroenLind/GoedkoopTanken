# fuelfinder

Zoekt het goedkoopste tankstation **inclusief de kosten van de omrit** (heen én terug naar huis),
over de grens heen. Dit is een lokale testversie voor op je laptop; de logica is los van de
interface gehouden, zodat er later een app, website of Home Assistant-koppeling op kan.

## Starten

Vereist Python 3.11+. Geen pakketten installeren nodig.

```
cp config.example.toml config.toml     # pas thuislocatie en kenteken aan
python -m fuelfinder check             # test alle bronnen (doe dit eerst!)
python -m fuelfinder vehicle AB-123-C  # wat weet de RDW over je auto?
python -m fuelfinder find -v           # het eigenlijke zoeken
python -m fuelfinder find --fuel diesel --consumption 5.5 --fill 50 --address "Straat 1, Plaats"
```

Voor Duitse prijzen heb je een gratis key nodig van https://creativecommons.tankerkoenig.de
(in `config.toml` of als omgevingsvariabele `TANKERKOENIG_API_KEY`).

## Webinterface

```
python -m fuelfinder web          # opent http://127.0.0.1:8080 in je browser
python -m fuelfinder web --port 9000 --no-browser
```

Op de hoofdpagina staan alleen **Huidige locatie**, **Liters tanken** en **Bereken**. De locatie wordt
bij het openen automatisch opgezocht via je apparaat (de browser vraagt eerst toestemming); lukt dat
niet, dan val je terug op je thuisadres of typ je zelf een adres. De rit heen en terug wordt
berekend vanaf die locatie. Alle andere instellingen (thuisadres, auto, zoekstraal, tijdlimiet,
bronnen, routering) staan achter de hamburgerknop linksboven. **Bereken** gebruikt wat er op dat moment
in het formulier staat (ook zonder opslaan). **Instellingen opslaan** schrijft
naar `config.toml`, dezelfde instellingen die de opdrachtregel gebruikt. Opmerkingen in een met de
hand geschreven `config.toml` blijven niet behouden zodra je via de webinterface opslaat.

Beveiliging: de server luistert alleen op `127.0.0.1` en is dus niet bereikbaar vanaf je netwerk. Hij
bewaart je Tankerkönig-key en heeft geen inlog; zet hem daarom niet open naar het netwerk zonder
eerst authenticatie toe te voegen. De API-key wordt nooit naar de browser teruggestuurd. Omdat
`config.toml` die key bevat staat het in `.gitignore`; commit dat bestand niet.

## Langs een route zoeken

Naast zoeken rondom een locatie kun je het goedkoopste station **onderweg** zoeken, bijvoorbeeld
van huis naar werk. In de webinterface kies je bovenaan *Langs een route*; het veld Huidige locatie
heet dan Vertrek en er komt een veld Bestemming bij (met de keuzelijst **Vaste adressen** en de knop **Omdraaien**, handig
voor de terugweg). Vaste adressen (Werk, school, familie, enz.) stel je in via het menu onder Vaste adressen; de naam Werk is de standaard. Een oud `[work]`-blok in config.toml wordt automatisch het adres Werk. Op de commandoregel:

    python -m fuelfinder find --to werk
    python -m fuelfinder find --to "Stationsstraat 1, Sittard" --address "Mijn straat 1, Roermond"
    python -m fuelfinder find --to 51.25,5.71 --corridor 8

Hoe het rekent:
- De omweg is het verschil met de directe route: (vertrek, station, bestemming) min (vertrek, bestemming),
  in kilometers en minuten. Alleen die omweg kost extra brandstof; de route zelf rij je toch.
- Tanken wordt gewaardeerd tegen de prijs van het station, net als bij zoeken rondom een locatie.
- De referentie voor de besparing is het station met de kleinste omweg (het station dat het best op je
  route ligt), niet het dichtstbijzijnde.
- De tijdlimiet (standaard 30 min) geldt voor de omweg zelf. Hij bepaalt ook hoe breed er naast de route
  gezocht wordt: ongeveer 0,4 km per toegestane minuut, tussen 3 en 15 km (zonder limiet 10 km).
  Met `--corridor` stel je dat zelf in.
- Optioneel stel je een maximale rijafstand in (`--max-km`, in de webinterface "Max. afstand"), voor als de tank
  bijna leeg is: stations die verder dan dat vanaf je vertrek liggen worden weggelaten, ook als referentie.
- Stations worden opgehaald met cirkels van 20 km langs de route. Die komen ook in de cache terecht,
  dus dezelfde dagelijkse route is de tweede keer meteen klaar.
- De navigatieknop opent Google Maps en Apple Maps met het station als tussenstop en je bestemming
  als eindpunt. Waze kent geen tussenstop en navigeert alleen naar het station.
- Bestemming kiezen op een kaart: naast het adresveld staat de knop **Kaart**. Klik of tik op de plek, controleer
  het adres onderaan en kies *Kies deze plek*. Je vertrekpunt staat als geel bolletje op de kaart. De kaart (Leaflet,
  meegeleverd in `static/vendor`) laadt de kaartbeelden rechtstreeks vanuit je browser van openstreetmap.org; daarvoor
  heb je internet nodig, en OpenStreetMap ziet dan welk gebied je bekijkt. Zonder kaart kun je altijd een adres typen.
- Het is een enkele rit (heen). Voor de terugweg gebruik je Omdraaien.
- Routes langer dan ongeveer 600 km worden geweigerd.

## Kaart bij de resultaten en data-download

- Onder de uitkomst staat een kaart met je vertrek, de route (bij Langs een route), de doorgerekende stations
  (genummerd zoals in de tabel) en de overige stations als grijze stipjes. Klik op een station of een regel in de
  tabel: de route erheen (bij Langs een route: van vertrek via het station naar de bestemming) wordt blauw getekend,
  met de afstand en tijd eronder. Onder de kaart staat de volledige berekening van dat station: tanken, omweg
  (kilometers × verbruik × prijs), totaal, besparing ten opzichte van de referentie, tijd en bron. Ook de grijze
  stipjes zijn aan te klikken. Uitzetten kan in het menu bij Zoeken.
- Onder elk station staat uit welke gegevensbron het komt (ANWB Onderweg of Tankerkönig) en of dat vers is opgehaald
  of uit de cache komt.
- **Download alle data (tijdelijk)** onderaan geeft een JSON-bestand met alle stations die bekeken zijn: bron, ruwe
  prijzen, ligging, het nummer `nr` dat het station op het scherm heeft (en `on_screen`: tabel of alleen grijs stipje),
  de uitkomst (kosten, omweg, besparing) en per station *waarom* het wel of niet in de uitkomst
  staat (geen prijs voor je brandstof, buiten de zoekbreedte, weggelaten door de tijdlimiet, niet doorgerekend,
  dubbel met een andere bron). Ook de gebruikte bronnen, instellingen en de route zitten erin. De knop is bedoeld
  voor het testen van de bronnen; de code staat apart (`service.export_data`, `/api/export`, en een blok in
  `index.html` met het woord TIJDELIJK) en is makkelijk te verwijderen.

## Cache

Prijzen en stationslocaties worden lokaal bewaard (map `cache/` naast `config.toml`, per bron
een JSON-bestand). Een zoekopdracht gebruikt opgeslagen gegevens als die jonger zijn dan
`max_age_hours` (standaard 12 uur) en het hele zoekgebied dekken. Je positie hoeft daarvoor niet
exact gelijk te zijn: bij een misser wordt een iets groter gebied rond een rasterpunt opgehaald,
en pas daarna gefilterd op jouw positie en straal.

- Aan/uit en maximale leeftijd: menu > Cache, of `[cache]` in `config.toml`.
- Web: staat er cache-data in het resultaat, dan verschijnt een knop **Prijzen vernieuwen**.
- CLI: `find --refresh` haalt alles vers op, `find --no-cache` slaat de cache over,
  `cache info` toont wat er bewaard is, `cache clear` wist alles.
- Is een bron onbereikbaar, dan worden oudere gegevens (tot 7 dagen) gebruikt, met een waarschuwing.
- De open/dicht-status uit de cache wordt na 30 minuten genegeerd, omdat die snel veroudert.
- Routes (OSRM) worden niet gecached; die zijn snel en afhankelijk van je exacte positie.
- Beperking: Tankerkönig staat maximaal 25 km straal toe. Bij een zoekstraal vanaf ca. 21 km
  levert de cache daarom alleen een treffer bij precies dezelfde coördinaten.

## Structuur

`service.search()` is de zoekopdracht zelf; de opdrachtregel (`cli.py`) en de webserver (`web.py`)
zijn dunne lagen eromheen. Een app of Home Assistant-koppeling kan dezelfde functie aanroepen.

## Tijdlimiet

Standaard worden stations weggelaten die meer dan 30 minuten extra rijtijd kosten (heen en
terug, vergeleken met het dichtstbijzijnde station). Aanpassen kan met `--max-extra-min 45`,
uitzetten met `--no-time-limit`, of vast in `config.toml` (`max_extra_min`, 0 = geen limiet).
Het dichtstbijzijnde station blijft altijd in de lijst.

## Rekenmodel

```
vulkosten = liters x prijs
omrit     = (km heen + km terug) x verbruik/100 x prijs
totaal    = vulkosten + omrit
besparing = totaal(dichtstbijzijnde station) - totaal(dit station)
```

Verbruik komt uit het kenteken (WLTP, anders NEDC) maal `real_world_factor` (standaard 1,2,
omdat het praktijkverbruik hoger ligt). Zelf opgegeven verbruik wordt niet gecorrigeerd.
Afstanden zijn rijafstanden via OSRM; als OSRM niet bereikbaar is schat het programma
1,3 x hemelsbreed en markeert dat met `~`.

## Wat is NIET getest tegen de echte dienst

De ontwikkelomgeving kon de externe diensten niet bereiken. Deze delen zijn gebouwd op
documentatie en de broncode van de bibliotheek pyfuelprices, maar nog niet live geprobeerd.
`python -m fuelfinder check` toont per bron of het werkt:

- **RDW**: de veldnamen voor verbruik (`brandstofverbruik_gecombineerd(_wltp)`). `check` meldt ontbrekende velden; `vehicle <kenteken> --raw` toont het ruwe antwoord.
- **ANWB Onderweg**: endpoint, responsvorm en brandstofcodes (`EURO95`, `DIESEL`, ...). Het endpoint is niet officieel gedocumenteerd en kan veranderen. `check` toont welke brandstoftypen er echt voorbijkomen.
- **Tankerkönig** en **OSRM**: standaard API's, wel nog niet live gedraaid.

## Nieuwe bron of grens toevoegen

Maak `fuelfinder/providers/<naam>.py` met een `Provider`-klasse (methode `fetch(lat, lon, radius_km)`
die `Station`-objecten teruggeeft), registreer hem in `PROVIDER_CLASSES` in `providers/__init__.py`. Naam, label, landen, toelichting en
testpunt staan als eigenschappen in de klasse; het menu (Bronnen en Landen) toont de bron dan vanzelf bij elk
land dat hij dekt. Een nieuw land komt in `countries.COUNTRIES` (grenzen maken met `scripts/maak_landgrenzen.py`).
De rekenkern verandert niet.

## Tests

`python -m unittest discover -s tests` (draait offline, met voorbeelddata).

## Home Assistant-add-on

De map `goedkoop-tanken/` is de add-on (Ingress in de zijbalk, instellingen in `/data`). Dezelfde code
draait nog steeds op je laptop met `python -m fuelfinder web`.

- Vervang `GITHUB_GEBRUIKER` in `repository.yaml`, `goedkoop-tanken/config.yaml` en `goedkoop-tanken/Dockerfile`.
- Lokaal testen op je Pi zonder GHCR: `scripts/lokale-addon.sh <map>`, kopieer de map naar `/addons/goedkoop-tanken`
  op Home Assistant en kies Verversen in de add-on-winkel.
- Release: zet `version` in `config.yaml` en `goedkoop-tanken/CHANGELOG.md`, maak tag `vX.Y.Z` en push die;
  `.github/workflows/release.yaml` test, bouwt aarch64 + amd64 en publiceert naar `ghcr.io`.
- Licentie: GPL v3 (`LICENSE`).
