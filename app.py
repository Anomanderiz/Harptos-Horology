# app.py
# ----------------------------------------------------------------------
# Harptos – Campaign Calendar (Shiny for Python)
# - Fixes illegible header (white on dark)
# - Wires header buttons (Set Current Date, Jump to Today, Refresh Events)
# - Clickable 30-day grid opens a robust modal
# - Defensive DB calls so "Save" never crashes the session
# - Loads CSS from absolute /www path for reliable deploys
# ----------------------------------------------------------------------

from __future__ import annotations

import os
from datetime import date
from typing import List, Dict, Any

from shiny import App, ui, render, reactive
import anyio

from supa import SupaClient, HarptosDate, HarptosDateDict, step_harptos

# ------------ Config ---------------------------------------------------------

# 12 months (30 days each)
MONTHS: List[str] = [
    "Hammer, Deepwinter",
    "Alturiak, The Claw of Winter",
    "Ches, The Claw of the Sunsets",
    "Tarsakh, The Claw of Storms",
    "Mirtul, The Melting",
    "Kythorn, The Time of Flowers",
    "Flamerule, Summertide",
    "Eleasis, Highsun",
    "Eleint, The Fading",
    "Marpenoth, Leafall",
    "Uktar, The Rotting",
    "Nightal, The Drawing Down",
]
DAYS_PER_MONTH: int = 30

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# Absolute path to /www for static assets (CSS, images, etc.)
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "www")

# ------------ App state ------------------------------------------------------

# Current Harptos date
current: reactive.Value[HarptosDateDict | None] = reactive.Value(None)

# "Real-world mapped" Harptos today (simple mapping)
today_harptos: reactive.Value[HarptosDateDict | None] = reactive.Value(None)

# Cached events
events: reactive.Value[List[Dict[str, Any]]] = reactive.Value([])

# DB client
db = SupaClient(SUPABASE_URL, SUPABASE_KEY, schema="public",
                state_table="state", events_table="events")

# ------------ UI helpers -----------------------------------------------------

def _month_index_from_name(name: str) -> int:
    try:
        return MONTHS.index(name) + 1
    except ValueError:
        return 1

def _month_name_from_index(idx: int) -> str:
    if 1 <= idx <= len(MONTHS):
        return MONTHS[idx - 1]
    return MONTHS[0]

def _map_date_to_harptos(d: date) -> HarptosDateDict:
    # Simple mapping: real month -> 1..12, clamp day to 30
    m = max(1, min(12, d.month))
    day = min(DAYS_PER_MONTH, max(1, d.day))
    # Keep a canonical FR year unless you prefer realtime
    y = 1492
    return HarptosDate(year=y, month=m, day=day)

def event_modal(default: Dict[str, Any] | None = None):
    d = default or {}
    return ui.modal(
        ui.row(
            ui.input_select("ev_month", "Month", choices=MONTHS,
                            selected=d.get("month_name", _month_name_from_index(d.get("month", 1)))),
            ui.input_numeric("ev_day", "Day", value=d.get("day", 1), min=1, max=DAYS_PER_MONTH),
            ui.input_numeric("ev_year", "Year", value=d.get("year", 1492)),
        ),
        ui.input_text("ev_title", "Title", value=d.get("title", "")),
        ui.input_text_area("ev_desc", "Description", value=d.get("description", "")),
        ui.input_date("ev_real_date", "Real-world date", value=d.get("real_date", date.today())),
        ui.row(
            ui.input_checkbox("ev_full_day", "All day?", value=bool(d.get("full_day", True))),
            ui.input_checkbox("ev_recurring", "Recurring yearly?", value=bool(d.get("recurring", False))),
        ),
        footer=ui.div(
            ui.input_action_button("ev_save", "Save", class_="btn btn-primary me-2"),
            ui.modal_button("Close"),
        ),
        title="Add / Edit Event",
        size="l",
        easy_close=False,
    )

def day_button(day: int) -> ui.TagChild:
    return ui.input_action_button(
        f"day_{day}",
        f"{day}",
        class_="btn btn-outline-light day-btn",
    )

def calendar_grid() -> ui.TagChild:
    # A simple 6x5 grid (30 days) for the current month
    rows: List[ui.TagChild] = []
    for r in range(6):
        start = r * 5 + 1
        btns = [day_button(d) for d in range(start, start + 5) if d <= DAYS_PER_MONTH]
        rows.append(ui.div(*btns, class_="d-flex gap-2 mb-2"))
    return ui.div(*rows, class_="calendar-grid")

# ------------ Server logic ---------------------------------------------------

async def reload_events():
    rows = await db.load_events()
    events.set(rows or [])

def _iso(d):
    try:
        return d.isoformat()
    except Exception:
        return None

# ------------ Page layout ----------------------------------------------------

