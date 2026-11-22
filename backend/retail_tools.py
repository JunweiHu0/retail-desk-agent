"""Retail toolkit with a fix for the upstream multi-item modify bug.

Upstream tau2 ``RetailTools.modify_pending_order_items`` (commit 0c69df4) validates
each requested variant correctly, but its final write loop reuses the ``variant``
variable left over from the validation loop. When several items are modified in one
call, every modified item receives the price and options of the *last* requested
variant, while the payment difference is computed correctly. Agents then see an
order whose items do not match what was requested and often transfer to a human.

``FixedRetailTools`` keeps every other tool, policy check and error message from
upstream and only looks the variant up per item when writing. Single-item modifies
behave exactly as upstream.
"""

from typing import List

from tau2.domains.retail.data_model import GiftCard, Order, OrderPayment
from tau2.domains.retail.tools import RetailTools
from tau2.environment.toolkit import ToolType, is_tool


class FixedRetailTools(RetailTools):
    @is_tool(ToolType.WRITE)
    def modify_pending_order_items(
        self,
        order_id: str,
        item_ids: List[str],
        new_item_ids: List[str],
        payment_method_id: str,
    ) -> Order:
        order = self._get_order(order_id)
        if order.status != "pending":
            raise ValueError("Non-pending order cannot be modified")

        all_item_ids = [item.item_id for item in order.items]
        for item_id in item_ids:
            if item_ids.count(item_id) > all_item_ids.count(item_id):
                raise ValueError(f"{item_id} not found")

        if len(item_ids) != len(new_item_ids):
            raise ValueError("The number of items to be exchanged should match")

        diff_price = 0
        for item_id, new_item_id in zip(item_ids, new_item_ids):
            if item_id == new_item_id:
                raise ValueError(
                    "The new item id should be different from the old item id"
                )
            item = next((item for item in order.items if item.item_id == item_id), None)
            if item is None:
                raise ValueError(f"Item {item_id} not found")
            variant = self._get_variant(item.product_id, new_item_id)
            if not variant.available:
                raise ValueError(f"New item {new_item_id} not found or available")
            diff_price += variant.price - item.price

        payment_method = self._get_payment_method(order.user_id, payment_method_id)
        if isinstance(payment_method, GiftCard) and payment_method.balance < diff_price:
            raise ValueError("Insufficient gift card balance to pay for the new item")

        order.payment_history.append(
            OrderPayment(
                transaction_type="payment" if diff_price > 0 else "refund",
                amount=abs(diff_price),
                payment_method_id=payment_method_id,
            )
        )
        if isinstance(payment_method, GiftCard):
            payment_method.balance -= diff_price
            payment_method.balance = round(payment_method.balance, 2)

        # Fix: look up the variant for *this* item instead of reusing the last one.
        for item_id, new_item_id in zip(item_ids, new_item_ids):
            item = next((item for item in order.items if item.item_id == item_id), None)
            if item is None:
                raise ValueError(f"Item {item_id} not found")
            variant = self._get_variant(item.product_id, new_item_id)
            item.item_id = new_item_id
            item.price = variant.price
            item.options = variant.options
        order.status = "pending (item modified)"
        return order

    modify_pending_order_items.__doc__ = RetailTools.modify_pending_order_items.__doc__
