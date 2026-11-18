"""Add repeatable synthetic customer fixtures without overwriting existing retail data."""

import argparse
import json
import sqlite3
from datetime import datetime

from tau2.domains.retail.data_model import RetailDB

from backend import config
from backend.store import Store

PEOPLE = [
    ("li_ming", "Ming", "Li", "li.ming@retail-demo.example.com", "Austin", "TX", "78701"),
    ("wang_fang", "Fang", "Wang", "wang.fang@retail-demo.example.com", "Seattle", "WA", "98101"),
    ("zhang_wei", "Wei", "Zhang", "zhang.wei@retail-demo.example.com", "Boston", "MA", "02108"),
    ("chen_xi", "Xi", "Chen", "chen.xi@retail-demo.example.com", "Denver", "CO", "80202"),
    ("liu_yang", "Yang", "Liu", "liu.yang@retail-demo.example.com", "Portland", "OR", "97201"),
    ("zhao_min", "Min", "Zhao", "zhao.min@retail-demo.example.com", "Chicago", "IL", "60601"),
]


def seed(store):
    created_users = created_orders = 0
    manifest = []
    with store.tx() as cx:
        data = store.dataset(cx)
        products = list(data["products"].values())
        for index, (slug, first, last, email, city, state, zipcode) in enumerate(PEOPLE):
            uid = f"demo_{slug}_2026"
            card, gift = f"credit_card_demo_{index + 1:04d}", f"gift_card_demo_{index + 1:04d}"
            order_ids = [f"#W{9000001 + index * 3 + j}" for j in range(3)]
            address = {
                "address1": f"{100 + index} Demo Avenue",
                "address2": f"Unit {index + 1}",
                "city": city,
                "state": state,
                "country": "USA",
                "zip": zipcode,
            }
            if uid not in data["users"]:
                data["users"][uid] = {
                    "user_id": uid,
                    "name": {"first_name": first, "last_name": last},
                    "email": email,
                    "address": address,
                    "orders": order_ids,
                    "payment_methods": {
                        card: {
                            "id": card,
                            "source": "credit_card",
                            "brand": "visa",
                            "last_four": f"{1001 + index}",
                        },
                        gift: {"id": gift, "source": "gift_card", "balance": 500.0},
                    },
                }
                created_users += 1
            elif data["users"][uid]["email"] != email:
                raise ValueError("Synthetic user ID collides with existing customer")
            for j, status in enumerate(("pending", "delivered", "processed")):
                oid = order_ids[j]
                if oid in data["orders"]:
                    if data["orders"][oid]["user_id"] != uid:
                        raise ValueError("Synthetic order ID collides with existing order")
                    continue
                items = []
                for product in (
                    products[(index * 5 + j) % len(products)],
                    products[(index * 5 + j + 1) % len(products)],
                ):
                    variant = next(v for v in product["variants"].values() if v["available"])
                    items.append(
                        {
                            "name": product["name"],
                            "product_id": product["product_id"],
                            "item_id": variant["item_id"],
                            "options": variant["options"],
                            "price": variant["price"],
                        }
                    )
                amount = round(sum(item["price"] for item in items), 2)
                data["orders"][oid] = {
                    "order_id": oid,
                    "user_id": uid,
                    "address": address,
                    "items": items,
                    "status": status,
                    "fulfillments": [
                        {
                            "tracking_id": [f"DEMO-TRACK-{index + 1}-{j + 1}"],
                            "item_ids": [item["item_id"] for item in items],
                        }
                    ]
                    if status == "delivered"
                    else [],
                    "payment_history": [
                        {"transaction_type": "payment", "amount": amount, "payment_method_id": card}
                    ],
                }
                created_orders += 1
            manifest.append(
                {
                    "user_id": uid,
                    "name": f"{first} {last}",
                    "email": email,
                    "zip": zipcode,
                    "orders": [
                        {"order_id": oid, "status": data["orders"][oid]["status"]}
                        for oid in order_ids
                    ],
                }
            )
        validated = RetailDB.model_validate(data)
        for user in validated.users.values():
            assert all(validated.orders[oid].user_id == user.user_id for oid in user.orders)
        store.save_dataset(cx, validated.model_dump(mode="json"))
    return {
        "created_users": created_users,
        "created_orders": created_orders,
        "total_users": len(validated.users),
        "total_orders": len(validated.orders),
        "customers": manifest,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        parser.error("Pass --apply to add synthetic data to the configured local database")
    store = Store()
    backup = config.ROOT / "runtime/backups" / f"pre-demo-{datetime.now():%Y%m%d-%H%M%S}.sqlite3"
    backup.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(store.path) as source, sqlite3.connect(backup) as destination:
        source.backup(destination)
    result = seed(store)
    result["backup"] = str(backup)
    output = config.ROOT / "docs/demo-customers.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
