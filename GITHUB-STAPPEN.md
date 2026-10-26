# Goedkoop tanken: naar GitHub pushen en releasen

## Kort antwoord

Ja, je kunt gewoon pushen. **Een gewone push maakt nooit een release.** Een release gebeurt alleen als je
bewust een tag `vX.Y.Z` pusht.

## Wat er bij welke actie gebeurt

| Actie | Workflow | Resultaat |
| --- | --- | --- |
| Push naar `main` of pull request | `ci.yaml` | Tests (Python 3.11 en 3.13), controle van de add-on-bestanden, testbouw van het image voor amd64 en arm64. **Er wordt niets gepubliceerd.** |
| Push van een tag `v0.1.0` | `release.yaml` | Tests, controle dat de tag gelijk is aan `version` in `config.yaml`, bouwen, publiceren naar `ghcr.io/<jij>/goedkoop-tanken` (tags `v0.1.0` en `latest`) en een GitHub Release |

## Eerste keer: stappen

1. Maak op GitHub een **lege, publieke** repository `goedkoop-tanken` (zonder README of licentie, die zitten al in de code).
2. Vervang de placeholder in de bestanden `repository.yaml`, `goedkoop-tanken/config.yaml` en `goedkoop-tanken/Dockerfile`:
   ```
   grep -rl GITHUB_GEBRUIKER . | xargs sed -i 's/GITHUB_GEBRUIKER/jouw-gebruikersnaam/g'
   ```
   (Gebruik kleine letters. Op Windows kun je de drie bestanden ook met de hand aanpassen.)
3. Controleer dat `config.toml` en `cache/` niet worden meegenomen (staat in `.gitignore`). Hier staat je Tankerkönig-sleutel in.
4. Push:
   ```
   git init -b main
   git add .
   git status        # kijk of er geen config.toml bij staat
   git commit -m "Eerste versie"
   git remote add origin https://github.com/jouw-gebruikersnaam/goedkoop-tanken.git
   git push -u origin main
   ```
5. Open het tabblad **Actions** en wacht tot `CI` groen is. Dit is de eerste keer dat het Docker-image echt wordt gebouwd,
   dus het kan zijn dat er nog iets gerepareerd moet worden. Dat is veilig: er is niets gepubliceerd.

## Test op de Pi voordat je een release maakt

`scripts/lokale-addon.sh <map>` maakt een map die je naar `/addons/goedkoop-tanken` op Home Assistant kopieert
(Samba of SSH-add-on). Kies daarna **Verversen** in de add-on-winkel en installeer de add-on onder *Lokale add-ons*.

## Een release maken (pas als CI groen is en de Pi-test werkt)

1. Zet `version` in `goedkoop-tanken/config.yaml` (bijv. `"0.1.0"`) en voeg in `goedkoop-tanken/CHANGELOG.md` een kop `## 0.1.0` toe.
2. Commit en push naar `main`.
3. Maak en push de tag:
   ```
   git tag v0.1.0
   git push origin v0.1.0
   ```
4. De workflow `Release` publiceert het image. Daarna:
   - Ga op GitHub naar je profiel, **Packages**, `goedkoop-tanken`, **Package settings** en zet de zichtbaarheid op **Public**
     (anders kan Home Assistant het image niet ophalen).
   - Voeg in Home Assistant onder *Instellingen, Add-ons, Add-on-winkel, Repositories* de URL van je repository toe.

## Let op

- Alleen tags die beginnen met `v` en in de vorm `X.Y.Z` staan triggeren een release. Een tag die niet bij `version` past, laat de workflow falen vóór het publiceren.
- Een tag verwijderen of hergebruiken na publicatie: doe dat niet. Verhoog de versie (`0.1.1`).
- Home Assistant ziet een update alleen als `version` in `config.yaml` hoger is dan de geïnstalleerde versie.
- Dit proces is nog niet in GitHub zelf gedraaid. Verwacht dat de eerste CI-run of release een kleine aanpassing nodig heeft.
