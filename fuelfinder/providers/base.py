"""Basisklasse voor prijsbronnen.

Een nieuwe bron toevoegen = één nieuw bestand in deze map met een klasse die `fetch` implementeert
en haar eigenschappen (naam, landen, ...) invult, plus één regel in `providers/__init__.py`.
De instellingen en de interface tonen de bron dan vanzelf, bij elk land dat hij dekt.
"""

from __future__ import annotations

from ..models import Station


class ProviderError(Exception):
    """Een bron kon geen data leveren (bv. ontbrekende sleutel of netwerkfout)."""


class Provider:
    name: str = ""            # korte sleutel, ook in config.toml
    label: str = ""           # leesbare naam voor de interface
    # Landcodes (ISO, zie countries.COUNTRIES) die de bron dekt. De gebruiker kan de bron alleen
    # voor deze landen aanzetten.
    countries: tuple[str, ...] = ()
    official: bool = False    # officiële, gedocumenteerde bron?
    needs_key: bool = False   # heeft de bron een API-key nodig?
    note: str = ""            # toelichting of disclaimer voor in de interface
    test_point: tuple[float, float, str] | None = None  # (lat, lon, plaatsnaam) voor de testknop
    attribution: str = ""  # verplichte bronvermelding, indien van toepassing
    max_radius_km: float | None = None  # grootste zoekstraal die de bron toestaat (None = onbeperkt)

    @classmethod
    def from_config(cls, cfg) -> "Provider":
        """Maak de bron aan met de instellingen die hij nodig heeft."""
        return cls()

    def fetch(self, lat: float, lon: float, radius_km: float) -> list[Station]:
        raise NotImplementedError
