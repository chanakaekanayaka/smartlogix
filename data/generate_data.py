"""
Generates synthetic Sri Lanka logistics data for SmartLogix.

Run this once before starting the app:
    python data/generate_data.py

The random seed is fixed so the dataset is reproducible - re-running this
script always produces the same data, which keeps the group demo and the
later individual vulnerability-assessment tests consistent.

Outputs (all in this folder):
    warehouses.csv
    couriers.csv
    inventory.csv
    orders.csv
"""

import random
import csv
from pathlib import Path
from faker import Faker

SEED = 42
random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

DATA_DIR = Path(__file__).parent

CITIES = [
    "Colombo", "Kandy", "Galle", "Jaffna", "Negombo", "Matara",
    "Kurunegala", "Anuradhapura", "Batticaloa", "Trincomalee",
    "Ratnapura", "Badulla", "Nuwara Eliya", "Gampaha", "Kalutara",
]

# A warehouse is opened only in a subset of cities (realistic - not every
# city has a SmartLogix warehouse).
WAREHOUSE_CITIES = ["Colombo", "Kandy", "Galle", "Kurunegala", "Jaffna",
                     "Negombo", "Matara", "Anuradhapura"]

# (item_name, category, fragile, avg_weight_kg, avg_price_lkr)
ITEM_CATALOG = [
    ("Refrigerator 250L", "Appliance", True, 55.0, 145000),
    ("Washing Machine", "Appliance", True, 40.0, 98000),
    ("43-inch Television", "Electronics", True, 8.5, 75000),
    ("Sofa Set (3-seater)", "Furniture", False, 60.0, 120000),
    ("Office Chair", "Furniture", False, 12.0, 18500),
    ("Queen Mattress", "Furniture", False, 22.0, 45000),
    ("Mobile Phone (boxed)", "Electronics", True, 0.4, 65000),
    ("Laptop (boxed)", "Electronics", True, 2.2, 210000),
    ("Gas Cooker (4-burner)", "Appliance", True, 18.0, 32000),
    ("Water Filter", "Appliance", False, 6.0, 15500),
    ("Book Carton (mixed)", "General", False, 10.0, 8000),
    ("Ceramic Dinner Set", "Homeware", True, 7.0, 12500),
    ("Mirror (large, framed)", "Homeware", True, 9.0, 22000),
    ("Bicycle", "Sports", False, 14.0, 39000),
    ("Air Conditioner Unit", "Appliance", True, 35.0, 165000),
]

# Weighted delivery outcomes (before we bias by packaging/courier history).
STATUS_WEIGHTS = [
    ("Delivered", 70),
    ("Delayed", 15),
    ("Damaged", 8),
    ("Lost", 3),
    ("In Transit", 4),
]


def weighted_choice(pairs):
    items, weights = zip(*pairs)
    return random.choices(items, weights=weights, k=1)[0]


def generate_warehouses():
    rows = []
    for i, city in enumerate(WAREHOUSE_CITIES, start=1):
        capacity = random.randint(800, 2000)
        rows.append({
            "warehouse_id": f"WH{i:02d}",
            "city": city,
            "capacity": capacity,
            "current_load": random.randint(int(capacity * 0.3), int(capacity * 0.95)),
            "has_cold_storage": random.random() < 0.4,
        })
    with open(DATA_DIR / "warehouses.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return rows


def generate_couriers():
    rows = []
    for i in range(1, 31):
        # A handful of couriers are deliberately given a rough track record -
        # this is what gives the Investigation Agent real signal to reason
        # over instead of guessing randomly every time.
        rough_record = random.random() < 0.2
        rows.append({
            "courier_id": f"CR{i:03d}",
            "name": fake.name(),
            "base_city": random.choice(CITIES),
            "past_delay_count": random.randint(5, 20) if rough_record else random.randint(0, 4),
            "past_damage_count": random.randint(3, 10) if rough_record else random.randint(0, 2),
            "rating": round(random.uniform(2.5, 3.5) if rough_record else random.uniform(3.8, 5.0), 1),
        })
    with open(DATA_DIR / "couriers.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return rows


def generate_inventory(warehouses):
    rows = []
    item_id = 1
    for wh in warehouses:
        # Not every warehouse stocks every item - realistic partial coverage.
        stocked_items = random.sample(ITEM_CATALOG, k=random.randint(8, len(ITEM_CATALOG)))
        for name, category, fragile, weight, price in stocked_items:
            rows.append({
                "item_id": f"ITM{item_id:04d}",
                "item_name": name,
                "category": category,
                "warehouse_id": wh["warehouse_id"],
                "stock_qty": random.choice([0, 0, 2, 5, 8, 12, 20]),  # some out of stock
                "fragile": fragile,
                "unit_weight_kg": weight,
                "unit_price_lkr": price,
            })
            item_id += 1
    with open(DATA_DIR / "inventory.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return rows


def generate_orders(warehouses, couriers, inventory):
    rows = []
    in_stock_items = [i for i in inventory if i["stock_qty"] > 0]
    for order_num in range(1, 301):
        item = random.choice(in_stock_items)
        warehouse = next(w for w in warehouses if w["warehouse_id"] == item["warehouse_id"])
        destination = random.choice(CITIES)
        courier = random.choice(couriers)

        # Packaging label: fragile items SHOULD get a "Fragile" label, but
        # ~15% of the time the warehouse forgets - this is the deliberate,
        # realistic packaging-error signal the Investigation Agent looks for.
        if item["fragile"]:
            packaging_label = "Standard" if random.random() < 0.15 else "Fragile"
        else:
            packaging_label = "Standard"

        status = weighted_choice(STATUS_WEIGHTS)

        # Bias status towards "Damaged" when a fragile item shipped without
        # fragile packaging, or towards "Delayed"/"Damaged" for couriers with
        # a rough track record - this is what makes the fault reasoning
        # meaningful instead of arbitrary.
        if item["fragile"] and packaging_label == "Standard" and random.random() < 0.6:
            status = "Damaged"
        elif courier["past_damage_count"] >= 3 and random.random() < 0.35:
            status = random.choice(["Damaged", "Delayed"])

        weather_flag = random.random() < 0.08

        rows.append({
            "order_id": f"ORD{10000 + order_num}",
            "customer_name": fake.name(),
            "customer_phone": f"07{random.randint(0,9)}{random.randint(1000000,9999999)}",
            "origin_warehouse_id": warehouse["warehouse_id"],
            "origin_city": warehouse["city"],
            "destination_city": destination,
            "item_id": item["item_id"],
            "item_name": item["item_name"],
            "courier_id": courier["courier_id"],
            "order_date": fake.date_between(start_date="-90d", end_date="today").isoformat(),
            "status": status,
            "packaging_label": packaging_label,
            "weather_flag": weather_flag,
        })
    with open(DATA_DIR / "orders.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return rows


if __name__ == "__main__":
    warehouses = generate_warehouses()
    couriers = generate_couriers()
    inventory = generate_inventory(warehouses)
    orders = generate_orders(warehouses, couriers, inventory)
    print(f"Generated {len(warehouses)} warehouses, {len(couriers)} couriers, "
          f"{len(inventory)} inventory rows, {len(orders)} orders.")
    print(f"Files written to: {DATA_DIR}")
