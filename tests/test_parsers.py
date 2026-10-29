"""Parser tests on synthetic emails.

The Foodpanda samples follow the formats handled by the reference project
(fasi96/FoodpandaExpenseTracker). The Careem, inDrive and Krave Mart samples
are representative layouts, not captured real emails: when a real receipt is
skipped, add it here (with personal details removed) and tune the parser.
"""

import base64
import datetime as dt

import pytest

from order_tracker.email_utils import extract_bodies, html_to_text
from order_tracker.models import Email
from order_tracker.parsers import PROVIDERS
from order_tracker.parsers.base import find_order_ref, find_total, TOTAL

WHEN = dt.datetime(2026, 3, 14, 12, 30, tzinfo=dt.UTC)


def email(body: str, subject: str = "Your receipt", message_id: str = "m1") -> Email:
    return Email(message_id, "Service <noreply@example.com>", subject, WHEN, [body])


def parse(provider: str, body: str, subject: str = "Your receipt", message_id: str = "m1"):
    return PROVIDERS[provider].parse(email(body, subject, message_id))


# --- shared amount extraction ---

@pytest.mark.parametrize(
    "text, expected",
    [
        ("Total PKR 1,884.99", (1884.99, "PKR")),
        ("Total:\nRs. 450", (450.0, "PKR")),
        ("Total\nPKR\n2,031.49", (2031.49, "PKR")),
        ("Total 1,250 PKR", (1250.0, "PKR")),
        ("Total AED 32.50", (32.5, "AED")),
        ("Order Total Tk 571.90", (571.9, "BDT")),
    ],
)
def test_find_total_formats(text, expected):
    assert find_total(text, (r"order\s+total", TOTAL)) == expected


def test_find_total_ignores_subtotal_and_savings():
    text = "Subtotal Rs. 800\nTotal savings Rs. 200\nDelivery Rs. 100\nTotal Rs. 900"
    assert find_total(text, (TOTAL,)) == (900.0, "PKR")


def test_find_total_needs_a_currency():
    assert find_total("Total items 3\nOrder 12345", (TOTAL,)) is None


def test_find_order_ref_requires_a_digit():
    assert find_order_ref("Order number: x7kq-p3m9") == "X7KQ-P3M9"
    assert find_order_ref("Order details below. Booking confirmed.") is None


# --- Foodpanda ---

FOODPANDA_PK = """Thanks for your order!
Order number: o2wq-9x1k
Partner:
Name: Homs
Subtotal PKR 1,700.00
Delivery fee PKR 184.99
Total (incl. GST) PKR 1,884.99
"""


def test_foodpanda_pakistan_receipt():
    order, reason = parse("foodpanda", FOODPANDA_PK)
    assert reason == ""
    assert (order.amount, order.currency) == (1884.99, "PKR")
    assert (order.merchant, order.category) == ("Homs", "Food")
    assert order.order_key == "foodpanda:O2WQ-9X1K"
    assert order.order_date == WHEN


def test_foodpanda_bangladesh_receipt():
    body = "Store Falafel House\nItems\nOrder Total Tk 571.90\n"
    order, _ = parse("foodpanda", body, subject="Your order has been placed")
    assert (order.amount, order.currency, order.merchant) == (571.9, "BDT", "Falafel House")


def test_foodpanda_pandamart_when_no_partner():
    order, _ = parse("foodpanda", "Your pandamart order\nTotal PKR 2,450.00")
    assert (order.merchant, order.category) == ("pandamart", "Groceries")


def test_foodpanda_refund_is_negative_and_kept_apart_from_the_order():
    order, _ = parse("foodpanda", FOODPANDA_PK)
    refund, _ = parse("foodpanda", FOODPANDA_PK, subject="Your refund has been processed", message_id="m2")
    assert refund.amount == -1884.99
    assert refund.order_key != order.order_key


def test_cancelled_and_promo_emails_are_skipped():
    order, reason = parse("foodpanda", FOODPANDA_PK, subject="Your order has been cancelled")
    assert order is None and "cancellation" in reason
    order, reason = parse("foodpanda", "Get 50% off pizzas this weekend!", subject="Weekend deals")
    assert order is None


def test_promo_without_total_is_skipped():
    order, reason = parse("foodpanda", "Hungry? Burgers from Rs. 299 near you.", subject="New near you")
    assert order is None and reason == "no order total found"


# --- Careem ---

CAREEM_RIDE_HTML = """<html><head><style>td{color:red}</style></head><body>
<table>
<tr><td>Thanks for riding with Careem</td></tr>
<tr><td>Booking ID</td><td>B-48213377</td></tr>
<tr><td>Captain</td><td>Ali</td></tr>
<tr><td>Pick-up</td><td>DHA Phase 6</td></tr>
<tr><td>Drop-off</td><td>Clifton Block 5</td></tr>
<tr><td>Distance</td><td>8.2 km</td></tr>
<tr><td>Total</td><td>PKR&nbsp;612.00</td></tr>
</table></body></html>"""


def test_careem_ride_receipt_from_html():
    order, _ = parse("careem", html_to_text(CAREEM_RIDE_HTML), subject="Your Careem trip receipt")
    assert (order.amount, order.currency) == (612.0, "PKR")
    assert (order.merchant, order.category) == ("Careem Ride", "Ride")
    assert order.order_key == "careem:B-48213377"


def test_careem_food_receipt():
    body = "Order from Kolachi\nSubtotal AED 58.00\nTotal paid AED 64.50"
    order, _ = parse("careem", body, subject="Your Careem Food order receipt")
    assert (order.amount, order.currency, order.category) == (64.5, "AED", "Food")


# --- inDrive ---

def test_indrive_city_trip():
    body = "Trip details\nFrom: Gulberg\nTo: Johar Town\nTrip cost: Rs 620"
    order, _ = parse("indrive", body, subject="Your inDrive trip")
    assert (order.amount, order.merchant, order.category) == (620.0, "inDrive City", "Ride")


def test_indrive_intercity_trip():
    order, _ = parse("indrive", "Intercity ride Lahore - Islamabad\nPrice PKR 9,500")
    assert (order.amount, order.merchant) == (9500.0, "inDrive Intercity")


# --- Krave Mart ---

def test_kravemart_order():
    body = "Order #KM104552\nMilk x2 Rs. 560\nDelivery Rs. 0\nGrand Total Rs. 1,250"
    order, _ = parse("kravemart", body, subject="Your Krave Mart order is confirmed")
    assert (order.amount, order.category, order.order_key) == (1250.0, "Groceries", "kravemart:KM104552")


# --- Gmail payload decoding ---

def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def test_extract_bodies_walks_nested_parts_plain_first():
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "parts": [
                    {"mimeType": "text/html", "body": {"data": _b64("<p>Total</p><p>PKR 10</p>")}},
                    {"mimeType": "text/plain", "body": {"data": _b64("Total PKR 10")}},
                ],
            },
            {"mimeType": "image/png", "body": {"attachmentId": "x"}},
        ],
    }
    assert extract_bodies(payload) == ["Total PKR 10", "Total\nPKR 10"]


def test_extract_bodies_handles_single_part_message():
    payload = {"mimeType": "text/plain", "body": {"data": _b64("Total\r\n\r\nRs. 99")}}
    assert extract_bodies(payload) == ["Total\nRs. 99"]
