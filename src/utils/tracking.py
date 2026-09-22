"""
Lightweight order status lookup - a plain data read, no LLM/agent pipeline
involved. Used by the "Track Order" UI page so a customer can check status
instantly without spending an LLM call on something that's just a lookup.
"""

import pandas as pd

from src.config import DATA_DIR

_orders_df = None
_couriers_df = None
_warehouses_df = None


def _load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    global _orders_df, _couriers_df, _warehouses_df
    if _orders_df is None:
        _orders_df = pd.read_csv(DATA_DIR / "orders.csv")
    if _couriers_df is None:
        _couriers_df = pd.read_csv(DATA_DIR / "couriers.csv")
    if _warehouses_df is None:
        _warehouses_df = pd.read_csv(DATA_DIR / "warehouses.csv")
    return _orders_df, _couriers_df, _warehouses_df


def get_order_status(order_id: str) -> dict | None:
    orders_df, couriers_df, _ = _load()
    match = orders_df[orders_df["order_id"] == order_id.strip().upper()]
    if match.empty:
        return None

    order = match.iloc[0].to_dict()
    courier_match = couriers_df[couriers_df["courier_id"] == order["courier_id"]]
    courier_name = courier_match.iloc[0]["name"] if not courier_match.empty else "Unassigned"

    return {
        "order_id": order["order_id"],
        "status": order["status"],
        "item_name": order["item_name"],
        "origin_city": order["origin_city"],
        "destination_city": order["destination_city"],
        "order_date": order["order_date"],
        "courier_name": courier_name,
        "packaging_label": order["packaging_label"],
    }
