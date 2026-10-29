"""Bank and wallet alert parsing.

These alerts are representative of the wording Pakistani banks and wallets
use, written for the tests; they are not captured real emails. When a real
alert is skipped or misread, add it here (with personal details removed).
"""

import datetime as dt

import pytest

from order_tracker.alerts import parse_alert
from order_tracker.categories import categorize
from order_tracker.models import Email, Institution

WHEN = dt.datetime(2026, 9, 1, 15, 16, tzinfo=dt.UTC)
BANK = Institution("meezan", "Meezan Bank", "bank", ["meezan"])
WALLET = Institution("jazzcash", "JazzCash", "wallet", ["jazzcash"])


def parse(body: str, subject: str = "Transaction Alert", institution=BANK, message_id="m1"):
    return parse_alert(Email(message_id, "Bank <alerts@bank.com>", subject, WHEN, [body]), institution)


def test_debit_card_purchase_ignores_balance():
    txn, reason = parse(
        "Dear Customer, PKR 1,884.99 has been debited from your A/C ****1234 via Debit Card at "
        "FOODPANDA PK on 01-Sep-26 20:16. Avl Bal PKR 52,310.00. Ref No. 624412345678"
    )
    assert reason == ""
    assert (txn.amount, txn.currency, txn.direction) == (1884.99, "PKR", "debit")
    assert txn.description == "FOODPANDA PK"
    assert (txn.reference, txn.account_hint) == ("624412345678", "1234")
    assert txn.txn_key == "meezan:624412345678"
    assert txn.category == "Food"
    assert txn.txn_date == WHEN


def test_incoming_transfer_is_income():
    txn, _ = parse(
        "Your account XXXXXX5678 has been credited with Rs. 25,000.00 from MUHAMMAD ALI via IBFT "
        "on 02/09/2026. Available balance Rs. 77,310.00",
        subject="Funds Received",
    )
    assert (txn.amount, txn.direction, txn.description, txn.category) == (25000.0, "credit", "MUHAMMAD ALI", "Income")
    assert txn.txn_key == "meezan:msg:m1"  # no reference number in this alert


def test_wallet_send_money():
    txn, _ = parse(
        "You have sent Rs. 2,000 to Ahmed Khan (0300xxxx123). TID: 81234567890. "
        "Your new balance is Rs. 1,500.",
        subject="Money Sent", institution=WALLET,
    )
    assert (txn.amount, txn.direction, txn.description) == (2000.0, "debit", "Ahmed Khan")
    assert txn.txn_key == "jazzcash:81234567890"
    assert txn.category == "Transfers"  # money sent to a person, not a known merchant


def test_credit_card_purchase_is_a_debit():
    txn, _ = parse(
        "Your Credit Card ending 4321 was used for USD 20.00 at OPENAI *CHATGPT SUBSCR on 03-Sep-2026.",
        subject="Credit Card Transaction Alert",
    )
    assert (txn.amount, txn.currency, txn.direction) == (20.0, "USD", "debit")
    assert txn.description == "OPENAI *CHATGPT SUBSCR"
    assert (txn.category, txn.account_hint) == ("Subscriptions", "4321")


def test_amount_without_currency_uses_the_institution_default():
    txn, _ = parse("Amount: 1,250.00\nTransaction Type: Debit\nMerchant: K-ELECTRIC\n")
    assert (txn.amount, txn.currency, txn.direction) == (1250.0, "PKR", "debit")
    assert (txn.description, txn.category) == ("K-ELECTRIC", "Bills & utilities")


def test_refund_credit():
    txn, _ = parse("PKR 1,884.99 has been credited to your account as refund from FOODPANDA.")
    assert (txn.direction, txn.category) == ("credit", "Refunds")


def test_footer_does_not_change_direction():
    filler = "Thank you for banking with us. " * 10
    txn, _ = parse(f"You have paid Rs. 500 to K-Electric.\n{filler}\nEarn 10% cashback on your next bill!")
    assert txn.direction == "debit"


@pytest.mark.parametrize("subject", [
    "Your OTP for login", "Your e-Statement for August", "Transaction declined",
    "Exclusive offer: 20% off",
])
def test_non_transaction_subjects_are_skipped(subject):
    txn, reason = parse("PKR 500 debited from your account.", subject=subject)
    assert txn is None and reason


def test_alert_without_direction_is_skipped():
    txn, reason = parse("Spend PKR 5,000 this weekend and win a trip!", subject="Win big")
    assert txn is None and reason == "could not tell whether money went out or came in"


def test_email_without_amount_is_skipped():
    txn, reason = parse("Your card has been dispatched.", subject="Card update")
    assert txn is None and reason == "no transaction amount found"


@pytest.mark.parametrize("text, direction, expected", [
    ("POS purchase at CARREFOUR LAHORE", "debit", "Groceries"),
    ("Payment to JAZZCASH", "debit", "Transfers"),
    ("Jazz prepaid load", "debit", "Mobile & internet"),
    ("ATM cash withdrawal", "debit", "Cash withdrawal"),
    ("Starbucks coffee", "debit", "Food"),
    ("Something unknown", "debit", "Other"),
    ("TOTAL PARCO F/S 112", "debit", "Fuel"),
    ("PSO-0231 BLUE AREA", "debit", "Fuel"),
    ("Total amount due", "debit", "Other"),
    ("Samosas", "debit", "Food"),  # typed in by the user
    ("Chicken Karahi", "debit", "Food"),
    ("CD 70 Petrol", "debit", "Fuel"),
    ("Salary September", "credit", "Income"),
])
def test_categorize(text, direction, expected):
    assert categorize(text, direction) == expected
