"""Budgets, how a month is going, what stands out, and expenses the user adds."""

import datetime as dt

import pandas as pd

from order_tracker.alerts import find_date, parse_message
from order_tracker.budgets import Budget, Limit, budget_for, pace
from order_tracker.insights import insights, place_key, place_name
from order_tracker.ledger import build_ledger
from order_tracker.models import Institution, Transaction
from order_tracker.money import money
from order_tracker.reconcile import reconcile
from order_tracker.storage import CASH, OrderStore

MEEZAN = Institution("meezan", "Meezan Bank", "bank", ["meezan"])
OCT = dt.date(2026, 10, 1)


def test_amounts_read_the_way_people_say_them():
    assert money(3119) == "Rs 3,119"
    assert money(253_000, short=True) == "Rs 2.53 lakh"
    assert money(100_000, short=True) == "Rs 1 lakh"
    assert money(12_500_000, short=True) == "Rs 1.25 crore"
    assert money(84_500, short=True) == "Rs 84,500"
    assert money(12.5, "USD") == "USD 12.50"
    assert money(12_900, "USD", short=True) == "USD 12.9K"
    assert money(-500) == "-Rs 500"


def test_a_budget_applies_from_its_month_and_before_the_first(tmp_path):
    store = OrderStore(tmp_path / "orders.db")
    store.save_budget("2026-09", Budget(100_000, [Limit("Coffee", 3000, words=["double shot"])]))
    store.save_budget("2026-12", Budget(150_000))
    saved = store.budgets()
    assert budget_for(saved, dt.date(2026, 6, 1)).total == 100_000  # before the first: the first
    assert budget_for(saved, dt.date(2026, 11, 1)).limits == [Limit("Coffee", 3000, "", ["double shot"])]
    assert budget_for(saved, dt.date(2027, 1, 1)) == Budget(150_000, [])
    assert budget_for({}, OCT) == Budget()

    store.save_budget("2026-12", Budget(None, [Limit("Petrol", 20_000, "Fuel")]))  # saved again: replaced
    assert store.budgets()["2026-12"] == Budget(None, [Limit("Petrol", 20_000, "Fuel", [])])


def test_pace_of_a_month():
    today = dt.date(2026, 10, 24)  # 7 days left
    over = pace(253_000, 150_000, OCT, today)
    assert (over.status, over.days_left, round(over.used, 2)) == ("over", 7, 1.69)
    heading = pace(130_000, 150_000, OCT, today)
    assert heading.status == "heading over" and round(heading.projected) == 167_917
    assert pace(60_000, 150_000, OCT, today).status == "on track"
    september = pace(90_000, 100_000, dt.date(2026, 9, 1), today)
    assert (september.status, september.days_left, september.per_day) == ("under", 0, 3000)
    assert pace(60_000, None, OCT, today).status == "none"


def spending(*rows) -> pd.DataFrame:
    """(date, description, category, amount) rows."""
    frame = pd.DataFrame(rows, columns=["date", "description", "category", "amount"])
    frame["date"] = pd.to_datetime(frame["date"])
    return frame


def coffee_months(per_month: dict[str, tuple[int, int]]) -> list[tuple]:
    """{month: (times, each)} of Double Shot visits, plus a steady 20,000 of groceries each month."""
    rows = []
    for month, (times, each) in per_month.items():
        rows.append((f"{month}-02", "IMTIAZ SUPER MARKET", "Groceries", 20_000))
        rows += [(f"{month}-{day + 3:02d}", "DOUBLE SHOT F-7", "Food", each) for day in range(times)]
    return rows


def test_a_coffee_habit_well_above_usual_stands_out():
    rows = spending(*coffee_months({"2026-07": (4, 700), "2026-08": (5, 700), "2026-09": (4, 700),
                                    "2026-10": (14, 700)}))
    found = insights(rows, OCT, dt.date(2026, 10, 24), Budget(), "PKR")
    first = found[0]
    assert (first.title, first.kind, first.key, first.level) == ("Double Shot F-7", "place", "double shot", "warning")
    assert first.text == "Rs 9,800 so far, 14 times: about 3× your usual Rs 3,033 a month."
    assert [i.title for i in found] == ["Double Shot F-7"]  # Food is up only because of it: said once


def test_a_category_up_across_places_stands_out():
    rows = [r for month in ("2026-08", "2026-09") for r in [
        (f"{month}-03", "KFC", "Food", 3000), (f"{month}-04", "HOMS", "Food", 3000), (f"{month}-05", "RENT", "Other", 90_000)]]
    rows += [("2026-10-03", "KFC", "Food", 4000), ("2026-10-04", "HOMS", "Food", 4000),
             ("2026-10-05", "CHEEZIOUS", "Food", 4000), ("2026-10-06", "RENT", "Other", 90_000)]
    found = insights(spending(*rows), OCT, dt.date(2026, 10, 24), Budget(), "PKR")
    assert [(i.title, i.text) for i in found] == [  # no one place stands out, but together they do
        ("Food", "Rs 12,000 so far, Rs 6,000 more than a usual month (Rs 6,000).")]


