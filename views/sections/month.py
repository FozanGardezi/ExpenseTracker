"""Home → Overview: one month at a glance, like a budgeting app's home screen.

How much has gone out and per day, the month against the budget and its
limits, where it went, what to keep an eye on, and the latest payments.
Tapping a row opens it.
"""

import datetime as dt

import pandas as pd
import streamlit as st

from order_tracker.budgets import Budget, Limit, add_months, budget_for, month_key, pace
from order_tracker.insights import insights, months, place_key, place_name, usual
from order_tracker.ledger import build_ledger, spend_for_labels
from order_tracker.money import money
from order_tracker.storage import OrderStore
from views import dialogs
from views.common import (
    ACCENT, CHART_CONFIG, NEUTRAL, STATUS, card, category_colors, category_group, category_icon,
    donut, esc, flash, meter, theme_mode, viewer_timezone,
)
from views.components import level_color, payment_rows, tap_list, tint

STATUS_BADGES = {  # (label, icon, badge color)
    "over": ("Over budget", ":material/warning:", "red"),
    "heading over": ("Heading over", ":material/trending_up:", "orange"),
    "on track": ("On track", ":material/check_circle:", "green"),
    "under": ("Under budget", ":material/check_circle:", "green"),
}


def month_label(month: dt.date, today: dt.date) -> str:
    if month == today.replace(day=1):
        return "This month"
    if month == add_months(today, -1):
        return "Last month"
    return f"{month:%B %Y}"


def render(store: OrderStore) -> None:
    ledger = build_ledger(store)
    if ledger.empty:
        st.info("Your spending appears here after the first sync. You can also add an expense yourself.")
        return
    mode = theme_mode()
    tz = viewer_timezone()
    today = dt.datetime.now(tz).date()
    ledger["date"] = ledger["date"].dt.tz_convert(tz)
    ledger["month"] = months(ledger["date"])
    currencies = ledger["currency"].value_counts().index.tolist()
    labels = spend_for_labels(store)

    first = min(ledger["month"].min(), today.replace(day=1))
    choices = []
    while (month := add_months(today, -len(choices))) >= first:
        choices.append(month)
    f1, f2, f3 = st.columns([1.3, 1.2, 1], vertical_alignment="bottom")
    month = f1.selectbox("Month", choices, key="home_month", format_func=lambda m: month_label(m, today),
                         label_visibility="collapsed")
    spent_for = f2.segmented_control("For", ["All", *labels], default="All", key="home_for",
                                     label_visibility="collapsed", required=True)
    currency = currencies[0]
    if len(currencies) > 1:
        currency = f3.selectbox("Currency", currencies, key="home_currency", label_visibility="collapsed")

    view = ledger[ledger["currency"] == currency]
    colors = category_colors(view, mode)
    if spent_for != "All":
        view = view[view["spent_for"] == spent_for]
    spending = view[view["counted"] & (view["amount"] > 0)]
    this = spending[spending["month"] == month]
    in_month = view[view["month"] == month]
    budget = budget_for(store.budgets(), month)
    progress = pace(this["amount"].sum(), budget.total, month, today)

    left, right = st.columns(2, gap="medium")
    with left:
        _hero(this, spending, in_month, month, today, spent_for, progress, currency, labels)
        if spent_for == "All":
            _budget(store, progress, budget, spending, month, today, currency)
        if budget.limits:
            _limits(budget.limits, this, month, today, currency, colors)
    with right:
        _where_it_went(this, spending, month, colors, currency, mode)
    _keep_an_eye_on(spending, month, today, budget, currency, colors)
    _recent(in_month[~in_month["transfer"]], colors, today)


def _hero(this, spending, in_month, month, today, spent_for, progress, currency, labels) -> None:
    spent = this["amount"].sum()
    current = not progress.finished
    who = "" if spent_for == "All" else f" for {spent_for}"
    label = f"You've spent{who} so far this month" if current else f"You spent{who} in {month:%B %Y}"
    sub = f"That's about <b>{esc(money(progress.per_day, currency))}</b> a day."
    if not current:
        before = spending.loc[spending["month"] == add_months(month, -1), "amount"].sum()
        if before:
            change = spent - before
            sub += (f" <b>{esc(money(abs(change), currency))} {'more' if change > 0 else 'less'}</b> "
                    f"than {add_months(month, -1):%B}.")
    received = -in_month.loc[in_month["counted"] & (in_month["amount"] < 0), "amount"].sum()
    with card("hero"):
        st.html(f'<div class="hero-label">{esc(label)}</div>'
                f'<div class="hero-value">{esc(money(spent, currency, short=True))}</div>'
                f'<div class="hero-sub">{sub}</div>')
        split = this.groupby("spent_for")["amount"].sum().reindex(labels).dropna()
        if spent_for == "All" and len(split) > 1:
            st.caption(" · ".join(f"{label} {money(amount, currency)}" for label, amount in split.items()))
        if received and spent_for == "All":
            st.caption(f"{money(received, currency)} came in{' this month' if current else ''}: income and refunds.")
        not_counted = in_month[~in_month["counted"] & ~in_month["transfer"] & (in_month["amount"] > 0)]["amount"].sum()
        if not_counted:
            st.caption(f"{money(not_counted, currency)} sent by transfer isn't counted as spending.")
            st.page_link("views/activity.py", query_params={"activity": "Transfers"},
                         icon=":material/swap_horiz:", label="Review transfers")


