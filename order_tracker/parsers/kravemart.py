"""Krave Mart grocery order receipts."""

from .base import TOTAL, Provider


class KraveMart(Provider):
    key = "kravemart"
    name = "Krave Mart"
    sender_terms = ("kravemart", "krave")
    total_labels = (
        r"grand\s+total",
        r"order\s+total",
        r"total\s+(?:amount|payable|bill|paid)",
        r"amount\s+(?:payable|paid)",
        TOTAL,
    )

    def describe(self, email, body, currency):
        return "Krave Mart", "Groceries"
