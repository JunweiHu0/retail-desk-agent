"""Exact no-op WRITE exceptions confirmed by the immutable all114 reference audit."""

AUDIT_TAU2_SHA = "0c69df456a96aa76a1162591574dad9c427a34d7"
AUDIT_REPORT_PATH = "reference-audit.json"

AUDIT_REPORT_SHA256 = "46024e9396dd7076e021e6b0cae2705fcbcad898080e2728958c5e91cc15b751"
AUDITED_UNCHANGED_DB_HASH = "3ca5bd70e621602e23d909c87f26224a1a486e75955d8a6da53721ec224b23dc"

EXPECTED_WRITE_FAILURES = {
    ("64", "64_6"): {
        "name": "exchange_delivered_order_items",
        "arguments": {
            "order_id": "#W7464385",
            "item_ids": ["1810466394"],
            "new_item_ids": ["6700049080"],
            "payment_method_id": "paypal_1261484",
        },
        "error_type": "ValueError",
        "error": "Non-delivered order cannot be exchanged",
        "rationale": "Audited native no-op: exchange is attempted on a pending order; continue to reference action64_7, which successfully modifies its items.",
    },
    ("105", "106_0"): {
        "name": "exchange_delivered_order_items",
        "arguments": {
            "order_id": "#W4316152",
            "item_ids": ["7292993796", "7292993796"],
            "new_item_ids": ["3761330360", "9647374798"],
            "payment_method_id": "gift_card_7245904",
        },
        "error_type": "ValueError",
        "error": "Insufficient gift card balance to pay for the price difference",
        "rationale": "Audited native no-op: the reference gift card cannot cover the exchange. This task's DB target is the unchanged seed; reference_issue is retained and no NL assertion is scored by the adapted DB-only protocol.",
    },
}