def _budget(store, progress, budget, spending, month, today, currency) -> None:
    with card("budget"):
        if not budget.total:
            st.html(f'<p class="card-title">{month:%B} budget</p>')
            st.caption("Set how much you want to spend in a month, and see how you're doing as it goes.")
            with st.form("home_budget", border=False):
                amount_col, save_col = st.columns([2, 1], vertical_alignment="bottom")
                usual_month = usual(spending.assign(all="all"), today.replace(day=1), "all").get("all", 0.0)
                amount = amount_col.number_input(
                    "Monthly budget", min_value=0.0, step=5000.0, format="%.0f", value=None, placeholder="Amount",
                    help=f"Your usual month is about {money(usual_month, currency)}." if usual_month else None)
                if save_col.form_submit_button("Set budget", type="primary", width="stretch") and amount:
                    store.save_budget(month_key(today), Budget(amount, budget.limits))
                    flash(f"Budget set: {money(amount, currency)} a month.")
                    st.rerun()
            return
        label, icon, color = STATUS_BADGES[progress.status]
        with st.container(horizontal=True, vertical_alignment="center"):
            st.html(f'<p class="card-title">{month:%B} budget</p>')
            st.space("stretch")
            st.badge(label, icon=icon, color=color)
        fill = {"over": STATUS["critical"], "heading over": STATUS["warning"]}.get(progress.status, ACCENT)
        remaining = f"{progress.days_left} days remaining" if progress.days_left else f"{progress.days} days"
        st.html(meter(progress.used, fill) + f'<div class="meter-legend"><span>{progress.used:.0%} used</span>'
                f'<span>{remaining}</span></div>')
        st.markdown(_budget_sentence(progress, currency))
        with st.expander("See how we worked this out"):
            st.markdown(
                f"- **Spent:** {money(progress.spent, currency)} of your {money(progress.budget, currency)} budget. "
                "It counts payments from your bank and wallet emails, statements, delivery receipts and what you "
                "added, each once. Moves between your own accounts, and transfers you haven't marked as "
                "spending, aren't counted.\n"
                f"- **Per day:** {money(progress.per_day, currency)} over {progress.elapsed} of "
                f"{progress.days} days."
                + (f"\n- **At this pace** the month ends near {money(progress.projected, currency)}."
                   if not progress.finished else "")
                + "\n- Change the budget under **Budget** above."
            )


def _budget_sentence(progress, currency) -> str:
    left = money(abs(progress.left), currency, short=True)
    if progress.status == "over":
        return f"You're **{left}** past your budget."
    if progress.status == "under":
        return f"You stayed **{left}** under budget."
    per_day = money(progress.left / max(progress.days_left, 1), currency)
    if progress.status == "heading over":
        return (f"**{left}** left. At this pace you'll spend about "
                f"**{money(progress.projected, currency, short=True)}**; {per_day} a day keeps you on budget.")
    return f"**{left}** left: about **{per_day}** a day for the {progress.days_left} days to go."


def _limits(limits: list[Limit], this, month, today, currency, colors) -> None:
    rows = []
    for position, limit in enumerate(limits):
        covered = this[limit.matches(this)]
        progress = pace(covered["amount"].sum(), limit.amount, month, today)
        fill = {"over": STATUS["critical"], "heading over": STATUS["warning"]}.get(progress.status, ACCENT)
        category = limit.category or (covered["category"].mode().iloc[0] if not covered.empty else "")
        state = (f"{money(-progress.left, currency)} over" if progress.status == "over"
                 else f"{money(progress.left, currency)} left")
        rows.append({
            "id": f"limit:{position}", "title": limit.name, "sub": state, "icon": category_icon(category),
            "amount": money(progress.spent, currency), "meta": f"of {money(limit.amount, currency)}",
            "meter": {"share": progress.used or 0, "color": fill},
            **tint(colors.get(category, NEUTRAL[theme_mode()])),
        })
    with card("limits"):
        st.html('<p class="card-title">Limits</p>')
        picked = tap_list(rows, key="home_limits")
    if picked:
        limit = limits[int(picked.split(":")[1])]
        covered = this[limit.matches(this)]
        dialogs.open_payments(limit.name, f"{month:%B %Y} · {len(covered)} payments · "
                              f"{money(covered['amount'].sum(), currency)} of {money(limit.amount, currency)}",
                              list(covered["item"]), colors)


