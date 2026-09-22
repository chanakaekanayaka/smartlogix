"""
Distance and delivery cost/time estimation between Sri Lankan cities.

Uses the haversine formula on real city coordinates (data/sri_lanka_cities.csv)
- free and local, no Google Maps API key needed. A 1.3x multiplier approximates
actual road distance vs. straight-line ("as the crow flies") distance; this is
a documented simplification, not a real routing engine.
"""

import csv
import math
from functools import lru_cache

from src.config import DATA_DIR

CITIES_FILE = DATA_DIR / "sri_lanka_cities.csv"
ROAD_DISTANCE_MULTIPLIER = 1.3

BASE_FEE_LKR = 500
PER_KM_RATE_LKR = 45
PER_KG_RATE_LKR = 120
FRAGILE_PACKAGING_FEE_LKR = 350


@lru_cache
def _load_city_coords() -> dict[str, tuple[float, float]]:
    coords = {}
    with open(CITIES_FILE, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            coords[row["city"]] = (float(row["latitude"]), float(row["longitude"]))
    return coords


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0  # Earth's radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def get_road_distance_km(city_a: str, city_b: str) -> float | None:
    coords = _load_city_coords()
    if city_a not in coords or city_b not in coords:
        return None
    lat1, lon1 = coords[city_a]
    lat2, lon2 = coords[city_b]
    straight_line = haversine_km(lat1, lon1, lat2, lon2)
    return round(straight_line * ROAD_DISTANCE_MULTIPLIER, 1)


def estimate_delivery_cost(distance_km: float, weight_kg: float, fragile: bool) -> dict:
    """Transparent cost breakdown - shown to the customer for explainability."""
    distance_fee = round(distance_km * PER_KM_RATE_LKR, 2)
    weight_fee = round(weight_kg * PER_KG_RATE_LKR, 2)
    packaging_fee = FRAGILE_PACKAGING_FEE_LKR if fragile else 0
    total = BASE_FEE_LKR + distance_fee + weight_fee + packaging_fee
    return {
        "base_fee_lkr": BASE_FEE_LKR,
        "distance_fee_lkr": distance_fee,
        "weight_fee_lkr": weight_fee,
        "packaging_fee_lkr": packaging_fee,
        "total_lkr": round(total, 2),
    }
