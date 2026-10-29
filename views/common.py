"""Helpers shared by the pages: the signed-in user, their storage, time zone,
formatting, the app's look (cards, colors, icons) and chart styling."""

import datetime as dt
import html
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from google.auth.exceptions import GoogleAuthError, RefreshError
from googleapiclient.errors import HttpError

from order_tracker import gmail_client, sync
from order_tracker.auth import GmailTokenStore
from order_tracker.config import data_dir, token_key
from order_tracker.institutions import SOURCE_PREFIX, STATEMENT_PREFIX
from order_tracker.ledger import category_options, spend_for_labels
from order_tracker.money import money, symbol
from order_tracker.parsers import PROVIDERS
from order_tracker.sessions import COOKIE, SESSION_DAYS, SessionStore
from order_tracker.storage import OrderStore
from order_tracker.users import User, user_dir

# One fixed color per service, so a service keeps its color whatever is filtered.
# Categorical slots 1-4 of the validated chart palette, with separate dark-mode steps.
SERVICE_COLORS = {
    "light": {"foodpanda": "#2a78d6", "careem": "#eb6834", "indrive": "#1baf7a", "kravemart": "#eda100"},
    "dark": {"foodpanda": "#3987e5", "careem": "#d95926", "indrive": "#199e70", "kravemart": "#c98500"},
}
# Single-series charts use slot 1.
SINGLE_COLOR = {"light": "#2a78d6", "dark": "#3987e5"}
# Categorical slots 1-5, in palette order, for a user's biggest spending categories;
# the rest share the neutral gray as "Everything else". Five plus the gray keeps a
# donut to six segments.
CATEGORY_SLOTS = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"],
    "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"],
}
NEUTRAL = {"light": "#898781", "dark": "#898781"}
EVERYTHING_ELSE = "Everything else"
# The app's surfaces and ink, matching .streamlit/config.toml; charts sit on cards.
UI = {
    "light": {"card": "#ffffff", "line": "rgba(16,32,29,0.09)", "text": "#13201d", "muted": "#5c6a67",
              "accent": "#0b7d74"},
    "dark": {"card": "#172120", "line": "rgba(255,255,255,0.07)", "text": "#e7efed", "muted": "#9aa9a6",
             "accent": "#74d9cd"},
}
# The accent as a CSS color that follows the theme the moment the viewer switches it.
ACCENT = "var(--app-accent)"
# Reserved for state (never a category): always shown with an icon and a label.
STATUS = {"good": "#0ca30c", "warning": "#fab219", "critical": "#d03b3b"}
CHROME = {
    "light": {"surface": UI["light"]["card"], "text": "#52514e", "grid": "#e1e0d9", "axis": "#c3c2b7"},
    "dark": {"surface": UI["dark"]["card"], "text": "#c3c2b7", "grid": "#2c2c2a", "axis": "#383835"},
}
FONT = 'Figtree, system-ui, -apple-system, "Segoe UI", sans-serif'
# Material Symbols for each category; the user's own categories get a tag.
CATEGORY_ICONS = {
    "Food": "restaurant", "Groceries": "shopping_basket", "Ride": "local_taxi", "Delivery": "delivery_dining",
    "Fuel": "local_gas_station", "Bills & utilities": "bolt", "Mobile & internet": "wifi",
    "Subscriptions": "subscriptions", "Shopping": "shopping_bag", "Health": "medical_services",
    "Education": "school", "Cash withdrawal": "atm", "Fees & charges": "receipt_long",
    "Transfers": "swap_horiz", "Income": "payments", "Refunds": "undo", "Other": "category",
    EVERYTHING_ELSE: "more_horiz",
}
CHART_CONFIG = {"displayModeBar": False}

PERIODS = ["This month", "Last month", "Last 3 months", "Last 12 months", "All time", "Custom"]


def current_user() -> User | None:
    """The user who continued with Google in this browser session, or None."""
    return st.session_state.get("user")


