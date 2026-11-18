"""Deterministic facts computed only from public tool results, never task labels."""

import json
from decimal import Decimal

RETAIL_REASONING_RULES = """
Reliable Retail reasoning:
- Tool results may contain _computed facts, calculated deterministically from that exact
  result. Use these for counts and totals. They are observations, not authorization.
- For inventory, distinguish total variants from AVAILABLE variants. A customer's
  question about options available now means available_variant_count, not total_variant_count.
  Never estimate by scanning a long JSON list. Missing availability is unknown, not in stock.
- Do not confuse product IDs, variant item IDs, order IDs, and payment method IDs.
- Retail item modifications and exchanges require a DIFFERENT variant. Do not exchange
  an item to the exact same item ID, even if that variant is in stock. Explain the
  supported different-option exchange and ask for an acceptable alternative; do not
  falsely say an in-stock item is sold out.
- Product type for modification/exchange is determined by product_id, not an option
  value named 'type'. For example, road vs mountain can be variants of the same bicycle
  product. Do not reject a valid same-product variant change as a different product type.
- Before quoting a credit card's last four digits, get_user_details and read last_four.
  A credit_card_... identifier is not a card number or its last four digits.
- For 'all my pending/delivered orders', retrieve the user's profile and inspect their
  order list. Do not make the customer supply order IDs that tools can retrieve.
- When locating an item, match ALL source-item identifying attributes supplied by the
  customer, not just the product name. A laptop with different memory in the first
  order is not a match. Inspect remaining orders or clarify before an exchange.
- Match order-composition clues too: 'the order with a purifier AND a speaker' must
  contain both items. Do not choose the first order containing only the purifier.
- Maintain the customer's full request checklist across turns. If the customer originally
  requested address corrections on ALL eligible orders and the profile, do not silently
  reduce it to only the order containing an item being changed. Enumerate the full scope.
- When both shipping/payment edits and item edits are requested on a pending order,
  complete the confirmed shipping/payment changes BEFORE the one-shot item modification,
  since item modification changes the status and can lock further actions.
- Immediately before the final one-shot item confirmation, ask whether any shipping
  address or payment changes are still needed on that SAME order. This is a preflight
  completeness check, not an offer to reverse unrelated completed actions. Resolve
  those requested changes first, then reconfirm the complete final item plan.
- For a price decrease, explicitly identify the original payment method from the order
  and propose that refund destination first. Do not invent a new method or casually offer
  unrelated payment choices. If the customer explicitly chooses another allowed method,
  honor that choice; never silently substitute the original method.
- Gather ALL requested item changes for an order before a single modify/exchange call;
  preserve every option the user did not ask to change. Check availability for each new item.
- For 'maximize zoom', 'lowest price', or similar requests with unchanged-spec constraints,
  FIRST filter by every explicit unchanged option and availability, THEN optimize the
  requested attribute within that feasible set. Do not maximize globally and change
  resolution, storage, size or other attributes without permission. If no feasible
  alternative exists, explain the actual constraint rather than inventing inventory.
- For 'best/highest specification I can get for my purchase price', optimize only within
  AVAILABLE variants at or below that budget. Offer the best feasible option directly;
  do not frame an unavailable or over-budget upgrade as the expected choice.
- If a customer gives conflicting order/action mappings across turns, summarize the
  conflict using order IDs and item names and ask them to resolve it before a write.
  Do not invent order creation dates when the tool provides none.
- A return request and an exchange request on the SAME delivered order are mutually
  exclusive: either action moves the order out of delivered status. If both are requested,
  explain the conflict and ask which request to prioritize BEFORE either write. Never
  promise both, perform the first action and discover the second is blocked afterward.
- Keep the scope of a rollback exact. Reverting only the default account address does
  not revert order addresses. Once a request is complete, do not suggest extra database
  changes, reversals or unrelated actions that the customer did not request.
- Compute money with calculate when needed, using item prices from the actual order and
  selected variants. For repeated item IDs, account for quantities exactly.
- Honor the current interface's confirmation contract before committing writes. A new
  proposed action cannot inherit approval for different items, amounts, orders or methods.
- In conversational benchmark mode, collect missing payment-method choices separately
  from final approval. Once every detail is known, present the concrete final order,
  item changes, amount and chosen method, then ask for explicit confirmation. Do not
  combine 'which method?' with 'shall I execute?' in one question. If the customer
  changes the method or item list during confirmation, summarize the new plan and
  reconfirm before a one-shot write. In web mode, the action card is that final approval.
- Recover from tool errors by correcting arguments using observed data; do not repeatedly
  submit the same invalid call or claim a write succeeded when a tool returned an error.
- Do not invent stock, payment details, dates, refunds or delivery promises.
- Never guess identity information. Honor explicit customer corrections; if a lookup
  fails, ask for the supported alternative verification fields rather than fabricate them.
"""


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


def enrich_observation(name, result):
    """Return a new result with optional generic arithmetic facts; retain original fields."""
    if not isinstance(result, dict) or "error" in result:
        return result
    facts = {}
    if name == "get_product_details" and isinstance(result.get("variants"), dict):
        variants = result["variants"]
        available = [key for key, variant in variants.items() if variant.get("available") is True]
        unavailable = [
            key for key, variant in variants.items() if variant.get("available") is False
        ]
        facts = {
            "source": "deterministic_from_this_tool_result",
            "total_variant_count": len(variants),
            "available_variant_count": len(available),
            "unavailable_variant_count": len(unavailable),
            "unknown_availability_count": len(variants) - len(available) - len(unavailable),
            "available_item_ids": available,
            "unavailable_item_ids": unavailable,
        }
        priced = [
            (key, Decimal(str(variants[key]["price"])))
            for key in available
            if variants[key].get("price") is not None
        ]
        if priced:
            cheapest = min(price for _, price in priced)
            facts["minimum_available_price"] = str(cheapest.quantize(Decimal("0.01")))
            facts["cheapest_available_item_ids"] = [
                key for key, price in priced if price == cheapest
            ]
            facts["price_note"] = (
                "Global minimum across available variants; user-specific option constraints still apply."
            )
    elif name == "get_order_details" and isinstance(result.get("items"), list):
        items = result["items"]
        if all(isinstance(item, dict) and "price" in item for item in items):
            total = sum((Decimal(str(item["price"])) for item in items), start=Decimal(0))
            facts = {
                "source": "deterministic_from_this_tool_result",
                "item_count": len(items),
                "sum_item_prices": str(total.quantize(Decimal("0.01"))),
                "note": "Sum of order item prices only; not a new payment or refund.",
            }
    return {**result, "_computed": facts} if facts else result


def enrich_tool_content(name, content):
    """Transform a JSON tool message for model context, preserving non-JSON outputs."""
    try:
        result = json.loads(content)
    except (ValueError, TypeError):
        return content
    enriched = enrich_observation(name, result)
    return json.dumps(enriched, ensure_ascii=False) if enriched is not result else content
