# Wijzigingen

## Nog niet uitgebracht
- Nieuw helpmenu (knop Help bovenaan): uitleg over rondom mij en langs een route, het resultaat, de berekening en alle instellingen met hun effect.
- Het instellingenmenu toont bij het thuisadres en de vaste adressen alleen nog het adres, niet meer de coördinaten.
- Nieuwe aanrader: de extra rijtijd telt mee tegen de waarde van je tijd (standaard € 15 per uur, instelbaar; 0 = alleen op prijs). De lijst blijft op prijs gesorteerd, maar de groene markering gaat naar de aanrader. Het grote resultaat heeft nu een knop Navigeer en noemt het goedkoopste station als dat niet de aanrader is.
- De referentie voor de besparing is het goedkoopste station op de route; in de instellingen kies je of dat op afstand (standaard minder dan 0,5 km omweg) of op tijd (standaard minder dan 3 minuten) wordt bepaald, en beide grenzen zijn instelbaar. Dezelfde regels gelden bij zoeken rondom een locatie.
- Het overzicht boven de resultaten toont geen gegevens over de auto meer (naam, brandstof, verbruik); het verbruik staat nog wel in de berekening per station.
- Langs een route zijn extra kilometers en minuten gemeten ten opzichte van de snelste route; dat staat nu ook zo in de uitleg, en het detailpaneel toont de omweg in minuten én kilometers, met de lengte en rijtijd van de snelste route zelf. Export en API vermelden de referentieroute.
- Nieuwe naam en uiterlijk: overal "Goedkoop tanken", met een groen pictogram (druppel met pijl omlaag) in de app, het tabblad en de add-on, en een nieuw kleurenpalet. Op een breed scherm staat de kaart met het detail naast de lijst. Technisch heet het pakket nu `goedkooptanken`.
- Bronnen kiezen is overzichtelijker: een lijst met bronnen (status, test, toelichting) en een lijst met landen waar je per land bronnen aan of uit zet en de prioriteit bepaalt. De eerdere bronkeuze vervalt; de standaard geldt (ANWB voor Nederland en België, Tankerkönig en ANWB voor Duitsland).
- België wordt meegenomen: Belgische stations komen via ANWB Onderweg binnen.

## 0.1.0
- Eerste versie als Home Assistant-add-on: zoeken rond een punt en langs een route, kaart, berekeningsdetail, export.
- Bij een route kun je een maximale rijafstand opgeven (bijna lege tank).
