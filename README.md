# Goedkoop tanken

Zoekt het goedkoopste tankstation **inclusief de kosten van de omrit en de extra rijtijd**, over de grens
heen (Nederland, Duitsland en België). Je gebruikt het als **Home Assistant-add-on** (in de zijbalk) of
op je laptop als gewone webapp. Versies die met `0.` beginnen zijn testversies.

Twee manieren van zoeken: **rondom mij** (waar tank ik het voordeligst vanaf hier?) en **langs een route**
(waar tank ik onderweg van A naar B?). In de app legt het menu **Help** alles uit: het bedoelde gebruik,
het resultaat, de berekening en alle instellingen.

## Installeren als Home Assistant-add-on

1. Ga in Home Assistant naar *Instellingen, Add-ons, Add-on-winkel, Repositories* en voeg
   `https://github.com/JeroenLind/GoedkoopTanken` toe.
2. Installeer **Goedkoop tanken** uit de winkel en start de add-on. Hij verschijnt in de zijbalk.
3. Vul in de app (menu linksboven) je thuisadres, kenteken en eventueel een Tankerkönig-sleutel in
   en kies *Instellingen opslaan*. De instellingen blijven bewaard in `/data`.

Het image wordt via GitHub gebouwd en gepubliceerd; je hoeft zelf niets te bouwen. Zie hieronder
voor testen zonder GitHub en voor het maken van een release.

## Starten op je laptop

Vereist Python 3.11+. Geen pakketten installeren nodig.

```
cp config.example.toml config.toml     # pas thuislocatie en kenteken aan
python -m goedkooptanken check             # test alle bronnen (doe dit eerst!)
python -m goedkooptanken vehicle AB-123-C  # wat weet de RDW over je auto?
python -m goedkooptanken find -v           # het eigenlijke zoeken
python -m goedkooptanken find --fuel diesel --consumption 5.5 --fill 50 --address "Straat 1, Plaats"
```

Voor Duitse prijzen heb je een gratis key nodig van https://creativecommons.tankerkoenig.de
(in `config.toml` of als omgevingsvariabele `TANKERKOENIG_API_KEY`).

## Webinterface

```
python -m goedkooptanken web          # opent http://127.0.0.1:8080 in je browser
python -m goedkooptanken web --port 9000 --no-browser
```

Op de hoofdpagina kies je **Rondom mij** of **Langs een route**, vul je de locatie (en bij een route de
bestemming) en het aantal liters in, en kies je **Bereken**. Met **Mijn locatie** gebruikt de app je apparaat
(de browser vraagt eerst toestemming); in het menu kun je dat ook automatisch bij het openen laten doen.
Lukt het niet, dan gebruik je **Thuis** of typ je zelf een adres. De rit heen en terug wordt
berekend vanaf die locatie. Alle andere instellingen (thuisadres, auto, zoekstraal, tijdlimiet,
waarde van je tijd, bronnen, routering) staan achter de hamburgerknop linksboven. **Bereken** gebruikt wat er op dat moment
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

    python -m goedkooptanken find --to werk
    python -m goedkooptanken find --to "Stationsstraat 1, Sittard" --address "Mijn straat 1, Roermond"
    python -m goedkooptanken find --to 51.25,5.71 --corridor 8

Hoe het rekent:
- De omweg is het verschil met de snelste route: (vertrek, station, bestemming) min (vertrek, bestemming),
  in kilometers en minuten. Alleen die omweg kost extra brandstof; de route zelf rij je toch.
- Tanken wordt gewaardeerd tegen de prijs van het station, net als bij zoeken rondom een locatie.
- De referentie voor de besparing is het goedkoopste station dat op je route ligt (standaard: omweg minder
  dan 0,5 km; instelbaar op afstand of tijd). Ligt er geen, dan het station met de kleinste omweg.
- De aanrader is het station met de laagste kosten inclusief tijd: extra rijtijd telt mee tegen de waarde
  van je tijd (standaard € 15 per uur, instelbaar; 0 = alleen op prijs).
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

## Aanrader en referentie

