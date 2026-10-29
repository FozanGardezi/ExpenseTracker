"""Spending categories, guessed from the merchant or payee text of a transaction.

The user can change any category on the Transactions page; these rules only
pick the starting value.
"""

import re

# Checked in order; the first rule with a matching keyword wins. Keywords match
# whole words, so "jazz" does not match "jazzcash" and "fee" not "coffee".
_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Food", ("foodpanda", "food panda", "careem food", "kfc", "mcdonalds", "mcdonald's", "dominos",
              "pizza", "burger", "restaurant", "cafe", "coffee", "bakery", "cheezious",
              # what people type for an expense they add themselves
              "samosa", "samosas", "roti", "naan", "paratha", "biryani", "karahi", "tikka", "shawarma",
              "chai", "tea", "coke", "pepsi", "juice", "snacks", "lunch", "dinner", "breakfast")),
    ("Groceries", ("krave", "krave mart", "pandamart", "imtiaz", "carrefour", "al-fatah", "alfatah",
                   "metro cash", "naheed", "chase up", "grocery", "grocer", "supermarket")),
    ("Ride", ("careem", "indrive", "indriver", "uber", "bykea", "yango")),
    ("Fuel", ("pso", "pakistan state oil", "shell", "total", "totalenergies", "total parco", "attock petroleum",
              "hascol", "byco", "petrol", "fuel", "filling station", "petroleum")),
    ("Bills & utilities", ("k-electric", "kelectric", "lesco", "iesco", "mepco", "fesco", "pesco",
                           "gepco", "hesco", "ssgc", "sngpl", "sui gas", "wasa", "electricity",
                           "utility", "bill payment")),
    ("Mobile & internet", ("jazz", "zong", "telenor", "ufone", "ptcl", "nayatel", "stormfiber",
                           "storm fiber", "wateen", "mobile top-up", "topup", "top-up", "mobile load")),
    ("Subscriptions", ("netflix", "spotify", "youtube", "google", "apple.com", "itunes", "icloud",
                       "microsoft", "adobe", "openai", "chatgpt", "anthropic", "canva", "linkedin")),
    ("Shopping", ("daraz", "amazon", "aliexpress", "temu", "outfitters", "khaadi", "sapphire", "gul ahmed")),
    ("Health", ("pharmacy", "hospital", "clinic", "laboratory", "dawaai", "medical")),
    ("Education", ("school", "university", "college", "tuition", "coursera", "udemy")),
    ("Cash withdrawal", ("atm", "cash withdrawal")),
    ("Fees & charges", ("fee", "fees", "charges", "excise", "fed", "withholding tax")),
    ("Transfers", ("jazzcash", "easypaisa", "nayapay", "sadapay", "raast", "ibft", "funds transfer",
                   "fund transfer", "transfer")),
]
_COMPILED = [
    (category, re.compile(r"\b(?:" + "|".join(map(re.escape, words)) + r")\b"))
    for category, words in _RULES
]
_REFUND = re.compile(r"\b(?:refund|refunded|reversal|reversed|cash ?back)\b")
# "Total" is a fuel company (TotalEnergies PARCO) but also an everyday word.
_TOTAL_PHRASE = re.compile(r"\btotal\s+(?:amount|due|bill|payable|balance|outstanding|charges|of)\b")

ALL_CATEGORIES = [
    "Food", "Groceries", "Ride", "Delivery", "Fuel", "Bills & utilities", "Mobile & internet",
    "Subscriptions", "Shopping", "Health", "Education", "Cash withdrawal", "Fees & charges",
    "Transfers", "Income", "Refunds", "Other",
]


def categorize(text: str, direction: str) -> str:
    lowered = _TOTAL_PHRASE.sub(" ", text.lower())
    if direction == "credit":
        return "Refunds" if _REFUND.search(lowered) else "Income"
    for category, pattern in _COMPILED:
        if pattern.search(lowered):
            return category
    return "Other"
