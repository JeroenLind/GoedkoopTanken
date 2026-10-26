# Goedkoop tanken

Vindt het goedkoopste tankstation **inclusief de kosten van de omrit**, in Nederland en Duitsland.

## Eerste keer instellen

1. Open **Goedkoop tanken** in de zijbalk.
2. Open het menu (linksboven) en vul in: je brandstof, kenteken of verbruik, en je thuisadres.
3. Voor Duitse prijzen: vraag gratis een sleutel aan op <https://creativecommons.tankerkoenig.de> en plak die bij **Tankerkönig API-key**.
4. Kies bij **Telefoon-tracker in Home Assistant** je telefoon. *Mijn locatie* gebruikt dan de laatst bekende locatie uit Home Assistant.

Alle instellingen worden in de app bewaard en blijven na een update of herstart bestaan.

## Opties van de add-on

| Optie | Betekenis |
| --- | --- |
| `contact` | Optioneel e-mailadres voor de User-Agent naar OpenStreetMap-diensten. |

## Privacy en bronnen

- Je locatie en zoekopdrachten gaan naar: ANWB Onderweg, Tankerkönig, een OSRM-routeserver, Nominatim (adressen) en OpenStreetMap-kaarttegels (je browser).
- **ANWB Onderweg** is geen officiële, gedocumenteerde bron en kan zonder bericht wijzigen of wegvallen. Zet de bron uit in het menu als je dat liever niet gebruikt.
- De Tankerkönig-sleutel staat in `/data` en komt dus ook in je Home Assistant-back-ups.
- De add-on leest van Home Assistant alleen de lijst met trackers en de locatie van de tracker die je kiest. Er wordt niets geschreven.

## Hulp

Fouten en vragen: zie de pagina Issues van de repository.
