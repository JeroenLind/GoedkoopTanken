#!/usr/bin/env bash
# Maakt een map die je naar de map /addons van Home Assistant kunt kopiëren, om de add-on lokaal
# te testen zonder GHCR. De Supervisor bouwt dan zelf op je Pi (duurt even).
# Gebruik: scripts/lokale-addon.sh /pad/naar/uitvoer
set -euo pipefail
out="${1:?geef een uitvoermap op}"
root="$(cd "$(dirname "$0")/.." && pwd)"
rm -rf "$out"; mkdir -p "$out"
cp -r "$root/goedkoop-tanken/." "$out/"
cp -r "$root/fuelfinder" "$out/fuelfinder"
find "$out" -name __pycache__ -type d -prune -exec rm -rf {} +
# Zonder image-regel bouwt de Supervisor lokaal; het Dockerfile verwacht de code naast zich.
sed -i '/^image:/d' "$out/config.yaml"
sed -i 's#COPY fuelfinder /app/fuelfinder#COPY fuelfinder /app/fuelfinder#; s#COPY goedkoop-tanken/rootfs /#COPY rootfs /#' "$out/Dockerfile"
echo "Klaar: kopieer '$out' naar /addons/goedkoop-tanken op je Home Assistant en kies Verversen in de add-on-winkel."