def consent_markdown(sender_names: list[str]) -> str:
    """What the app does with Gmail access, shown before the user allows it."""
    return f"""
**What the app will do**
- Search your Gmail for emails from these senders only: {', '.join(sender_names)}.
- Read those emails to pull out the date, amount, merchant or payee, and order or reference number.
- Keep what it finds in your own private space in this app, which other users can't see.

**What it will never do**
- Send, delete, change or label any of your emails.
- Look at emails from other senders. Google's read-only permission covers your whole
  mailbox, because Gmail has no permission for "only these senders", so this is a promise
  the app keeps by only ever searching for the senders above.
- Share your data with anyone, or use it for advertising.

**You stay in control**
- Disconnect Gmail at any time under **Settings → Gmail & account**. That also withdraws
  the permission at Google.
- Delete all your data at any time in the same place.
- You can also see and remove the app's access in your Google account under
  *Security → Third-party apps*.
"""


def open_store(user: User | None = None) -> OrderStore:
    """The signed-in user's own database."""
    user = user or current_user()
    if user is None:
        raise RuntimeError("No signed-in user")
    return OrderStore(user_dir(user.id) / "orders.db")


def open_sessions() -> SessionStore:
    return SessionStore(data_dir() / "sessions.db")


def session_cookie() -> str | None:
    """The remembered-sign-in token this browser sent, if any. (Tests replace this.)"""
    value = st.context.cookies.get(COOKIE)
    return value if isinstance(value, str) and value else None


def set_session_cookie(token: str, days: int = SESSION_DAYS) -> None:
    """Store (or, with days=0, clear) the remembered-sign-in cookie in this browser."""
    secure = "; Secure" if (st.context.url or "").startswith("https") else ""
    st.html(
        f'<script>document.cookie = "{COOKIE}={token}; Max-Age={days * 86400}; Path=/; SameSite=Lax{secure}";</script>',
        unsafe_allow_javascript=True,
    )


def sign_out() -> None:
    sessions = open_sessions()  # a callback: open a fresh connection on this thread
    sessions.delete(st.session_state.get("session_token"))
    sessions.close()
    for key in ("user", "gmail", "auto_sync_done", "session_token"):
        st.session_state.pop(key, None)
    st.session_state["clear_session_cookie"] = True


def gmail_tokens(user: User) -> GmailTokenStore:
    return GmailTokenStore(user_dir(user.id), token_key())


def gmail_session(user: User) -> dict | None:
    """This user's live Gmail connection ({"creds", "account"}) in this browser session."""
    session = st.session_state.get("gmail")
    return session if session and session["user_id"] == user.id else None


def theme_mode() -> str:
    theme = st.context.theme
    return "dark" if theme is not None and theme.type == "dark" else "light"


def category_icon(category: str) -> str:
    return CATEGORY_ICONS.get(category, "sell")


def tidy(name) -> str:
    """A merchant or payee as written in an alert, without the shouting: "DOT LAHORE" -> "Dot Lahore"."""
    name = str(name or "").strip()
    return name.title() if name.isupper() else name


def esc(text) -> str:
    """Text from emails, or typed by the user, made safe to put inside the app's own HTML."""
    return html.escape(str(text or ""))


def _both(name: str) -> str:
    return f"light-dark({UI['light'][name]}, {UI['dark'][name]})"


def app_style() -> None:
    """Cards, the hero figure and meters: the app-like look the pages share. A container
    with a key starting "card" (st.container(key="card_budget")) is drawn as a card.

    Colors use light-dark(), which follows the color scheme Streamlit sets on the app,
    so they change the moment the viewer switches theme, without a rerun."""
    st.html(f"""<style>
    .stApp {{ --app-accent: {_both("accent")}; --app-muted: {_both("muted")}; --app-line: {_both("line")}; }}
    [data-testid="stMainBlockContainer"] {{ max-width: 1180px; padding-top: 2.2rem; }}
    .st-key-theme_watch {{ display: none; }}
    div[class*="st-key-card"] {{
        background: {_both("card")}; border: 1px solid var(--app-line); border-radius: 22px;
        padding: 18px 20px 16px;
    }}
    .card-title {{ font-weight: 650; font-size: 1.12rem; margin: 0; }}
    .muted {{ color: var(--app-muted); }}
    .hero-label {{ color: var(--app-muted); font-size: 0.95rem; }}
    .hero-value {{ font-size: clamp(2.7rem, 9vw, 3.5rem); font-weight: 700; line-height: 1.1;
                   letter-spacing: -0.02em; margin: 2px 0 4px; }}
    .hero-sub {{ font-size: 1rem; }}
    .meter {{ height: 10px; border-radius: 5px; overflow: hidden; margin: 6px 0 6px; }}
    .meter > span {{ display: block; height: 100%; border-radius: 5px; }}
    .meter-legend {{ display: flex; justify-content: space-between; font-size: 0.85rem; color: var(--app-muted); }}
    .sheet-amount {{ text-align: center; margin: 4px 0 8px; }}
    .sheet-amount .big {{ font-size: 2.6rem; font-weight: 700; letter-spacing: -0.02em; line-height: 1.15; }}
    .details {{ width: 100%; border-collapse: collapse; font-size: 0.92rem; }}
    .details td {{ padding: 8px 2px; border-top: 1px solid var(--app-line); vertical-align: top; }}
    .details td:last-child {{ text-align: right; font-weight: 600; overflow-wrap: anywhere; }}
    </style>""")


