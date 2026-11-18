"""Agent-facing Retail tool interfaces; official business writes remain authoritative."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from tau2.domains.retail.data_model import RetailDB

TOOL_PROFILES = {
    "tools_described": "retail-described-v1",
    "tools_structured": "retail-structured-v1",
    "tools_extended": "retail-extended-v1",
}
STRUCTURED_VARIANTS = {"tools_structured", "tools_extended"}

# These describe the current HTTP execution contract, not native immediate writes.
PREVIEW_DESCRIPTION = (
    " This call validates and stages a preview ONLY; it does not commit the database. "
    "Once the requested details are known, call it without an extra chat yes. "
    "Then stop on awaiting_confirmation. Only the application's approve decision commits "
    "the exact proposal; rejected means unchanged. Never report the preview as executed."
)
DESCRIPTIONS = {
    "find_user_id_by_email": "Look up the customer ID by their account email. Use only when no authenticated customer is already provided. Returns the customer ID; not an order or product ID.",
    "find_user_id_by_name_zip": "Look up the customer ID using their name and ZIP when their email is unavailable. Do not switch an already authenticated session to another customer.",
    "get_user_details": "Read the authenticated customer's profile, default address, order IDs and saved payment methods. A saved method is an available option, not evidence the user selected it. Do not ask for identity again when context is preauthenticated.",
    "get_order_details": "Read an owned order's current status, items with item_id/product_id/options, address, fulfillments and payment history. order_id includes #W. Match all user-requested filters before selecting items. An order can contain duplicate item IDs; preserve multiplicity. Reading never changes the order.",
    "get_product_details": "Read one product's complete variant catalog. product_id identifies a product family; each variant's item_id identifies a selectable option. Count all variants separately from available variants. Preserve required size/style/other options when comparing replacements. This does not select or reserve a variant.",
    "get_item_details": "Read one exact item variant by item_id, including its attributes, availability and price. item_id and product_id are different identifiers. Does not reserve or change stock.",
    "list_all_product_types": "List product types and their product IDs. Use these exact IDs/names to query a product catalog; this does not list the customer's orders.",
    "calculate": "Compute arithmetic using +, -, *, / and parentheses; returns a decimal string rounded to two places. Calculation is not a charge, refund or database change.",
    "transfer_to_human_agents": "Transfer this conversation to a human with a concise factual summary when policy requires it or the request cannot be handled. Does not complete pending business changes; state what remains undone.",
    "cancel_pending_order": "Stage cancellation of a pending owned order. reason must be 'no longer needed' or 'ordered by mistake'. Actual execution cancels the order and refunds its payments to their original methods. A user withdrawing an unexecuted cancellation wants to KEEP the order, not cancel it with a different reason.",
    "exchange_delivered_order_items": "Stage exchange of selected delivered-order items for available variants of the SAME products. Align item_ids and new_item_ids positionally, retaining duplicate quantities. Include every requested exchange for this order together: after actual exchange/return execution further changes are restricted. Resolve the user's price-difference payment/refund choice first.",
    "modify_pending_order_address": "Stage the full shipping address for ONE pending owned order. Use all required address fields in the database's conventions; preserve fields the user asked to keep. Does not change the account default address or any other order.",
    "modify_user_address": "Stage the authenticated user's full default address. Does not update any existing order's shipping address. A request to update both account and orders needs separate operations.",
    "modify_pending_order_items": "Stage a pending order's item changes to available variants of the SAME products. Include all requested changes for that order in ONE operation, with aligned item_ids/new_item_ids and a selected payment method for the difference. Actual execution permits this modification only once and restricts later cancellation/modification; do requested address/payment changes first. Do not expand a 'small items' request to other sizes.",
    "modify_pending_order_payment": "Stage replacing the payment method of ONE pending order with another valid saved method. A gift card must cover the full order; split payment is unsupported. Preserve the user's choice, and use IDs from their saved methods.",
    "return_delivered_order_items": "Stage return of selected delivered-order items. Include all requested return items together, retaining duplicate quantities. Refund must use an eligible original payment method or an existing gift card; ask when the user's preference is unknown. After actual return/exchange execution the order is restricted. Preview alone is not a refund.",
}


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    params: type[BaseModel]


class FindOrderItems(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statuses: list[
        Literal[
            "pending",
            "pending (item modified)",
            "processed",
            "delivered",
            "cancelled",
            "return requested",
            "exchange requested",
        ]
    ] = Field(
        default_factory=list,
        description="Exact order statuses; empty means all. 'pending' does not include 'pending (item modified)'.",
    )
    product_id: str | None = Field(
        default=None, description="Optional exact product family ID, not item_id."
    )
    product_name: str | None = Field(
        default=None,
        description="Optional exact product name, case-insensitive; use known catalog names, not fuzzy keywords.",
    )
    options: dict[str, str] = Field(
        default_factory=dict,
        description="Required item attributes, e.g. size=S, style=v-neck. All filters must match; no automatic relaxation or synonym guessing.",
    )


class FindVariants(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: str = Field(
        description="Exact product family ID from a customer's item or product catalog."
    )
    options: dict[str, str] = Field(
        default_factory=dict,
        description="All required variant attributes, e.g. color=purple, size=S. Keys and values match case-insensitively after trimming whitespace.",
    )
    available_only: bool = Field(
        default=True, description="Only return variants currently available when true."
    )


EXTRA_READ_TOOLS = {
    "find_customer_order_items": ToolDefinition(
        "find_customer_order_items",
        "Read-only: find matching items across ALL orders owned by the authenticated customer. Apply every supplied status/product/attribute filter with AND. Names/options match exactly ignoring case and outer whitespace; no synonyms, fuzzy matching or relaxed fallback. Returns every matching occurrence with order_id, order_status, item_index, item_id, product_id, name, options and price. Duplicates retain separate item_index positions. Empty matches means none matched, not permission to choose other items. Never modifies DB or creates a preview.",
        FindOrderItems,
    ),
    "find_product_variants": ToolDefinition(
        "find_product_variants",
        "Read-only: filter ONE product's variants by all requested attributes and availability. Returns every match sorted by item_id, counts for all/available/matched variants, and observed option values for clarifying zero matches. Attribute keys/values match exactly ignoring case and outer whitespace. No synonym guessing, automatic fallback, preference choice, reservation or database change. Preserve user-required attributes in options; ask before relaxing them. Use returned item_id values in official write tools.",
        FindVariants,
    ),
}


def matches_options(actual: dict[str, str], requested: dict[str, str]) -> bool:
    actual = {k.strip().casefold(): v.strip().casefold() for k, v in actual.items()}
    return all(
        actual.get(k.strip().casefold()) == v.strip().casefold() for k, v in requested.items()
    )


def read_helper(name: str, params: FindOrderItems | FindVariants, db: RetailDB, user_id: str):
    """Pure reads of the same episode data available through official tools."""
    if name == "find_customer_order_items":
        matches = []
        for order in sorted(db.orders.values(), key=lambda o: o.order_id):
            if order.user_id != user_id or (
                params.statuses and order.status not in params.statuses
            ):
                continue
            for index, item in enumerate(order.items):
                if params.product_id is not None and item.product_id != params.product_id:
                    continue
                if (
                    params.product_name is not None
                    and item.name.strip().casefold() != params.product_name.strip().casefold()
                ):
                    continue
                if matches_options(item.options, params.options):
                    matches.append(
                        {
                            "order_id": order.order_id,
                            "order_status": order.status,
                            "item_index": index,
                            **item.model_dump(mode="json"),
                        }
                    )
        return {"filters": params.model_dump(), "match_count": len(matches), "matches": matches}
    product = db.products.get(params.product_id)
    if product is None:
        raise ValueError("Product not found")
    variants = sorted(product.variants.values(), key=lambda v: v.item_id)
    matches = [
        v.model_dump(mode="json")
        for v in variants
        if (not params.available_only or v.available) and matches_options(v.options, params.options)
    ]
    option_values = {}
    for variant in variants:
        for key, value in variant.options.items():
            option_values.setdefault(key, set()).add(value)
    return {
        "product_id": product.product_id,
        "name": product.name,
        "filters": params.model_dump(),
        "total_variant_count": len(variants),
        "available_variant_count": sum(v.available for v in variants),
        "match_count": len(matches),
        "matches": matches,
        "option_values": {k: sorted(v) for k, v in sorted(option_values.items())},
    }


def format_result(name, result, writes):
    """Preserve raw business data; do not mask errors or label previews executed."""
    if isinstance(result, dict) and "error" in result:
        return {**result, "status": "error", "tool": name}
    if name in writes:
        return {**result, "execution_state": "preview_only"}
    if name == "transfer_to_human_agents":
        return result
    formatted = {"status": "observed", "tool": name, "read_only": True, "data": result}
    if name == "get_product_details":
        variants = result["variants"].values()
        formatted["summary"] = {
            "total_variant_count": len(result["variants"]),
            "available_variant_count": sum(v["available"] for v in variants),
        }
    return formatted
