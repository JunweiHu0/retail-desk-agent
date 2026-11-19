"""Private reference fixtures and the HTTP evaluator (never imported by the agent)."""

TAU2_SHA = "0c69df456a96aa76a1162591574dad9c427a34d7"
PROTOCOL_VERSION = "retail-http-v2"
COMPARATOR_VERSION = "complete-customer-initial-orders-v1"
VALIDATION20 = tuple("4,6,8,21,22,25,28,35,46,52,54,59,72,80,81,84,96,99,104,112".split(","))
SMOKE8 = tuple("0,3,10,16,24,34,41,47".split(","))
WRITE_TOOLS = frozenset(
    {
        "cancel_pending_order",
        "exchange_delivered_order_items",
        "modify_pending_order_address",
        "modify_pending_order_items",
        "modify_pending_order_payment",
        "modify_user_address",
        "return_delivered_order_items",
    }
)