def card(name: str):
    """A card on the page: a keyed container that app_style draws with a surface and rounded corners."""
    return st.container(key=f"card_{name}")


def meter(share: float, color: str) -> str:
    """A bar filled to `share` (0-1, capped) of its track; the track is a lighter step of the fill."""
    return (f'<div class="meter" style="background:color-mix(in srgb, {color} 20%, transparent)">'
            f'<span style="width:{min(share, 1) * 100:.1f}%;background:{color}"></span></div>')


def viewer_timezone():
    try:
        if st.context.timezone:
            return ZoneInfo(st.context.timezone)
    except (KeyError, ValueError):
        pass
    return dt.datetime.now().astimezone().tzinfo


def flash(message: str) -> None:
    """Show a toast after the next rerun."""
    st.session_state["flash"] = message


def service_name(key: str) -> str:
    return PROVIDERS[key].name


def source_name(key: str, store: OrderStore) -> str:
    """Display name for a delivery service key, 'acct:<institution>' or 'stmt:<institution>'."""
    if key in PROVIDERS:
        return PROVIDERS[key].name
    names = {i.key: i.name for i in store.institutions()}
    if key.startswith(SOURCE_PREFIX):
        return names.get(key[len(SOURCE_PREFIX):], key[len(SOURCE_PREFIX):])
    if key.startswith(STATEMENT_PREFIX):
        return names.get(key[len(STATEMENT_PREFIX):], key[len(STATEMENT_PREFIX):]) + " statements"
    return key


def run_sync(store: OrderStore, user: User, source_keys: list[str], days: int = 365,
             since: dt.date | None = None, until: dt.date | None = None) -> None:
    """Sync the given sources with a progress bar, then rerun; `since`/`until` read an older period."""
    st.session_state["auto_sync_done"] = True
    session = gmail_session(user)
    sources = sync.available_sources(store)
    bar = st.progress(0.0, text="Searching Gmail…")

    def on_progress(name: str, done: int, total: int) -> None:
        bar.progress(done / total, text=f"{name}: reading email {done} of {total}")

    try:
        results = sync.sync_gmail(
            gmail_client.GmailClient(session["creds"]), store,
            [sources[k] for k in source_keys if k in sources], days,
            session["account"], on_progress, since=since, until=until,
        )
    except RefreshError:
        bar.empty()
        gmail_tokens(user).delete()
        st.session_state.pop("gmail", None)
        st.error("Gmail access was withdrawn. You can allow it again on Gmail access.")
        return
    except (HttpError, GoogleAuthError) as exc:
        bar.empty()
        st.error(f"Sync stopped: {exc}")
        return
    bar.empty()

    added = sum(s.added for s in results.values())
    errors = sum(s.errors for s in results.values())
    message = f"Sync complete: {added} new {'entry' if added == 1 else 'entries'}."
    if errors:
        message += f" {errors} email(s) could not be downloaded and will be retried next time."
    # Rerun so everything on screen (status, setup steps, figures) reflects the new data.
    flash(message)
    st.rerun()


