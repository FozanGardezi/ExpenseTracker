"""How amounts are written: "Rs 3,119", or "Rs 2.53 lakh" where space is short."""

SYMBOLS = {"PKR": "Rs"}


def symbol(currency: str) -> str:
    return SYMBOLS.get(currency, currency)


def _trim(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def money(amount: float, currency: str = "PKR", short: bool = False) -> str:
    """Rupees in whole numbers, other currencies with cents. `short` writes big rupee
    amounts in lakh and crore, as people in Pakistan say them, and others as 12.9K / 4.2M."""
    sign = "-" if amount < 0 else ""
    value = abs(amount)
    if short:
        sizes = ((1e7, " crore"), (1e5, " lakh")) if currency == "PKR" else ((1e9, "B"), (1e6, "M"), (1e4, "K"))
        for size, word in sizes:
            if value >= size:
                divisor = 1e3 if word == "K" else size
                return f"{sign}{symbol(currency)} {_trim(value / divisor)}{word}"
    decimals = 0 if currency == "PKR" or value >= 1000 else 2
    return f"{sign}{symbol(currency)} {value:,.{decimals}f}"
