"""Voertuiggegevens opzoeken via het kenteken (RDW open data, geen sleutel nodig).

De RDW-dataset "Gekentekende voertuigen brandstof" (8ys7-d773) bevat per kenteken één
of meer regels (een hybride heeft er twee). Veldnamen die we gebruiken:
  brandstof_omschrijving, brandstofverbruik_gecombineerd (NEDC, l/100km),
  brandstofverbruik_gecombineerd_wltp (WLTP, l/100km).
Het exacte veldgebruik is niet vooraf geverifieerd, daarom is de parser tolerant en toont
`goedkooptanken vehicle <kenteken> --raw` het ruwe antwoord.
"""

from __future__ import annotations

import re
import urllib.parse

from . import http
from .models import DIESEL, LPG, PETROL95, Vehicle

RDW_FUEL_URL = "https://opendata.rdw.nl/resource/8ys7-d773.json"
RDW_BASE_URL = "https://opendata.rdw.nl/resource/m9d7-ebf2.json"

_FUEL_MAP = {"benzine": PETROL95, "diesel": DIESEL, "lpg": LPG}

# Voorkeursvolgorde: WLTP is realistischer dan NEDC.
_CONSUMPTION_FIELDS = (
    ("brandstof_verbruik_gecombineerd_wltp", "WLTP"),  # veldnaam zoals de RDW hem nu geeft
    ("brandstofverbruik_gecombineerd_wltp", "WLTP"),
    ("brandstofverbruik_gecombineerd", "NEDC"),
)


def normalize_plate(plate: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", plate).upper()


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        number = float(str(value).replace(",", "."))
    except ValueError:
        return None
    return number if number > 0 else None


def parse_fuel_rows(plate: str, rows: list[dict]) -> Vehicle:
    """Kies uit de RDW-regels de brandstofregel die we kunnen gebruiken."""
    fallback_fuel = None
    for row in rows:
        fuel = _FUEL_MAP.get(str(row.get("brandstof_omschrijving", "")).strip().lower())
        if fuel and fallback_fuel is None:
            fallback_fuel = fuel
        if not fuel:
            continue  # elektriciteit e.d. heeft geen pompverbruik
        for field_name, label in _CONSUMPTION_FIELDS:
            value = _to_float(row.get(field_name))
            if value:
                return Vehicle(plate, fuel, value, label)
        # Onbekende veldnaam? Neem dan een veld dat 'verbruik' en 'gecombineerd' bevat.
        for key in sorted(row, key=lambda k: "wltp" not in k):
            if "verbruik" in key and "gecombineerd" in key:
                value = _to_float(row.get(key))
                if value:
                    return Vehicle(plate, fuel, value, "WLTP" if "wltp" in key else "NEDC")
    return Vehicle(plate, fallback_fuel, None, "")


def lookup(plate: str) -> tuple[Vehicle, list[dict]]:
    """Zoek een kenteken op. Retourneert (voertuig, ruwe brandstofregels)."""
    plate = normalize_plate(plate)
    if not plate:
        raise ValueError("Leeg kenteken")
    rows = http.fetch_json(RDW_FUEL_URL + "?" + urllib.parse.urlencode({"kenteken": plate}))
    if not rows:
        raise http.FetchError(f"Kenteken {plate} niet gevonden bij de RDW")
    vehicle = parse_fuel_rows(plate, rows)
    try:  # merk/type is alleen informatief; mislukken is niet erg
        base = http.fetch_json(RDW_BASE_URL + "?" + urllib.parse.urlencode({"kenteken": plate}))
        if base:
            merk, naam = base[0].get("merk") or "", base[0].get("handelsbenaming") or ""
            vehicle.description = naam if merk and naam.upper().startswith(merk.upper()) \
                else f"{merk} {naam}".strip()
    except http.FetchError:
        pass
    return vehicle, rows
