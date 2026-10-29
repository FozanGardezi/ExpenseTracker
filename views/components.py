"""App-style list rows that open something when tapped: a payment, a category, a place.

Built with st.components.v2, so a tap reaches Python as a trigger value. Every
piece of text is set with textContent, never as HTML, because descriptions
come from emails.
"""

import datetime as dt

import pandas as pd
import streamlit as st

from order_tracker.money import money
from views.common import ACCENT, NEUTRAL, STATUS, category_icon, theme_mode, tidy

# Streamlit sets its theme on the component as --st-* variables, which follow a theme switch live.
_CSS = """
.list {
  --text: var(--st-text-color); --muted: color-mix(in srgb, var(--st-text-color) 62%, transparent);
  --hover: color-mix(in srgb, var(--st-text-color) 5%, transparent); --accent: var(--st-primary-color);
  --good: var(--st-green-text-color);
  display: flex; flex-direction: column; color: var(--text); font-family: inherit;
}
.header { font-size: 0.8rem; font-weight: 600; color: var(--muted); padding: 14px 6px 4px; }
.row {
  all: unset; box-sizing: border-box; width: 100%; display: grid; grid-template-columns: auto 1fr auto;
  align-items: center; column-gap: 12px; row-gap: 6px; padding: 10px 8px; border-radius: 14px;
  color: var(--text); font-family: inherit; position: relative;
}
button.row { cursor: pointer; }
button.row:hover { background: var(--hover); }
button.row:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.row.level { border-left: 3px solid var(--level); border-radius: 4px 14px 14px 4px; padding-left: 10px; }
.icon {
  width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center;
  font-family: "Material Symbols Rounded"; font-size: 21px; line-height: 1;
  font-variation-settings: "FILL" 1, "wght" 500; font-feature-settings: "liga"; -webkit-font-smoothing: antialiased;
}
.dot { width: 12px; height: 12px; border-radius: 50%; margin: 0 6px; }
.body { min-width: 0; }
.title { font-weight: 600; font-size: 0.96rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sub { font-size: 0.84rem; color: var(--muted); margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wrap .sub { white-space: normal; }
.end { text-align: right; }
.amount { font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
.amount.in { color: var(--good); }
.meta { font-size: 0.8rem; color: var(--muted); margin-top: 2px; white-space: nowrap; }
.chev { font-family: "Material Symbols Rounded"; font-size: 20px; color: var(--muted); }
.meter { grid-column: 2 / 4; height: 6px; border-radius: 3px; overflow: hidden; }
.meter > span { display: block; height: 100%; border-radius: 3px; }
.empty { color: var(--muted); padding: 6px; font-size: 0.92rem; }
"""

_JS = """
export default function ({ data, parentElement, setTriggerValue }) {
  const list = parentElement.querySelector(".list");
  const part = (tag, cls, text) => {
    const el = document.createElement(tag);
    el.className = cls;
    if (text !== undefined && text !== null) el.textContent = text;
    return el;
  };
  const rows = data.rows.map((row) => {
    if (row.header) return part("div", "header", row.header);
    const item = part(row.id ? "button" : "div", "row" + (row.wrap ? " wrap" : "") + (row.level ? " level" : ""));
    if (row.id) {
      item.type = "button";
      item.setAttribute("aria-label", [row.title, row.amount, row.sub].filter(Boolean).join(", "));
      item.addEventListener("click", () => setTriggerValue("picked", row.id));
    }
    if (row.level) item.style.setProperty("--level", row.level);
    if (row.dot) {
      const dot = part("span", "dot");
      dot.style.background = row.dot;
      item.appendChild(dot);
    } else {
      const icon = part("span", "icon", row.icon || "");
      icon.setAttribute("aria-hidden", "true");
      icon.style.background = row.tint || "transparent";
      icon.style.color = row.ink || "inherit";
      item.appendChild(icon);
    }
    const body = part("div", "body");
    body.appendChild(part("div", "title", row.title));
    if (row.sub) body.appendChild(part("div", "sub", row.sub));
    item.appendChild(body);
    const end = part("div", "end");
    if (row.amount) end.appendChild(part("div", "amount" + (row.money_in ? " in" : ""), row.amount));
    if (row.meta) end.appendChild(part("div", "meta", row.meta));
    if (!row.amount && !row.meta && row.id) end.appendChild(part("span", "chev", "chevron_right"));
    item.appendChild(end);
    if (row.meter) {
      const track = part("div", "meter");
      track.style.background = `color-mix(in srgb, ${row.meter.color} 20%, transparent)`;
      const fill = part("span", "");
      fill.style.width = `${Math.min(row.meter.share, 1) * 100}%`;
      fill.style.background = row.meter.color;
      track.appendChild(fill);
      item.appendChild(track);
    }
    return item;
  });
  if (!rows.length && data.empty) rows.push(part("div", "empty", data.empty));
  list.replaceChildren(...rows);
}
"""



