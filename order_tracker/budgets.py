"""Monthly budgets, and how a month is going against them.

A budget is a total for the month plus optional limits on parts of it. A
limit covers a category ("Eating out": Food), places whose name has certain
words ("Coffee": double shot), or both.

Budgets are saved from a month on: changing the budget in December leaves
November judged by the budget it had. Months before the first saved budget
use that first one, so a new budget can be compared with past months too.
"""

import calendar
import datetime as dt
from dataclasses import dataclass, field

import pandas as pd

from .rules import Rule


@dataclass
class Limit:
    name: str
    amount: float
    category: str = ""
    words: list[str] = field(default_factory=list)

    def matches(self, rows: pd.DataFrame) -> pd.Series:
        """Which rows (with description, category and amount) the limit covers."""
        return Rule(self.words, self.category).matches(rows["description"], rows["category"], rows["amount"])


@dataclass
class Budget:
    total: float | None = None
    limits: list[Limit] = field(default_factory=list)


def month_key(day: dt.date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def add_months(day: dt.date, months: int) -> dt.date:
    """The first of the month `months` after (or before, if negative) `day`'s month."""
    index = day.year * 12 + day.month - 1 + months
    return dt.date(index // 12, index % 12 + 1, 1)


def budget_for(saved: dict[str, Budget], month: dt.date) -> Budget:
    """The budget that applies to `month`, from budgets saved by the month they start ('YYYY-MM')."""
    if not saved:
        return Budget()
    key = month_key(month)
    earlier = [start for start in saved if start <= key]
    return saved[max(earlier)] if earlier else saved[min(saved)]


@dataclass
class Pace:
    """A month's spending against a budget (or a limit)."""

    spent: float
    budget: float | None
    days: int     # in the month
    elapsed: int  # days so far; all of them once the month is over

    @property
    def finished(self) -> bool:
        return self.elapsed >= self.days

    @property
    def days_left(self) -> int:
        return self.days - self.elapsed

    @property
    def per_day(self) -> float:
        return self.spent / max(self.elapsed, 1)

    @property
    def projected(self) -> float:
        """Where the month ends if spending carries on at the same daily rate."""
        return self.spent if self.finished else self.per_day * self.days

    @property
    def left(self) -> float:
        return (self.budget or 0) - self.spent

    @property
    def used(self) -> float | None:
        return self.spent / self.budget if self.budget else None

    @property
    def status(self) -> str:
        """"over", "heading over", "on track" (this month), "under" (a past month) or "none"."""
        if not self.budget:
            return "none"
        if self.spent > self.budget:
            return "over"
        if self.finished:
            return "under"
        return "heading over" if self.projected > self.budget else "on track"


def pace(spent: float, budget: float | None, month: dt.date, today: dt.date) -> Pace:
    days = calendar.monthrange(month.year, month.month)[1]
    if (today.year, today.month) == (month.year, month.month):
        elapsed = today.day
    else:
        elapsed = days if (today.year, today.month) > (month.year, month.month) else 0
    return Pace(spent, budget, days, elapsed)