page = ui.page_fluid(
    ui.tags.link(rel="stylesheet", href="styles.css"),

    # Header / top bar
    ui.div(
        ui.h5("Harptos – Campaign Calendar", class_="mb-0 me-3"),
        ui.input_action_button("btn_set_current", "Set Current Date",
                               class_="btn btn-primary me-2"),
        ui.input_action_button("btn_jump_today", "Jump to Today",
                               class_="btn btn-outline-light me-2"),
        ui.input_action_button("btn_refresh_events", "Refresh Events",
                               class_="btn btn-outline-light"),
        ui.div_output("current_date_label", class_="ms-auto text-on-dark"),
        class_="navbar d-flex align-items-center gap-2 px-3 py-2"
    ),

    ui.layout_columns(
        # Left: calendar
        ui.card(
            ui.card_header("Month"),
            ui.output_ui("calendar_ui"),
            class_="glass p-3"
        ),
        # Right: (optional) events list snapshot
        ui.card(
            ui.card_header("Events (latest 20)"),
            ui.output_ui("events_list"),
            class_="glass p-3"
        ),
        col_widths=(6,6)
    ),
    class_="p-3"
)

# ------------ Renderers ------------------------------------------------------

@render.text
def current_date_label():
    h = current.get()
    if not h:
        return "Current date: —"
    month_name = _month_name_from_index(h["month"])
    return f"Current date: {month_name} {h['day']}, {h['year']}"

@render.ui
def calendar_ui():
    return calendar_grid()

@render.ui
def events_list():
    rows = events.get()[:20]
    if not rows:
        return ui.div("No events yet.", class_="muted")
    items = []
    for r in rows:
        mname = r.get("month_name") or _month_name_from_index(int(r.get("month", 1)))
        items.append(
            ui.div(
                ui.strong(r.get("title", "(Untitled)")),
                ui.div(f"{mname} {r.get('day', 1)}, {r.get('year', 1492)}"),
                class_="mb-2"
            )
        )
    return ui.div(*items)

# ------------ Effects & Events ----------------------------------------------

# One-time initialiser
@reactive.Effect
async def _init():
    # Load saved current_date (if present)
    st = await db.get_state_value("current_date", default=None)
    if st and isinstance(st, dict):
        try:
            current.set(HarptosDate(
                year=int(st.get("year", 1492)),
                month=int(st.get("month", 1)),
                day=int(st.get("day", 1)),
            ))
        except Exception:
            current.set(HarptosDate(year=1492, month=1, day=1))
    else:
        current.set(HarptosDate(year=1492, month=1, day=1))

    # Compute a simple mapping for "today"
    today_harptos.set(_map_date_to_harptos(date.today()))

    # Preload events
    await reload_events()

# Header buttons
@reactive.Effect
@reactive.event(ui.input("btn_set_current"))
async def _set_current_date():
    h = current.get()
    if not h:
        ui.notification_show("No date to save yet.", type="warning")
        return
    ok = await db.set_state("current_date", h)
    if ok:
        ui.notification_show("Current date saved.", type="message")
    else:
        ui.notification_show("Failed to save current date (check RLS / logs).", type="error")

@reactive.Effect
@reactive.event(ui.input("btn_jump_today"))
def _jump_to_today():
    t = today_harptos.get()
    if not t:
        ui.notification_show("No ‘today’ available yet.", type="warning")
        return
    current.set(t)

@reactive.Effect
@reactive.event(ui.input("btn_refresh_events"))
async def _refresh_events():
    await reload_events()
    ui.notification_show("Events refreshed.", type="message")

# Generate click handlers for day_1..day_30
for _d in range(1, DAYS_PER_MONTH + 1):
    def _make_handler(day=_d):
        @reactive.Effect
        @reactive.event(ui.input(f"day_{day}"))
        def _open_modal():
            h = current.get() or HarptosDate(year=1492, month=1, day=1)
            ui.modal_show(event_modal({
                "month": h["month"],
                "month_name": _month_name_from_index(h["month"]),
                "day": day,
                "year": h["year"],
                "title": "",
                "description": "",
                "full_day": True,
                "recurring": False,
                "real_date": date.today(),
            }))
        return _open_modal
    _make_handler()

# Save from modal
@reactive.Effect
@reactive.event(ui.input("ev_save"))
async def _save_event():
    # Collect + validate values
    try:
        mname = ui.input("ev_month")()
        rec: Dict[str, Any] = {
            "month_name": mname,
            "month": _month_index_from_name(mname),
            "day": int(ui.input("ev_day")() or 1),
            "year": int(ui.input("ev_year")() or 1492),
            "title": (ui.input("ev_title")() or "").strip(),
            "description": (ui.input("ev_desc")() or "").strip(),
            "real_date": _iso(ui.input("ev_real_date")()),
            "full_day": bool(ui.input("ev_full_day")()),
            "recurring": bool(ui.input("ev_recurring")()),
        }
    except Exception as e:
        ui.notification_show(f"Invalid form values: {e!s}", type="error")
        return

    if not rec["title"]:
        ui.notification_show("Please enter a title.", type="warning")
        return

    # Upsert via supabase client (sync -> off-thread)
    def _q():
        return db.client.table(db.events_table).upsert(rec).execute()

    try:
        await anyio.to_thread.run_sync(_q)
    except Exception as e:
        print("[App] upsert_event failed:", repr(e))
        ui.notification_show("Save failed (see logs / RLS).", type="error")
        return

    ui.modal_remove()
    await reload_events()
    ui.notification_show("Event saved.", type="message")

# ------------ App ------------------------------------------------------------

app = App(page, server=None, static_assets=ASSETS_DIR)
