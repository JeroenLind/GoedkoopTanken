# Goedkoop tanken: requirements

Dit document bevat alleen eisen die Jeroen zelf heeft genoemd, of die hij op voorstel expliciet heeft
bevestigd. Eisen die ik zelf belangrijk vond, zijn eerst aan hem voorgelegd; alleen wat hij aanvinkte
staat erin (herkomst "Bevestigd"). Open vragen staan apart in hoofdstuk 7.

**Herkomst:** *Jeroen* = door Jeroen gevraagd of besloten. *Bevestigd* = door mij voorgesteld, door Jeroen goedgekeurd.
**Status:** *Klaar* = gebouwd en getest, *Gepland* = nog te bouwen, *Open* = nog niet besloten.

## 1. Doel en scope

Een app die het **goedkoopste tankstation** vindt, **inclusief de kosten van de omrit** (brandstof en tijd), over
de grens heen (Roermond, Nederland en Duitsland). De app draait lokaal op een laptop (voor testen) en als
**Home Assistant-add-on** die in de zijbalk van Home Assistant te openen is, ook in de Home Assistant-app op de telefoon.

Versie 1 beperkt de koppeling met Home Assistant tot de web-interface in de zijbalk en het lezen van de locatie van een telefoon-tracker.

## 2. Gebruikers en omgeving

| Nr. | Omschrijving | Herkomst |
| --- | --- | --- |
| U-1 | Hoofdgebruikers: Mensen met een auto die zo goedkoop willen tanken, maar wel binnen zekere grenzen | Jeroen |
| U-2 | Home Assistant draait op een Raspberry Pi; de add-on moet ook werken op andere hardware. | Jeroen |
| U-3 | Doelgroep: Nederlandse Home Assistant-gebruikers; interface en documentatie in het Nederlands. | Jeroen |
| U-4 | Telefoon (Android) is naar verwachting de meest gebruikte plek om de app te openen. | Jeroen |
| U-5 | Ontwikkelen en testen gebeurt op een Windows-laptop. | Jeroen |

## 3. Functionele eisen

### 3.1 Zoeken en berekenen

| Nr. | Eis | Herkomst | Status |
| --- | --- | --- | --- |
| FR-1 | De app vindt het goedkoopste station inclusief de brandstofkosten van de omrit en de extra rijtijd, niet alleen de laagste literprijs. | Jeroen | Klaar |
| FR-2 | Prijzen komen uit twee bronnen: ANWB Onderweg (Nederland) en Tankerkönig (Duitsland, met eigen API-sleutel van de gebruiker). | Jeroen | Klaar |
| FR-3 | Brandstof en verbruik kunnen uit het kenteken komen (RDW); de gebruiker kan brandstof en verbruik ook zelf opgeven. | Jeroen | Klaar |
| FR-4 | De gebruiker wil maar beperkt omrijden: er is een instelbare tijdlimiet voor extra rijtijd (0 = geen limiet). | Jeroen | Klaar |
| FR-5 | Afstanden en rijtijden komen uit een routeserver (OSRM); adressen worden opgezocht via Nominatim. Is routering niet beschikbaar, dan schat de app, en toont dat. | Jeroen | Klaar |
| FR-6 | Het resultaat toont de beste stations met prijs, tankkosten, omrit, totaal en besparing ten opzichte van een referentiestation (het dichtstbijzijnde, of bij een route het station met de kleinste omweg). | Jeroen | Klaar |
| FR-7 | Prijzen worden lokaal gecachet. Valt een bron uit, dan gebruikt de app oudere gegevens met een duidelijke melding. | Jeroen | Klaar |

### 3.2 Zoeken langs een route

| Nr. | Eis | Herkomst | Status |
| --- | --- | --- | --- |
| FR-8 | Naast zoeken rond een punt is er een tweede modus: het goedkoopste station langs een route van A naar B (bijvoorbeeld van huis naar werk), met dezelfde logica dat de gebruiker er maar beperkt voor wil omrijden. | Jeroen | Klaar |
| FR-9 | Bij een route is de omweg het aantal extra kilometers en minuten ten opzichte van de directe route; de tijdlimiet geldt voor die omweg. | Jeroen | Klaar |
| FR-10 | De bestemming kan als adres worden getypt of op een kaart worden gekozen. | Jeroen | Klaar |
| FR-11 | Vertrek en bestemming kunnen worden omgedraaid (voor de terugweg). | Jeroen | Klaar |
| FR-12 | Bij een route kan de gebruiker een maximaal te rijden afstand invullen, voor het geval de tank bijna leeg is. | Jeroen | Gepland |

