"""The user's rules, who spending was for, notes and the "In spending" tick."""

import datetime as dt

from order_tracker.ledger import build_ledger, category_options, set_my_categories, set_spend_for_labels
from order_tracker.models import Institution, Transaction
from order_tracker.rules import Rule
from order_tracker.storage import OrderStore

T0 = dt.datetime(2026, 10, 1, 12, 0, tzinfo=dt.UTC)
MEEZAN = Institution("meezan", "Meezan Bank", "bank", ["meezan"])


def make_store(tmp_path, *txns) -> OrderStore:
    store = OrderStore(tmp_path / "orders.db")
    store.save_institution(MEEZAN)
    for i, (description, amount, category, *direction) in enumerate(txns):
        store.add_transaction(Transaction(
            "meezan", f"meezan:{i}", T0 + dt.timedelta(hours=i), amount, "PKR",
            direction[0] if direction else "debit", description, category,
        ))
    return store


def by_description(store, column):
    ledger = build_ledger(store)
    return dict(zip(ledger["description"], ledger[column]))


def test_a_big_shop_and_a_small_one_at_the_same_store(tmp_path):
    store = make_store(tmp_path, ("EURO STORE F-7", 7889, "Other"), ("EURO STORE F-7 ", 180, "Other"))
    store.save_rules([
        Rule(["euro store"], category="Food", spent_for="Mine"),
        Rule(["euro store"], min_amount=5000, category="Groceries", spent_for="Home"),  # more specific: wins
    ])
    ledger = build_ledger(store).set_index("amount")
    assert ledger.loc[7889, ["category", "spent_for"]].tolist() == ["Groceries", "Home"]
    assert ledger.loc[180, ["category", "spent_for"]].tolist() == ["Food", "Mine"]
    assert (ledger["auto_category"] == "Other").all()


def test_words_match_whole_words_ignoring_case(tmp_path):
    store = make_store(tmp_path, ("pso-0231 islamabad", 2706, "Other"), ("EPSOM SALTS", 300, "Other"))
    store.save_rules([Rule(["PSO"], category="Fuel")])
    categories = by_description(store, "category")
    assert categories["pso-0231 islamabad"] == "Fuel"
    assert categories["EPSOM SALTS"] == "Other"


def test_on_a_tie_the_first_rule_wins(tmp_path):
    store = make_store(tmp_path, ("ZAIN AHMED", 5000, "Transfers"))
    store.save_rules([Rule(["zain"], category="Going out"), Rule(["ahmed"], category="Gifts")])
    assert by_description(store, "category")["ZAIN AHMED"] == "Going out"


def test_for_rules_follow_the_final_category(tmp_path):
    store = make_store(tmp_path, ("K-ELECTRIC", 11000, "Bills & utilities"), ("KITCHEN CUISINE", 200, "Food"))
    store.save_rules([Rule(category_is="Bills & utilities", spent_for="Home")])
    store.set_category("txn:meezan:1", "Bills & utilities")  # picked by hand, then the rule applies
    assert by_description(store, "spent_for") == {"K-ELECTRIC": "Home", "KITCHEN CUISINE": "Home"}


def test_choices_on_one_transaction_beat_rules(tmp_path):
    store = make_store(tmp_path, ("EURO STORE", 7889, "Groceries"))
    store.save_rules([Rule(["euro store"], category="Groceries", spent_for="Home")])
    store.set_category("txn:meezan:0", "Shopping")
    store.set_item_detail("txn:meezan:0", "spent_for", "Mine")
    store.set_item_detail("txn:meezan:0", "note", "Extra for shirts (from gas bill)")
    row = build_ledger(store).iloc[0]
    assert (row["category"], row["spent_for"], row["note"]) == ("Shopping", "Mine", "Extra for shirts (from gas bill)")

    store.set_item_detail("txn:meezan:0", "spent_for", None)  # cleared: back to the rule
    assert build_ledger(store).iloc[0]["spent_for"] == "Home"


def test_spending_is_for_the_first_label_until_told_otherwise(tmp_path):
    store = make_store(tmp_path, ("SAMOSA HOUSE", 180, "Food"), ("ACME LTD", 50000, "Income", "credit"))
    assert by_description(store, "spent_for") == {"SAMOSA HOUSE": "Mine", "ACME LTD": ""}  # money in has none
    set_spend_for_labels(store, ["Me", "Family", "Office"])
    assert by_description(store, "spent_for")["SAMOSA HOUSE"] == "Me"


def test_rules_leave_money_in_and_own_account_moves_alone(tmp_path):
    store = make_store(tmp_path, ("PSO CASHBACK", 100, "Refunds", "credit"))
    store.save_rules([Rule(["pso"], category="Fuel")])
    assert by_description(store, "category")["PSO CASHBACK"] == "Refunds"


def test_ticking_in_spending_counts_a_transfer(tmp_path):
    store = make_store(tmp_path, ("ZAIN", 5000, "Transfers"), ("SHOP", 300, "Food"))
    assert by_description(store, "counted") == {"ZAIN": False, "SHOP": True}
    store.set_item_detail("txn:meezan:0", "counted", True)
    store.set_item_detail("txn:meezan:1", "counted", False)
    assert by_description(store, "counted") == {"ZAIN": True, "SHOP": False}


def test_a_rule_category_counts_a_transfer(tmp_path):
    store = make_store(tmp_path, ("ZAIN", 5000, "Transfers"))
    store.save_rules([Rule(["zain"], category="Going out", spent_for="Mine")])
    row = build_ledger(store).iloc[0]
    assert (row["category"], row["auto_category"], row["counted"]) == ("Going out", "Transfers", True)


def test_older_rows_get_newer_built_in_categories(tmp_path):
    store = make_store(tmp_path, ("TOTAL PARCO F/S", 2706, "Other"))  # stored before "total" was known
    assert by_description(store, "category")["TOTAL PARCO F/S"] == "Fuel"


def test_rules_are_saved_in_order(tmp_path):
    store = OrderStore(tmp_path / "orders.db")
    rules = [Rule(["euro store"], min_amount=5000, category="Groceries", spent_for="Home"),
             Rule(category_is="Bills & utilities", max_amount=20000, spent_for="Home")]
    store.save_rules(rules)
    assert store.rules() == rules
    assert not Rule(["pso"]).is_complete() and not Rule(category="Fuel").is_complete()


def test_own_categories_are_offered_everywhere(tmp_path):
    store = OrderStore(tmp_path / "orders.db")
    set_my_categories(store, ["Going out", "Clothes"])
    options = category_options(store, "Pets")
    assert {"Going out", "Clothes", "Pets", "Fuel"} <= set(options)
