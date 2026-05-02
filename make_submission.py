#!/usr/bin/env python3
"""Generate submission.jsonl from the deterministic compose() engine."""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from bot import compose

ROOT = Path(__file__).parent
DATASET = ROOT / "dataset"

sys.path.insert(0, str(DATASET.resolve()))
from generate_dataset import SEED, expand_customers, expand_merchants, expand_triggers  # noqa: E402


def load_json(path: Path):
    return json.load(open(path, encoding="utf-8"))


def load_seed_data():
    categories = {}
    for path in (DATASET / "categories").glob("*.json"):
        data = load_json(path)
        categories[data["slug"]] = data
    merchants = load_json(DATASET / "merchants_seed.json")["merchants"]
    customers = load_json(DATASET / "customers_seed.json")["customers"]
    triggers = load_json(DATASET / "triggers_seed.json")["triggers"]
    return categories, merchants, customers, triggers


def canonical_pairs(triggers: list[dict]) -> list[dict]:
    by_kind: dict[str, list[dict]] = {}
    for trigger in triggers:
        by_kind.setdefault(trigger["kind"], []).append(trigger)

    pairs = []
    test_id = 1
    for kind, items in sorted(by_kind.items()):
        for trigger in items[:2]:
            pairs.append(
                {
                    "test_id": f"T{test_id:02d}",
                    "trigger_id": trigger["id"],
                    "merchant_id": trigger["merchant_id"],
                    "customer_id": trigger.get("customer_id"),
                }
            )
            test_id += 1
            if len(pairs) >= 30:
                return pairs
    return pairs


def main() -> None:
    categories, merchant_seeds, customer_seeds, trigger_seeds = load_seed_data()
    rnd = random.Random(SEED)
    merchants = expand_merchants(merchant_seeds, rnd)
    customers = expand_customers(customer_seeds, merchants, rnd)
    triggers = expand_triggers(trigger_seeds, merchants, customers, rnd)

    merchants_by_id = {m["merchant_id"]: m for m in merchants}
    customers_by_id = {c["customer_id"]: c for c in customers}
    triggers_by_id = {t["id"]: t for t in triggers}

    lines = []
    for pair in canonical_pairs(triggers):
        trigger = triggers_by_id[pair["trigger_id"]]
        merchant = merchants_by_id[pair["merchant_id"]]
        customer = customers_by_id.get(pair.get("customer_id"))
        category = categories[merchant["category_slug"]]
        message = compose(category, merchant, trigger, customer)
        lines.append(json.dumps({"test_id": pair["test_id"], **message}, ensure_ascii=False))

    (ROOT / "submission.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote submission.jsonl with {len(lines)} rows")


if __name__ == "__main__":
    main()
