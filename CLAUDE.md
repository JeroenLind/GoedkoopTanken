# Afspraken voor Claude in deze repository

## Requirements bijhouden (altijd, zonder dat erom gevraagd wordt)

`docs/REQUIREMENTS.md` is de bron van waarheid voor wat de app moet doen. Houd het bij als onderdeel van elke wijziging:

1. **Nieuwe wens of idee van Jeroen** (in het gesprek of in `Todo.md`): voeg het in dezelfde wijziging toe als eis, met herkomst *Jeroen* en status *Gepland*.
2. **Functie opgeleverd**: zet de status van de eis op *Klaar* in dezelfde commit als de code. Vink het punt in `Todo.md` pas af nadat Jeroen heeft bevestigd dat het werkt.
3. **Wijziging of schrapping van gedrag**: pas de bestaande eis aan of verwijder hem, en zeg dat in je antwoord.
4. **Alleen opnemen wat Jeroen heeft gezegd of goedgekeurd.** Vind je zelf een eis belangrijk (beveiliging, prestatie, toegankelijkheid enzovoort), vraag dat eerst aan Jeroen en neem hem alleen op als hij ja zegt (herkomst *Bevestigd*). Verzin geen getallen of grenzen: zet ze als *Open* of als voorstel.
5. Een kleine bugfix die geen gedrag verandert, hoeft het document niet aan te passen.
6. Noem in je antwoord in één regel welke eisen je hebt toegevoegd of gewijzigd.

## Verder

- Taal van interface, documentatie en commitberichten: Nederlands.
- Een gewone push mag nooit een release maken; alleen een tag `vX.Y.Z` doet dat (zie `GITHUB-STAPPEN.md`).
- Draai voor het committen `python -m unittest discover -s tests`.
