"""The user's own rules for categories and who spending was for.

A rule has conditions and what to set:
- conditions: words in the merchant or payee ("pso, total"), the category the
  app found ("Groceries"), and an amount range ("from 5,000");
- what to set: a category ("Fuel"), who it was for ("Home"), or both.

Rules only look at money going out. When several rules match a transaction,
the one with the most conditions wins ("euro store from 5,000" beats "euro
store"); on a tie, the one higher in the list. A change the user makes to a
single transaction always wins over every rule.
"""

import re
from dataclasses import dataclass, field

import pandas as pd


def split_words(text: str) -> list[str]:
    return [word.strip() for word in (text or "").split(",") if word.strip()]


@dataclass
class Rule:
    words: list[str] = field(default_factory=list)
    category_is: str = ""
    min_amount: float | None = None
    max_amount: float | None = None
    category: str = ""   # set this category
    spent_for: str = ""  # set who it was for

    @property
    def conditions(self) -> int:
        return sum((bool(self.words), bool(self.category_is),
                    self.min_amount is not None, self.max_amount is not None))

    def is_complete(self) -> bool:
        return self.conditions > 0 and bool(self.category or self.spent_for)

    def matches(self, description: pd.Series, category: pd.Series, amount: pd.Series) -> pd.Series:
        hit = pd.Series(True, index=description.index)
        if self.words:
            # Whole words, ignoring case; digits may touch them ("PSO-0231", "TOTAL123").
            pattern = r"(?<![a-z])(?:" + "|".join(re.escape(w.lower()) for w in self.words) + r")(?![a-z])"
            hit &= description.fillna("").str.lower().str.contains(pattern, regex=True)
        if self.category_is:
            hit &= category == self.category_is
        if self.min_amount is not None:
            hit &= amount >= self.min_amount
        if self.max_amount is not None:
            hit &= amount <= self.max_amount
        return hit


def winning_rules(rules: list[Rule], target: str, description: pd.Series, category: pd.Series,
                  amount: pd.Series, eligible: pd.Series) -> pd.Series:
    """Which rule (its position, or -1) decides `target` ("category" or "spent_for") on each row."""
    winner = pd.Series(-1, index=description.index)
    best = pd.Series(0, index=description.index)
    for position, rule in enumerate(rules):
        if not getattr(rule, target) or not rule.conditions:
            continue
        # Strictly more conditions replaces an earlier match, so ties keep the first rule.
        hit = eligible & rule.matches(description, category, amount) & (rule.conditions > best)
        winner[hit] = position
        best[hit] = rule.conditions
    return winner


def apply_rules(rules: list[Rule], target: str, description: pd.Series, category: pd.Series,
                amount: pd.Series, eligible: pd.Series) -> pd.Series:
    """What the deciding rule sets for `target` on each row; NA where no rule matches."""
    values = pd.Series([getattr(rule, target) for rule in rules] + [pd.NA], dtype=object)
    winner = winning_rules(rules, target, description, category, amount, eligible)
    return pd.Series(values.iloc[winner.to_numpy()].to_numpy(), index=description.index, dtype=object)