Het resultaat toont één **aanrader**: het station met de laagste kosten inclusief tijd (totaal plus extra
minuten × waarde van je tijd per uur / 60). De waarde van je tijd is standaard € 15 per uur en instelbaar
(0 = alleen op prijs kiezen). De lijst blijft op totaalprijs gesorteerd; de aanrader is groen gemarkeerd en
heeft een knop **Navigeer**. Is het goedkoopste station niet de aanrader, dan staat in het resultaat hoeveel
goedkoper het is en hoeveel extra minuten dat kost.

De besparing is vergeleken met de **referentie**: het goedkoopste station dat op de route ligt. In het menu
kies je of dat op afstand (standaard omweg minder dan 0,5 km) of op tijd (standaard minder dan 3 minuten)
wordt bepaald; beide grenzen zijn instelbaar. Ligt er geen station binnen de grens, dan is het station met
de kleinste omweg de referentie. Rondom een locatie gelden dezelfde regels, met het dichtstbijzijnde
station als uitgangspunt.

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
tijd      = extra minuten x waarde van je tijd / 60
besparing = totaal(referentie) - totaal(dit station)
```

De aanrader is het station met het laagste `totaal + tijd`. De referentie staat onder
*Aanrader en referentie*; rondom een locatie telt de extra rit ten opzichte van het dichtstbijzijnde station.

Verbruik komt uit het kenteken (WLTP, anders NEDC) maal `real_world_factor` (standaard 1,2,
omdat het praktijkverbruik hoger ligt). Zelf opgegeven verbruik wordt niet gecorrigeerd.
Afstanden zijn rijafstanden via OSRM; als OSRM niet bereikbaar is schat het programma
1,3 x hemelsbreed en markeert dat met `~`.

## Bronnen en betrouwbaarheid

`python -m goedkooptanken check` (en in de app de testknop bij Bronnen) toont per bron of het werkt.

- **ANWB Onderweg** (Nederland en België): geen officiële of gedocumenteerde dienst. Het endpoint, de
  responsvorm en de brandstofcodes (`EURO95`, `DIESEL`, ...) kunnen zonder waarschuwing veranderen. Valt de bron uit,
  dan gebruikt de app oudere prijzen uit de cache met een melding.
- **Tankerkönig** (Duitsland): officiële API met een eigen gratis sleutel.
- **OSRM** (afstand en rijtijd): standaard een openbare server; houd het gebruik beleefd. Zonder OSRM schat de app.
- **RDW** (kenteken): de veldnamen voor verbruik (`brandstofverbruik_gecombineerd(_wltp)`). `check` meldt
  ontbrekende velden; `vehicle <kenteken> --raw` toont het ruwe antwoord.

## Nieuwe bron of grens toevoegen

Maak `goedkooptanken/providers/<naam>.py` met een `Provider`-klasse (methode `fetch(lat, lon, radius_km)`
die `Station`-objecten teruggeeft), registreer hem in `PROVIDER_CLASSES` in `providers/__init__.py`. Naam, label, landen, toelichting en
testpunt staan als eigenschappen in de klasse; het menu (Bronnen en Landen) toont de bron dan vanzelf bij elk
land dat hij dekt. Een nieuw land komt in `countries.COUNTRIES` (grenzen maken met `scripts/maak_landgrenzen.py`).
De rekenkern verandert niet.

## Tests

`python -m unittest discover -s tests` (draait offline, met voorbeelddata).

## Home Assistant-add-on

De map `goedkoop-tanken/` is de add-on (Ingress in de zijbalk, instellingen in `/data`). Dezelfde code
draait nog steeds op je laptop met `python -m goedkooptanken web`.

- Lokaal testen op je Pi zonder GHCR: `scripts/lokale-addon.sh <map>`, kopieer de map naar `/addons/goedkoop-tanken`
  op Home Assistant en kies Verversen in de add-on-winkel.
- Release: zet `version` in `config.yaml` en `goedkoop-tanken/CHANGELOG.md`, maak tag `vX.Y.Z` en push die;
  `.github/workflows/release.yaml` test, bouwt aarch64 + amd64 en publiceert naar `ghcr.io`. Een gewone push maakt
  nooit een release. Tags `v0.*` worden als pre-release gemarkeerd. De stappen staan in `GITHUB-STAPPEN.md`.
- Licentie: GPL v3 (`LICENSE`).
