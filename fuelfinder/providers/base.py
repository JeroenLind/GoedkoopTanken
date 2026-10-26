"""Basisklasse voor prijsbronnen.

Een nieuwe bron (of grens) toevoegen = één nieuw bestand in deze map met een klasse die
`fetch` implementeert, plus één regel in `providers/__init__.py`.
"""

from __future__ import annotations

from ..models import Station


class ProviderError(Exception):
    """Een bron kon geen data leveren (bv. ontbrekende sleutel of netwerkfout)."""


class Provider:
    name: str = ""
    # Landcodes (ISO) die de bron dekt. Alleen informatief; handig bij uitbreiding.
    countries: tuple[str, ...] = ()
    attribution: str = ""  # verplichte bronvermelding, indien van toepassing
    max_radius_km: float | None = None  # grootste zoekstraal die de bron toestaat (None = onbeperkt)

    def fetch(self, lat: float, lon: float, radius_km: float) -> list[Station]:
        raise NotImplementedError
