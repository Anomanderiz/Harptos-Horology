# app.py
# ------------------------------------------------------------------------------
# Harptos – Campaign Calendar (Shiny for Python)
# Clean, deploy-ready build (no intercalaries; 12 × 30 days)
# ------------------------------------------------------------------------------
from __future__ import annotations

import os
from datetime import date
from typing import List, Dict, Any, Optional, TypedDict

from shiny import App, ui, render, reactive
import anyio

from supa import SupaClient, HarptosDate

# ---------------- Config / constants -----------------------------------------

# 12 months (30 days each)
MONTHS: List[str] = [
    "Hammer, Deepwinter",
    "Alturiak, The Claw of Winter",
    "Ches, The Claw of the Sunsets",
    "Tarsakh, The Claw of the Storms",
    "Mirtul, The Melting",
    "Kythorn, The Time of Flowers",
    "Flamerule, Summertide",
    "Eleasis, Highsun",
    "Eleint, The Fading",
    "Marpenoth, Leaffall",
    "Uktar, The Rotting",
    "Nightal, The Drawing Down",
]
DAYS_PER_MONTH = 30

# Absolute path to /www for static assets (CSS, images)
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "www")

# ---------------- Utilities ---------------------------------------------------

def _month_name_from_index(idx: int) -> str:
    if 1 <= idx <= len(MONTHS):
        return MONTHS[idx - 1]
    return "Hammer, Deepwinter"

