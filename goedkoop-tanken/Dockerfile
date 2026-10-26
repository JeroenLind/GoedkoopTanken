# Bouwcontext is de hoofdmap van de repository (zie scripts/lokale-addon.sh en .github/workflows).
FROM ghcr.io/home-assistant/base:latest

RUN apk add --no-cache python3

WORKDIR /app
COPY fuelfinder /app/fuelfinder
COPY goedkoop-tanken/rootfs /
RUN chmod a+x /etc/services.d/goedkoop-tanken/run /etc/services.d/goedkoop-tanken/finish

ARG BUILD_VERSION=dev
ARG BUILD_REPOSITORY=https://github.com/jeroenlind/goedkoop-tanken
LABEL io.hass.name="Goedkoop tanken" \
      io.hass.description="Vind het goedkoopste tankstation, inclusief de kosten van de omrit" \
      io.hass.type="addon" \
      io.hass.version="${BUILD_VERSION}" \
      org.opencontainers.image.title="Goedkoop tanken" \
      org.opencontainers.image.source="${BUILD_REPOSITORY}" \
      org.opencontainers.image.licenses="GPL-3.0-only" \
      org.opencontainers.image.version="${BUILD_VERSION}"
