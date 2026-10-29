"""Foodpanda receipts (Pakistan and Bangladesh).

Formats follow https://github.com/fasi96/FoodpandaExpenseTracker:
  Pakistan    "Partner: Name: <restaurant>" ... "Total ... PKR 1,884.99"
  Bangladesh  "Store <restaurant>" ... "Order Total Tk 571.90"
Receipts without a partner/store name are pandamart grocery orders.
"""

import re

from .base import TOTAL, Provider

_PARTNER = re.compile(r"Partner:\s*Name:\s*(.+)")
_STORE = re.compile(r"Store\s+([^\n<]+)")


class Foodpanda(Provider):
    key = "foodpanda"
    name = "Foodpanda"
    sender_terms = ("foodpanda",)
    # "Received ... Rs." is the older Pakistan format.
    total_labels = (r"order\s+total", r"grand\s+total", TOTAL, r"received")

    def describe(self, email, body, currency):
        match = _PARTNER.search(body)
        if not match and currency == "BDT":
            match = _STORE.search(body)
        merchant = match.group(1).strip() if match else "pandamart"
        lowered = merchant.lower()
        category = "Groceries" if "pandamart" in lowered or "panda mart" in lowered else "Food"
        return merchant, category