### 3.3 Vaste adressen

| Nr. | Eis | Herkomst | Status |
| --- | --- | --- | --- |
| FR-13 | In het configuratiescherm kan de gebruiker meerdere vaste adressen instellen: thuis, werk en vrij te kiezen adressen met een eigen naam. | Jeroen | Klaar |
| FR-14 | Een vast adres kan worden ingesteld door het adres te typen of door de plek op een kaart te kiezen. | Jeroen | Klaar |
| FR-15 | Bij een route kiest de gebruiker de bestemming uit de lijst met vaste adressen. | Jeroen | Klaar |
| FR-16 | Het los ingestelde thuisadres staat ook in die keuzelijst. | Jeroen | Klaar |

### 3.4 Resultaten, kaart en inzicht

| Nr. | Eis | Herkomst | Status |
| --- | --- | --- | --- |
| FR-17 | Na een berekening toont een kaart de route, de stations en de omweg. | Jeroen | Klaar |
| FR-18 | Per station is zichtbaar uit welke gegevensbron de gegevens komen (ANWB Onderweg of Tankerkönig) en hoe oud ze zijn. | Jeroen | Klaar |
| FR-19 | Bij een klik op een station (in de lijst, op de kaart of op een stip) toont de app de volledige berekening van dat station. | Jeroen | Klaar |
| FR-20 | Er is een tijdelijke downloadknop met alle bekeken stations en gegevens (JSON), met de bron en status per station. | Jeroen | Klaar |
| FR-21 | In die download staat ook het nummer of de positie uit de berekening, zodat het te relateren is aan wat op het scherm staat. | Jeroen | Klaar |

### 3.5 Bronnen en instellingen

| Nr. | Eis | Herkomst | Status |
| --- | --- | --- | --- |
| FR-22 | Per bron is er een testknop die de verbinding en de API-sleutel controleert, naar aanleiding van een time-out bij Tankerkönig. | Jeroen | Klaar |
| FR-23 | Instellingen worden in de app zelf gedaan en bewaard (niet in de Home Assistant-configuratiepagina); alleen technische opties staan in Home Assistant. | Jeroen | Klaar |
| FR-24 | De ANWB-bron staat standaard aan, met een duidelijke disclaimer dat het geen officiële bron is, en kan worden uitgezet. | Jeroen | Klaar |
| FR-25 | De standaard zoekstraal is 20 km. | Jeroen | Klaar |

### 3.6 Locatie en Home Assistant

| Nr. | Eis | Herkomst | Status |
| --- | --- | --- | --- |
| FR-26 | De huidige locatie komt uit een telefoon-tracker in Home Assistant (de gebruiker kiest de tracker in de instellingen); lukt dat niet, dan gebruikt de app de locatie van de browser. | Jeroen | Klaar |
| FR-27 | De app is bereikbaar via de zijbalk van Home Assistant (Ingress), ook in de Home Assistant-app op de telefoon. | Jeroen | Klaar |
| FR-28 | In versie 1 is de koppeling met Home Assistant beperkt tot de web-interface in de zijbalk. Sensoren, meldingen en services zijn bewust uitgesteld. | Jeroen | Besluit |

## 4. Niet-functionele eisen

### 4.1 Platform, distributie en licentie

| Nr. | Eis | Herkomst | Status |
| --- | --- | --- | --- |
| NFR-1 | De app blijft lokaal te draaien op een laptop met `python -m fuelfinder web`, zonder Docker en zonder Home Assistant. | Jeroen | Klaar |
| NFR-2 | De add-on heet "Goedkoop tanken" en draait op aarch64 en amd64. | Jeroen | Klaar |
| NFR-3 | Eén publieke GitHub-repository bevat de code, de add-on en de bouwconfiguratie. | Jeroen | Klaar |
| NFR-4 | De add-on wordt via GitHub gebouwd en verspreid als kant-en-klare images op GitHub Container Registry; gebruikers bouwen niet zelf. | Jeroen | Klaar |
| NFR-5 | Een release ontstaat alleen via een versie-tag (bijvoorbeeld v0.1.0), die test, bouwt en publiceert. Een gewone push maakt nooit een release. | Jeroen | Klaar |
| NFR-6 | De licentie is GPL v3. | Jeroen | Klaar |

### 4.2 Gebruik en kwaliteit