def compact(value: float) -> str:
    """1,284 / 12.9K / 4.2M: short enough for a stat tile in a narrow window."""
    for size, suffix in ((1e9, "B"), (1e6, "M"), (1e4, "K")):
        if abs(value) >= size:
            divisor = size if suffix != "K" else 1e3
            return f"{value / divisor:,.1f}{suffix}"
    return f"{value:,.0f}"


def _month_start(day: dt.date, months_back: int) -> dt.date:
    index = day.year * 12 + day.month - 1 - months_back
    return dt.date(index // 12, index % 12 + 1, 1)


def pick_period(column, first_day: dt.date, last_day: dt.date, key: str,
                default: str = "Last 12 months") -> tuple[dt.date, dt.date]:
    """A period preset selector (plus a date range for "Custom"); returns (start, end)."""
    today = dt.datetime.now(viewer_timezone()).date()
    choice = column.selectbox("Period", PERIODS, index=PERIODS.index(default), key=key)
    if choice == "This month":
        return today.replace(day=1), today
    if choice == "Last month":
        end = today.replace(day=1) - dt.timedelta(days=1)
        return end.replace(day=1), end
    if choice == "Last 3 months":
        return _month_start(today, 2), today
    if choice == "Last 12 months":
        return _month_start(today, 11), today
    if choice == "All time":
        return first_day, max(last_day, today)
    picked = column.date_input("Dates", value=(first_day, last_day), key=f"{key}_dates")
    return picked if len(picked) == 2 else (picked[0], picked[0])


def months_in(start: dt.date, end: dt.date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month + 1


def style_figure(fig: go.Figure, mode: str, height: int) -> go.Figure:
    chrome = CHROME[mode]
    fig.update_layout(
        height=height,
        margin=dict(l=0, r=0, t=36, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, color=chrome["text"], size=13),
        hoverlabel=dict(font_family=FONT),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None),
    )
    # Margins are zero, so automargin is what makes room for the tick labels.
    fig.update_xaxes(showgrid=False, linecolor=chrome["axis"], title=None, automargin=True)
    fig.update_yaxes(
        gridcolor=chrome["grid"], gridwidth=1, zerolinecolor=chrome["axis"], title=None, automargin=True
    )
    return fig


def month_axis(fig: go.Figure, months: pd.Series) -> None:
    """Columns near 24px wide, room for at least six, and month ticks that don't crowd."""
    first, last = months.min(), months.max()
    n_months = len(pd.date_range(first, last, freq="MS"))
    slots = max(n_months, 6)
    gap = min(0.9, max(0.25, 1 - 24 / (900 / slots)))
    # A date axis sizes a lone column by the axis span, so the width is set (in ms).
    fig.update_traces(width=(1 - gap) * 30.4 * 86_400_000, selector=dict(type="bar"))
    fig.update_layout(barcornerradius=4)
    fig.update_xaxes(hoverformat="%B %Y")
    if n_months < slots:
        # One month alone would fill the chart: centre it in six months' room, ticking only real months.
        pad = pd.Timedelta(days=30.4 * ((slots - n_months) / 2 + 0.5))
        ticks = pd.date_range(first, last, freq="MS")
        fig.update_xaxes(range=[first - pad, last + pad], tickvals=ticks, ticktext=[f"{m:%b %Y}" for m in ticks])
    else:
        # Plotly's own month labels put the year under a month only when it changes, which fits a phone.
        fig.update_xaxes(dtick="M1" if n_months <= 12 else "M3" if n_months <= 36 else "M12")
    fig.update_yaxes(tickformat=",.0f")


def category_colors(ledger: pd.DataFrame, mode: str) -> dict[str, str]:
    """A color for each of the user's biggest spending categories. Ranked over all
    time, not the period shown, so a category keeps its color as filters change."""
    spent = ledger[ledger["counted"] & (ledger["amount"] > 0)].groupby("category")["amount"].sum()
    top = spent.sort_index().sort_values(ascending=False, kind="stable").index[:len(CATEGORY_SLOTS[mode])]
    return dict(zip(top, CATEGORY_SLOTS[mode]))


def category_group(category: str, colors: dict[str, str]) -> str:
    return category if category in colors else EVERYTHING_ELSE


def stacked_months(rows: pd.DataFrame, colors: dict[str, str], currency: str, mode: str,
                   budget: pd.Series | None = None) -> go.Figure:
    """Monthly columns split by category, biggest at the bottom, with the total on each cap.
    `rows` has month, category and amount; `budget` (by month) is drawn as a dashed line."""
    rows = rows.assign(group=rows["category"].map(lambda c: category_group(c, colors)))
    table = rows.pivot_table(index="month", columns="group", values="amount", aggfunc="sum", fill_value=0)
    order = [g for g in table.sum().sort_values(ascending=False).index if g != EVERYTHING_ELSE]
    if EVERYTHING_ELSE in table:
        order.append(EVERYTHING_ELSE)
    rest = ", ".join(sorted(set(rows.loc[rows["group"] == EVERYTHING_ELSE, "category"])))
    totals = table.sum(axis=1)
    fig = go.Figure()
    for group in order:
        values = table[group][table[group] > 0]  # no empty segments to hover or click
        label = f"{group} ({rest})" if group == EVERYTHING_ELSE else group
        fig.add_bar(
            x=list(values.index), y=values.tolist(), name=group,
            customdata=[[group, totals[month]] for month in values.index],
            marker=dict(color=colors.get(group, NEUTRAL[mode]), line=dict(width=1, color=CHROME[mode]["surface"])),
            hovertemplate=(f"<b>{label}</b><br>%{{x|%B %Y}}: {symbol(currency)} %{{y:,.0f}}"
                           f"<br>Month total: {symbol(currency)} %{{customdata[1]:,.0f}}<extra></extra>"),
        )
    # Totals on every cap crowd a phone, so past six months only the latest and the biggest are labelled.
    labelled = totals if len(totals) <= 6 else totals[totals.index.isin([totals.index.max(), totals.idxmax()])]
    for month, total in labelled.items():
        fig.add_annotation(x=month, y=total, text=compact(total), showarrow=False, yanchor="bottom", yshift=2,
                           font=dict(color=CHROME[mode]["text"], size=12))
    top = totals.max()
    if budget is not None and budget.notna().any():
        # A step per month, wide enough to reach across each month's column.
        months = list(budget.index) + [budget.index.max() + pd.offsets.MonthBegin(1)]
        fig.add_scatter(
            x=[m - pd.Timedelta(days=15) for m in months], y=budget.tolist() + [budget.iloc[-1]], name="Budget",
            mode="lines", line=dict(shape="hv", dash="dash", width=2, color=CHROME[mode]["text"]),
            hovertemplate=f"Budget: {symbol(currency)} %{{y:,.0f}}<extra></extra>",
        )
        top = max(top, budget.max())
    # Hiding a category from the legend would leave the totals wrong, so the legend is a key only.
    fig.update_layout(barmode="stack", legend=dict(traceorder="normal", itemclick=False, itemdoubleclick=False))
    month_axis(fig, totals.index.to_series())
    fig.update_yaxes(range=[0, top * 1.15])
    return fig


def donut(by_category: pd.Series, colors: dict[str, str], currency: str, mode: str) -> go.Figure:
    """Where the money went, part-to-whole: the colored categories and "Everything else",
    with the biggest category's share in the middle."""
    groups = by_category.groupby(lambda c: category_group(c, colors)).sum().sort_values(ascending=False)
    groups = pd.concat([groups.drop(EVERYTHING_ELSE, errors="ignore"), groups.filter([EVERYTHING_ELSE])])
    fig = go.Figure(go.Pie(
        labels=list(groups.index), values=groups.tolist(), hole=0.7, sort=False, direction="clockwise",
        marker=dict(colors=[colors.get(g, NEUTRAL[mode]) for g in groups.index],
                    line=dict(color=CHROME[mode]["surface"], width=2)),
        textinfo="none", hovertemplate=f"<b>%{{label}}</b><br>{symbol(currency)} %{{value:,.0f}} · %{{percent}}<extra></extra>",
    ))
    top = by_category.idxmax()
    fig.add_annotation(text=esc(top), showarrow=False, x=0.5, y=0.6, yanchor="middle",
                       font=dict(size=13, color=UI[mode]["muted"]))
    fig.add_annotation(text=f"<b>{by_category.max() / by_category.sum():.0%}</b>", showarrow=False, x=0.5, y=0.44,
                       yanchor="middle", font=dict(size=28, color=UI[mode]["text"]))
    fig.update_layout(height=230, margin=dict(l=0, r=0, t=6, b=6), showlegend=False,
                      paper_bgcolor="rgba(0,0,0,0)", font=dict(family=FONT), hoverlabel=dict(font_family=FONT))
    return fig


def labelled_bars(labels: list[str], values: list[float], colors: list[str], currency: str,
                  mode: str) -> go.Figure:
    """Horizontal bars with the value at each tip, first item on top."""
    fig = go.Figure(go.Bar(
        x=values,
        y=labels,
        orientation="h",
        marker=dict(color=colors),
        text=[money(v, currency) for v in values],
        textposition="outside",
        textfont=dict(color=CHROME[mode]["text"]),
        cliponaxis=False,
        hovertemplate=f"%{{y}}: {symbol(currency)} %{{x:,.0f}}<extra></extra>",
    ))
    fig.update_layout(barcornerradius=4, bargap=0.55, showlegend=False)
    # Every bar carries its value label, so the value axis is dropped.
    fig.update_xaxes(showticklabels=False, showgrid=False, zeroline=False, showline=False)
    fig.update_yaxes(autorange="reversed", showgrid=False, ticksuffix="  ")
    fig = style_figure(fig, mode, 70 + 44 * len(labels))
    fig.update_layout(margin=dict(l=0, r=90, t=10, b=0))
    return fig


def clicked_month(event) -> pd.Timestamp | None:
    """The month of the bar clicked in a monthly chart drawn with on_select, if any."""
    points = event.selection.points if event else []
    return pd.Timestamp(points[0]["x"]).to_period("M").to_timestamp() if points else None


def clicked_group(event) -> str | None:
    """The category (or "Everything else") of the segment clicked in stacked_months, if any."""
    points = event.selection.points if event else []
    group = points[0].get("customdata") if points else None
    return group[0] if isinstance(group, list) else group


def local_month(dates: pd.Series) -> pd.Series:
    return dates.dt.tz_localize(None).dt.to_period("M").dt.to_timestamp()


def item_editor(store: OrderStore, table: pd.DataFrame, items: list[str], key: str, column_config: dict) -> None:
    """A read-only table whose "category", "spent_for", "note" and "counted" columns
    (those present) can be changed; changes are saved per item ("txn:<key>" or
    "order:<key>") and apply everywhere in the app."""
    version = st.session_state.get(f"{key}_version", 0)
    # The key changes with the rows shown, so a pending edit can never land on a different row.
    editor_key = f"{key}_{version}_{hash(tuple(items))}"

    def save() -> None:
        # Callbacks run on the next rerun's thread; SQLite connections can't cross threads.
        callback_store = open_store()
        for row, change in st.session_state[editor_key]["edited_rows"].items():
            for field, value in change.items():
                if field == "category" and value:
                    callback_store.set_category(items[int(row)], value)
                elif field in ("spent_for", "note", "counted"):
                    # Clearing "For" (None) goes back to what the rules say.
                    callback_store.set_item_detail(items[int(row)], field, value)
        callback_store.close()
        st.session_state[f"{key}_version"] = version + 1

    editable = {
        "category": st.column_config.SelectboxColumn(
            "Category", options=category_options(store, *table["category"]), required=True),
        "spent_for": st.column_config.SelectboxColumn(
            "For", options=list(dict.fromkeys(spend_for_labels(store) + [v for v in table.get("spent_for", []) if v])),
            help="Who it was for. Clear it to go back to what your rules say."),
        "note": st.column_config.TextColumn("Note", width="medium", help="Anything to remember, e.g. \"Outing with Zain\""),
        "counted": st.column_config.CheckboxColumn(
            "In spending", help="Tick to count it as spending, untick to leave it out."),
    }
    st.data_editor(
        table,
        key=editor_key,
        on_change=save,
        hide_index=True,
        height=min(36 + 35 * len(table), 640),
        placeholder="",
        disabled=[c for c in table.columns if c not in editable],
        column_config={**column_config, **{c: config for c, config in editable.items() if c in table}},
    )
