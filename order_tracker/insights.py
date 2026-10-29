"""What stands out in a month's spending: limits gone over (or about to be),
places and categories well above their usual, and habits (a place paid again
and again, like a coffee shop).

"Usual" is the average month over up to three months before the one shown,
counting only months since the user's history starts. A month still in
progress is compared as it stands, so it only shows up once it has already
passed a usual month.

Each thing is said once: a place isn't listed again under a limit that's
already flagged for it, nor a category whose rise is mostly one listed place.
"""

import datetime as dt
import re
from dataclasses import dataclass

import pandas as pd

from .budgets import Budget, add_months, pace
from .money import money

HISTORY_MONTHS = 3
HABIT_TIMES = 8      # paying the same place this often in a month is a habit worth a look
PLACE_SHARE = 0.02   # a place stands out once it's this share of a usual month above its usual
CATEGORY_SHARE = 0.04
LEVELS = ("critical", "warning", "info")


@dataclass
class Insight:
    title: str
    text: str
    level: str      # "critical": over a limit; "warning": above usual or heading over; "info": a habit
    category: str   # for the icon
    kind: str       # what `key` names: "limit" (its position), "place" or "category"
    key: str
    excess: float   # how far past the usual or the limit, for ranking


def place_key(description) -> str:
    """One name for the spellings of a place: "DOUBLE SHOT F-7" and "Double Shot" are "double shot"."""
    words = re.sub(r"[^a-z]+", " ", str(description or "").lower()).split()
    return " ".join(word for word in words if len(word) > 1)


def place_name(descriptions: pd.Series) -> str:
    """How to show a place: its most common spelling, in title case if it's all capitals."""
    name = str(descriptions.mode().iloc[0]) if not descriptions.empty else ""
    return name.title() if name.isupper() else name


def months(dates: pd.Series) -> pd.Series:
    """The first of each date's month, as dates."""
    if dates.dt.tz is not None:
        dates = dates.dt.tz_localize(None)
    return dates.dt.to_period("M").dt.to_timestamp().dt.date


def history(rows: pd.DataFrame, month: dt.date) -> list[dt.date]:
    """The months a usual month is averaged over, for `rows` with a month column."""
    start = rows["month"].min() if not rows.empty else month
    return [m for m in (add_months(month, -i) for i in range(1, HISTORY_MONTHS + 1)) if m >= start]


def usual(rows: pd.DataFrame, month: dt.date, by: str) -> pd.Series:
    """A usual month's spending for each `by` value (e.g. "category"), from rows with a month column."""
    past = history(rows, month)
    if not past:
        return pd.Series(dtype=float)
    return rows[rows["month"].isin(past)].groupby(by)["amount"].sum() / len(past)


def insights(rows: pd.DataFrame, month: dt.date, today: dt.date, budget: Budget, currency: str) -> list[Insight]:
    """Most important first. `rows` is counted money out in one currency, over the user's
    whole history, with date, description, category and amount."""
    rows = rows.assign(month=months(rows["date"]), place=rows["description"].map(place_key))
    this = rows[rows["month"] == month]
    if this.empty:
        return []
    so_far = "" if pace(0, None, month, today).finished else " so far"
    past = history(rows, month)
    usual_month = rows.loc[rows["month"].isin(past), "amount"].sum() / len(past) if past else this["amount"].sum()
    found: list[Insight] = []
    flagged_limits: list = []

    for position, limit in enumerate(budget.limits):
        spent = this.loc[limit.matches(this), "amount"].sum()
        progress = pace(spent, limit.amount, month, today)
        category = limit.category or _main(this.loc[limit.matches(this), "category"])
        if progress.status == "over":
            found.append(Insight(
                limit.name, f"{money(spent, currency)} of your {money(limit.amount, currency)} limit{so_far}, "
                f"{money(-progress.left, currency)} over.", "critical", category, "limit", str(position),
                -progress.left))
            flagged_limits.append(limit)
        elif progress.status == "heading over" and progress.used >= 0.5:
            found.append(Insight(
                limit.name, f"{money(spent, currency)} of {money(limit.amount, currency)} with "
                f"{progress.days_left} days to go. At this pace it ends near {money(progress.projected, currency)}.",
                "warning", category, "limit", str(position), progress.projected - limit.amount))
            flagged_limits.append(limit)

    usual_places = usual(rows, month, "place")
    for place, group in this.groupby("place"):
        if any(limit.matches(group).all() for limit in flagged_limits):
            continue
        spent, times, before = group["amount"].sum(), len(group), usual_places.get(place, 0.0)
        name, category = place_name(group["description"]), _main(group["category"])
        if past and before and spent >= 1.5 * before and spent - before >= PLACE_SHARE * usual_month:
            ratio = spent / before
            compared = (f"about {ratio:.0f}× your usual {money(before, currency)} a month" if ratio >= 2
                        else f"up from a usual {money(before, currency)} a month")
            often = f", {times} times" if times > 1 else ""
            found.append(Insight(name, f"{money(spent, currency)}{so_far}{often}: {compared}.",
                                 "warning", category, "place", place, spent - before))
        elif times >= HABIT_TIMES and spent >= PLACE_SHARE * usual_month:
            found.append(Insight(name, f"{times} times this month, {money(spent, currency)} in all "
                                       f"(about {money(spent / times, currency)} each).",
                                 "info", category, "place", place, spent))

    usual_categories = usual(rows, month, "category")
    for category, spent in this.groupby("category")["amount"].sum().items():
        before = usual_categories.get(category, 0.0)
        # Already said by its places (or limits) above.
        explained = sum(i.excess for i in found if i.kind != "category" and i.category == category)
        if explained >= 0.6 * (spent - before):
            continue
        if before and spent >= 1.25 * before and spent - before >= CATEGORY_SHARE * usual_month:
            found.append(Insight(category, f"{money(spent, currency)}{so_far}, {money(spent - before, currency)} "
                                           f"more than a usual month ({money(before, currency)}).",
                                 "warning", category, "category", category, spent - before))

    return sorted(found, key=lambda i: (LEVELS.index(i.level), -i.excess))


def _main(categories: pd.Series) -> str:
    return str(categories.mode().iloc[0]) if not categories.empty else "Other"