| Nr. | Eis | Herkomst | Status |
| --- | --- | --- | --- |
| NFR-7 | **Telefoon eerst:** het scherm is op een telefoon goed bruikbaar, zonder zijwaarts scrollen; resultaten verschijnen als kaartjes. | Jeroen, Bevestigd | Klaar |
| NFR-8 | **Toegankelijkheid:** bediening met het toetsenbord, voldoende kleurcontrast en labels voor schermlezers. | Bevestigd | Gedeeltelijk, nog niet getoetst |
| NFR-9 | **Duidelijke foutmeldingen:** bij uitval van een bron staat er welke bron en waarom, en valt de app terug op oudere prijzen. | Bevestigd | Klaar |
| NFR-10 | **Reactietijd:** een berekening met warme cache is binnen een vaste tijd klaar op een Raspberry Pi. De grens is nog niet vastgesteld (voorstel: 10 seconden). | Bevestigd | Open |
| NFR-11 | **Instellingen blijven bewaard:** instellingen, vaste adressen en cache blijven behouden bij een herstart of update van de add-on. | Bevestigd | Klaar |

### 4.3 Beveiliging en privacy

| Nr. | Eis | Herkomst | Status |
| --- | --- | --- | --- |
| NFR-12 | De Tankerkönig-API-sleutel wordt nooit teruggegeven aan de browser, niet gelogd en staat niet in de repository. | Bevestigd | Klaar |
| NFR-13 | De locatie van de gebruiker gaat alleen naar de gekozen diensten (ANWB, Tankerkönig, routeserver, adreszoeker, kaarttegels van OpenStreetMap); dit staat in de documentatie. | Bevestigd | Klaar |
| NFR-14 | De koppeling met Home Assistant is alleen-lezen: de add-on leest alleen de lijst met trackers en de locatie van de gekozen tracker. | Bevestigd | Klaar |

### 4.4 Eerlijk gebruik van gedeelde diensten

| Nr. | Eis | Herkomst | Status |
| --- | --- | --- | --- |
| NFR-15 | De routeserver (OSRM) en de adreszoeker (Nominatim) blijven in gebruik, op een beleefde manier: herkenbare User-Agent, maximaal 1 aanvraag per seconde naar Nominatim, adressen cachen, server-adressen instelbaar. | Jeroen, Bevestigd | Klaar |

### 4.5 Onderhoud en kwaliteitsborging

| Nr. | Eis | Herkomst | Status |
| --- | --- | --- | --- |
| NFR-16 | **Tests en CI:** elke wijziging draait de tests; een release kan alleen met groene tests. | Bevestigd | Klaar |
| NFR-17 | **Documentatie:** README, uitleg in de add-on en een changelog per release, in het Nederlands. | Bevestigd | Gedeeltelijk |

## 5. Besluiten en randvoorwaarden

| Onderwerp | Besluit | Herkomst |
| --- | --- | --- |
| Repository | github.com/JeroenLind/GoedkoopTanken, publiek | Jeroen |
| Add-on-naam | Goedkoop tanken (slug `goedkoop-tanken`) | Jeroen |
| Toegang | Ingress, zijbalk in Home Assistant | Jeroen |
| Images | Prebuilt op GHCR, aarch64 en amd64 | Jeroen |
| Releases | Alleen via versie-tags; de eerste push levert geen release op | Jeroen |
| Laptop | `python -m fuelfinder web` blijft werken | Jeroen |
| Taal | Nederlands | Jeroen |
| Licentie | GPL v3 | Jeroen |

## 6. Bewust uitgesteld (buiten versie 1)

- Sensoren, meldingen en services in Home Assistant.
- Een maximaal te rijden afstand bij een route staat wel gepland (FR-12).

## 7. Open punten

| Nr. | Punt | Eigenaar |
| --- | --- | --- |
| O-1 | Maximale reactietijd (NFR-10): welke grens is acceptabel? | Jeroen |
| O-2 | Pictogram en logo van de add-on. | Jeroen |
| O-3 | Contactadres voor de User-Agent naar OpenStreetMap-diensten (optionele add-on-optie `contact`). | Jeroen |
| O-4 | Minimale Home Assistant-versie. | Te bepalen bij testen |
| O-5 | Toegankelijkheid (NFR-8) nog niet getoetst met toetsenbord en schermlezer. | Te plannen |

## 8. Herleidbaarheid

Welke ontwerpkeuzes, modules en tests een eis invullen, staat in [DESIGN.md](DESIGN.md), hoofdstuk 9. Elke eis heeft een herkomst in hoofdstuk 3 en 4. Eisen met herkomst "Bevestigd" zijn door mij voorgesteld en
op 27 oktober 2026 door Jeroen goedgekeurd. Wijzigt een eis, pas dan eerst dit document aan.