def _where_it_went(this, spending, month, colors, currency, mode) -> None:
    with card("where"):
        by_category = this.groupby("category")["amount"].sum().sort_values(ascending=False)
        with st.container(horizontal=True, vertical_alignment="center"):
            st.html('<p class="card-title">Where it went</p>')
            st.space("stretch")
            if len(by_category):
                st.badge(f"{len(by_category)} {'category' if len(by_category) == 1 else 'categories'}", color="gray")
        if by_category.empty:
            st.caption("Nothing spent yet.")
            return
        st.plotly_chart(donut(by_category, colors, currency, mode), theme=None, config=CHART_CONFIG,
                        key="home_donut")
        before = usual(spending, month, "category")
        total = by_category.sum()
        # A month still going is only compared once it has passed the usual, not while it's catching up.
        going = month == dt.datetime.now(viewer_timezone()).date().replace(day=1)
        rows = []
        for category, amount in by_category.items():
            count = int((this["category"] == category).sum())
            sub = f"{count} {'payment' if count == 1 else 'payments'}"
            was = before.get(category)
            if was is not None:
                change = amount - was
                if abs(change) < 0.1 * max(was, 1):
                    sub += "" if going else " · about usual"
                elif change > 0 or not going:
                    sub += f" · {money(abs(change), currency, short=True)} {'above' if change > 0 else 'below'} usual"
            color = colors.get(category_group(category, colors), NEUTRAL[mode])
            rows.append({"id": f"category:{category}", "title": category, "icon": category_icon(category),
                         "sub": sub, "amount": money(amount, currency), "meta": f"{amount / total:.0%}",
                         **tint(color)})
        picked = tap_list(rows, key="home_categories")
    if picked:
        category = picked.split(":", 1)[1]
        rows = this[this["category"] == category]
        dialogs.open_payments(category, f"{month:%B %Y} · {len(rows)} payments · {money(rows['amount'].sum(), currency)}",
                              list(rows["item"]), colors, limit=Limit(category, 0, category),
                              suggested=round(before.get(category, 0) / 500) * 500)


def _keep_an_eye_on(spending, month, today, budget, currency, colors) -> None:
    found = insights(spending, month, today, budget, currency)[:5]
    mode = theme_mode()
    with card("eye"):
        st.html('<p class="card-title">Keep an eye on</p>')
        if not found:
            st.caption("Nothing stands out" + (" so far this month." if month == today.replace(day=1) else ".")
                       + " Places you pay often, or far more than usual, show up here.")
            return
        rows = [{"id": f"{i.kind}:{i.key}", "title": i.title, "sub": i.text, "wrap": True,
                 "icon": category_icon(i.category), "level": level_color(i.level),
                 **tint(colors.get(category_group(i.category, colors), NEUTRAL[mode]))} for i in found]
        picked = tap_list(rows, key="home_insights")
        st.caption("Compared with your usual month: the average of up to three months before.")
    if not picked:
        return
    kind, key = picked.split(":", 1)
    this = spending[spending["month"] == month]
    if kind == "limit":
        limit = budget.limits[int(key)]
        rows, title, offer = this[limit.matches(this)], limit.name, None
    elif kind == "place":
        rows = this[this["description"].map(place_key) == key]
        title = place_name(rows["description"])
        offer = Limit(title, 0, words=[key])
    else:
        rows, title, offer = this[this["category"] == key], key, Limit(key, 0, key)
    history = spending[spending["month"] < month]
    usual_amount = 0.0
    if offer is not None:
        matched = history[offer.matches(history)].assign(all="all")
        usual_amount = float(usual(matched, month, "all").get("all", 0.0)) if not matched.empty else 0.0
    dialogs.open_payments(title, f"{month:%B %Y} · {len(rows)} payments · {money(rows['amount'].sum(), currency)}",
                          list(rows["item"]), colors, limit=offer, suggested=round(usual_amount / 500) * 500)


def _recent(rows: pd.DataFrame, colors, today) -> None:
    with card("recent"):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.html('<p class="card-title">Latest</p>')
            st.space("stretch")
            st.page_link("views/activity.py", label="See all", icon=":material/arrow_forward:")
        picked = tap_list(payment_rows(rows.head(8), colors, today), key="home_recent",
                          empty="Nothing this month yet.")
    if picked:
        dialogs.open_sheet("payment", picked)