def _map_date_to_harptos(d: date) -> HarptosDate:
    """Map real day-of-year to a 360-day Harptos calendar (no intercalaries)."""
    doy = d.timetuple().tm_yday
    idx = ((doy - 1) % 360) + 1       # 1..360
    month = ((idx - 1) // DAYS_PER_MONTH) + 1
    day = ((idx - 1) % DAYS_PER_MONTH) + 1
    return {"year": 1492, "month": month, "day": day}

def _iso(d: Optional[date]) -> Optional[str]:
    try:
        return d.isoformat() if d else None
    except Exception:
        return None

# ---------------- Shared state ------------------------------------------------

db = SupaClient()

current: reactive.Value[Optional[HarptosDate]] = reactive.Value(None)
today_harptos: reactive.Value[Optional[HarptosDate]] = reactive.Value(None)
events: reactive.Value[List[Dict[str, Any]]] = reactive.Value([])

selected_day: reactive.Value[Optional[int]] = reactive.Value(None)

# ---------------- Reusable UI bits -------------------------------------------

def day_button(day: int) -> ui.TagChild:
    return ui.input_action_button(
        f"day_{day}", f"{day}", class_="btn btn-outline-light day-btn"
    )

def calendar_grid() -> ui.TagChild:
    # 6 rows × 5 columns (30 days)
    rows: List[ui.TagChild] = []
    for r in range(6):
        start = r * 5 + 1
        btns = [day_button(d) for d in range(start, min(start + 5, DAYS_PER_MONTH + 1))]
        rows.append(ui.div(*btns, class_="d-flex gap-2 mb-2"))
    return ui.div(*rows, class_="calendar-grid")

def event_modal_ui(day: int, default: Optional[HarptosDate] = None) -> ui.TagChild:
    d = default or {"year": 1492, "month": 1, "day": day}
    return ui.modal(
        ui.h5(f"Add / Edit Event — Day {day}"),
        ui.row(
            ui.input_select(
                "ev_month", "Month", choices=MONTHS,
                selected=_month_name_from_index(d.get("month", 1)),
            ),
            ui.input_numeric("ev_day", "Day", value=d.get("day", day), min=1, max=DAYS_PER_MONTH),
            ui.input_numeric("ev_year", "Year", value=d.get("year", 1492)),
        ),
        ui.input_text("ev_title", "Title", value=""),
        ui.input_text_area("ev_desc", "Description", value=""),
        ui.input_date("ev_real_date", "Real-world date", value=date.today()),
        footer=ui.div(
            ui.input_action_button("ev_save", "Save", class_="btn btn-primary me-2"),
            ui.input_action_button("ev_cancel", "Cancel", class_="btn btn-secondary"),
        ),
        easy_close=True,
        size="l",
    )

# ---------------- Page layout -------------------------------------------------

page = ui.page_fluid(
    ui.head_content(ui.tags.link(rel="stylesheet", href="styles.css")),
    ui.div(
        # Top bar
        ui.div(ui.h4("Harptos Horology", class_="mb-0")),
        ui.div(
            ui.output_text("current_date_label"),
            class_="ms-auto text-on-dark"
        ),
        ui.div(
            ui.input_action_button("btn_set_current", "Set Current Date"),
            ui.input_action_button("btn_jump_today", "Jump to Today"),
            ui.input_action_button("btn_refresh_events", "Refresh Events"),
            class_="d-flex gap-2"
        ),
        class_="navbar d-flex align-items-center gap-3 flex-wrap"
    ),
    ui.div(
        ui.card(
            ui.card_header("Current Month"),
            calendar_grid(),
            class_="glass"
        ),
        class_="container mt-3"
    ),
)

# ---------------- Server ------------------------------------------------------

def server(input, output, session):
    async def reload_events():
        rows = await db.load_events()
        events.set(rows or [])

    # On start: load current date, compute 'today', preload events
    @reactive.Effect
    async def _init():
        st = await db.get_state_value("current_date", default=None)
        if isinstance(st, dict):
            try:
                current.set({
                    "year": int(st.get("year", 1492)),
                    "month": int(st.get("month", 1)),
                    "day": int(st.get("day", 1)),
                })
            except Exception:
                current.set({"year": 1492, "month": 1, "day": 1})
        else:
            current.set({"year": 1492, "month": 1, "day": 1})

        today_harptos.set(_map_date_to_harptos(date.today()))
        await reload_events()

    # Header label
    @render.text
    def current_date_label():
        h = current.get()
        if not h:
            return "—"
        return f"{_month_name_from_index(h['month'])} {h['day']}, {h['year']}"

    # Set current date -> persist to state table
    @reactive.Effect
    @reactive.event(input.btn_set_current)
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

    # Jump to today (computed mapping)
    @reactive.Effect
    @reactive.event(input.btn_jump_today)
    def _jump_to_today():
        t = today_harptos.get()
        if not t:
            ui.notification_show("No ‘today’ available yet.", type="warning")
            return
        current.set(t)

    # Refresh events from DB
    @reactive.Effect
    @reactive.event(input.btn_refresh_events)
    async def _refresh_events():
        await reload_events()
        ui.notification_show("Events refreshed.", type="message")

    # Generate day button handlers
    for _d in range(1, DAYS_PER_MONTH + 1):
        def _make_handler(day=_d):
            @reactive.Effect
            @reactive.event(getattr(input, f"day_{day}"))
            def _open_modal():
                selected_day.set(day)
                h = current.get() or {"year": 1492, "month": 1, "day": day}
                ui.modal_show(event_modal_ui(day, h))
        _make_handler()

    # Modal cancel
    @reactive.Effect
    @reactive.event(input.ev_cancel)
    def _cancel_modal():
        ui.modal_remove()

    # Modal save
    @reactive.Effect
    @reactive.event(input.ev_save)
    async def _save_event():
        day = selected_day.get()
        h = current.get()
        if not h or not day:
            ui.notification_show("No day selected.", type="warning")
            return

        # Collect modal inputs
        month_name = input.ev_month()
        try:
            month_index = MONTHS.index(month_name) + 1
        except ValueError:
            month_index = h["month"]

        rec = {
            "year": int(input.ev_year() or h["year"]),
            "month": int(input.ev_day() and month_index or h["month"]),
            "day": int(input.ev_day() or day),
            "title": (input.ev_title() or "").strip() or None,
            "notes": (input.ev_desc() or "").strip() or None,
            "real_world_date": _iso(input.ev_real_date()),
        }

        # Upsert via Supabase (thread off the blocking call)
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

# ---------------- Create app --------------------------------------------------

app = App(page, server=server, static_assets=ASSETS_DIR)
