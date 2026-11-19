"""Main-compatible normalization of browser item-change proposals."""


def normalize_variant_changes(name, args):
    """Omit no-op lines only when at least one genuine change remains; never alter choices."""
    if name not in {"modify_pending_order_items", "exchange_delivered_order_items"}:
        return args
    old, new = args.get("item_ids"), args.get("new_item_ids")
    if not isinstance(old, list) or not isinstance(new, list) or len(old) != len(new):
        return args
    changes = [(a, b) for a, b in zip(old, new) if a != b]
    if not changes or len(changes) == len(old):
        return args
    return {**args, "item_ids": [a for a, _ in changes], "new_item_ids": [b for _, b in changes]}


def variant_change_error(name, args):
    """Reject a policy-invalid same-variant change before any side effect."""
    if name not in {"modify_pending_order_items", "exchange_delivered_order_items"}:
        return None
    old, new = args.get("item_ids", []), args.get("new_item_ids", [])
    if not isinstance(old, list) or not isinstance(new, list):
        return None
    if len(old) == len(new) and any(a == b for a, b in zip(old, new)):
        return (
            "Retail modifications and exchanges require a different variant of the same "
            "product. A replacement with the exact same item ID is not supported, even "
            "when it is available. Please choose which different product options you want."
        )
    return None