def test_a_frequent_place_is_a_habit_even_without_history():
    rows = spending(*coffee_months({"2026-10": (10, 700)}))
    found = insights(rows, OCT, dt.date(2026, 10, 24), Budget(), "PKR")
    assert [(i.title, i.level) for i in found] == [("Double Shot F-7", "info")]
    assert found[0].text == "10 times this month, Rs 7,000 in all (about Rs 700 each)."


def test_limits_over_or_heading_over_come_first():
    rows = spending(*coffee_months({"2026-09": (4, 700), "2026-10": (6, 700)}))
    budget = Budget(None, [Limit("Coffee", 3000, words=["double shot"]), Limit("Groceries", 30_000, "Groceries")])
    found = insights(rows, OCT, dt.date(2026, 10, 24), budget, "PKR")
    assert (found[0].title, found[0].level, found[0].kind, found[0].key) == ("Coffee", "critical", "limit", "0")
    assert found[0].text == "Rs 4,200 of your Rs 3,000 limit so far, Rs 1,200 over."
    assert "Groceries" not in {i.title for i in found}  # 20,000 of 30,000 with a week left is on track

    early = insights(rows, OCT, dt.date(2026, 10, 10), Budget(None, [Limit("Coffee", 6000, words=["double shot"])]),
                     "PKR")
    assert early[0].level == "warning" and early[0].text.startswith("Rs 4,200 of Rs 6,000 with 21 days to go.")


def test_places_group_their_spellings():
    assert place_key("DOUBLE SHOT F-7") == place_key("Double Shot") == "double shot"
    assert place_name(pd.Series(["DOUBLE SHOT F-7", "DOUBLE SHOT F-7", "Double Shot"])) == "Double Shot F-7"


def test_dates_in_bank_messages():
    assert find_date("debited on 23-Oct-2026 11:42 AM") == dt.datetime(2026, 10, 23, 11, 42)
    assert find_date("paid on 05/10/26 at 18:05") == dt.datetime(2026, 10, 5, 18, 5)
    assert find_date("Oct 21, 2026 9:15 pm") == dt.datetime(2026, 10, 21, 21, 15)
    assert find_date("on 2026-10-01") == dt.datetime(2026, 10, 1, 12)
    assert find_date("Rs 500 sent") is None


def test_a_pasted_message_is_stored_once(tmp_path):
    store = OrderStore(tmp_path / "orders.db")
    store.save_institution(MEEZAN)
    text = "PKR 3,119.00 debited from A/c **1234 at DOT LAHORE on 23-Oct-2026. Avl Bal PKR 50,000"
    when = dt.datetime(2026, 10, 23, 6, 42, tzinfo=dt.UTC)
    txn, reason = parse_message(text, MEEZAN, when)
    assert reason == "" and (txn.amount, txn.description, txn.source) == (3119, "DOT LAHORE", "message")
    assert store.add_typed(txn)
    assert not store.add_typed(parse_message(text, MEEZAN, when)[0])
    row = build_ledger(store).iloc[0]
    assert (row["came_from"], row["source"], row["counted"]) == ("Pasted message", "Meezan Bank", True)
    # The bank's email for the same payment arrives later: it isn't counted again.
    alert = Transaction("meezan", "meezan:FT1", when + dt.timedelta(hours=2), 3119, "PKR", "debit", "DOT LAHORE",
                        "Other", source="gmail")
    assert not store.add_transaction(alert)


def test_a_cash_expense_can_be_changed_and_removed(tmp_path):
    store = OrderStore(tmp_path / "orders.db")
    store.save_institution(MEEZAN)
    when = dt.datetime(2026, 10, 20, 7, tzinfo=dt.UTC)
    samosas = Transaction(CASH, "", when, 180, "PKR", "debit", "Samosas", "Food", source="manual")
    assert store.add_typed(samosas) and samosas.txn_key.startswith("cash:manual:")
    # A same-amount credit into the bank right after isn't a move between own accounts.
    store.add_transaction(Transaction("meezan", "meezan:in", when, 180, "PKR", "credit", "ALI", "Income"))
    reconcile(store)
    ledger = build_ledger(store).set_index("description")
    assert ledger.loc["Samosas", ["source", "kind", "came_from", "counted"]].tolist() == [
        "Cash", "Cash", "Added by you", True]

    store.update_typed(samosas.txn_key, when, 240, "Samosas and chai", CASH)
    store.set_item_detail(f"txn:{samosas.txn_key}", "note", "With Zain")
    assert build_ledger(store).set_index("description").loc["Samosas and chai", ["amount", "note"]].tolist() == [
        240, "With Zain"]
    assert store.already_tracked(Transaction(CASH, "", when, 240, "PKR", "debit", "x", "Food"))

    store.delete_typed(samosas.txn_key)
    store.delete_typed("meezan:in")  # only things the user added can be removed
    assert build_ledger(store)["description"].tolist() == ["ALI"]
    assert store.item_details().empty