def tap_list(rows: list[dict], key: str, empty: str = "") -> str | None:
    """Show rows; returns the id of the row tapped on this run, if any.

    A row has title, and optionally id (tappable), sub, amount, meta, icon with
    tint and ink (or a dot color), money_in, wrap (let sub wrap), level (a
    colored edge), meter {share, color}; or it is a {"header": ...} label.
    """
    # Registered on every use: registering the same definition again is free, and a new
    # runtime (a restarted server, or a test) would otherwise not know the component.
    mount = st.components.v2.component("tap_list", html='<div class="list"></div>', css=_CSS, js=_JS)
    result = mount(data={"rows": rows, "empty": empty}, key=key, on_picked_change=lambda: None)
    return getattr(result, "picked", None) if result is not None else None


# Charts are drawn in Python with the theme's colors, and switching theme doesn't rerun
# the app, so this watches Streamlit's theme variable and asks for a rerun when it changes.
_THEME_JS = """
export default function ({ parentElement, setTriggerValue }) {
  const host = parentElement.host || parentElement;
  const read = () => getComputedStyle(host).getPropertyValue("--st-background-color").trim();
  let seen = read();
  const timer = setInterval(() => {
    const now = read();
    if (now && now !== seen) {
      seen = now;
      setTriggerValue("changed", now);
    }
  }, 700);
  return () => clearInterval(timer);
}
"""


def follow_theme() -> None:
    """Redraw the page when the viewer switches between light and dark."""
    mount = st.components.v2.component("theme_watch", js=_THEME_JS)
    with st.container(key="theme_watch"):
        mount(key="theme_watch_component", on_changed_change=lambda: None)


def tint(color: str) -> dict:
    """An icon's colors: its category color on a pale wash of the same color."""
    return {"tint": f"{color}29", "ink": color}


def day_label(day: dt.date, today: dt.date) -> str:
    if day == today:
        return "Today"
    if day == today - dt.timedelta(days=1):
        return "Yesterday"
    return f"{day:%A} {day.day} {day:%b}" + ("" if day.year == today.year else f" {day.year}")


def payment_rows(rows: pd.DataFrame, colors: dict[str, str], today: dt.date, by_day: bool = True) -> list[dict]:
    """Ledger rows (newest first, local dates) as list rows: by day with times, or with dates."""
    mode = theme_mode()
    result: list[dict] = []
    last_day = None
    for row in rows.itertuples():
        day = row.date.date()
        if by_day and day != last_day:
            result.append({"header": day_label(day, today)})
            last_day = day
        money_in = row.amount < 0
        when = f"{row.date:%I:%M %p}".lstrip("0").lower() if by_day else f"{day.day} {day:%b}"
        if not by_day and day.year != today.year:
            when += f" {day.year}"
        sub = row.category + " · " + (row.paid_with if row.kind == "Order" and row.paid_with else row.source)
        if row.note:
            sub += f" · {row.note}"
        meta = when if row.counted else f"{when} · not counted"
        result.append({
            "id": row.item, "title": tidy(row.description) or row.source, "sub": sub,
            "amount": ("+" if money_in else "") + money(abs(row.amount), row.currency),
            "meta": meta, "money_in": money_in, "icon": category_icon(row.category),
            **tint(colors.get(row.category, NEUTRAL[mode])),
        })
    return result


def level_color(level: str) -> str:
    return {"critical": STATUS["critical"], "warning": STATUS["warning"]}.get(level, ACCENT)
