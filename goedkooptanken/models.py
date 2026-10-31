"""Gemeenschappelijke datamodellen. Alle providers leveren `Station` objecten."""

from __future__ import annotations

from dataclasses import dataclass, field

# Canonieke brandstofnamen. Elke provider vertaalt zijn eigen namen hiernaartoe.
PETROL95 = "petrol95"  # Euro 95 / E10 / E5
PETROL98 = "petrol98"  # Euro 98 / Super Plus
DIESEL = "diesel"
LPG = "lpg"
FUELS = (PETROL95, PETROL98, DIESEL, LPG)

FUEL_LABELS = {
    PETROL95: "Benzine 95",
    PETROL98: "Benzine 98",
    DIESEL: "Diesel",
    LPG: "LPG",
}


@dataclass
class Station:
    id: str
    name: str
    lat: float
    lon: float
    source: str  # naam van de provider
    address: str = ""
    prices: dict[str, float] = field(default_factory=dict)  # canonieke brandstof -> EUR/liter
    is_open: bool | None = None  # None = onbekend


@dataclass
class Vehicle:
    plate: str
    fuel: str | None  # canonieke brandstof, None als onbekend
    l_per_100km: float | None  # officieel gecombineerd verbruik
    consumption_source: str = ""  # bv. "WLTP" of "NEDC"
    description: str = ""  # bv. "VOLKSWAGEN GOLF"


@dataclass
class Result:
    station: Station
    price: float  # EUR/liter
    km_out: float
    km_back: float
    estimated: bool  # True als afstand geschat is (geen route beschikbaar)
    fill_cost: float  # liters * prijs, in hele centen
    detour_cost: float  # brandstof voor heen en terug, in hele centen
    total: float  # fill_cost + detour_cost (som van de afgeronde bedragen)
    min_round_trip: int = 0  # reistijd heen en terug, hele minuten
    saving_vs_baseline: float = 0.0
    extra_min_vs_baseline: int = 0  # = min_round_trip - die van het dichtstbijzijnde station
    is_baseline: bool = False
    km_to_station: float | None = None  # alleen bij een route: rijafstand vertrek -> station

    @property
    def km_round_trip(self) -> float:
        return self.km_out + self.km_back
