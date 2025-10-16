from __future__ import annotations

import os
import math
from datetime import datetime, timedelta, timezone, date
from typing import Dict, Any

from shiny import App, reactive, render, ui, Session
from shiny.types import ImgData
from htmltools import HTML
from pathlib import Path

# --- Supabase helper ---------------------------------------------------------
from supa import SupaClient, HarptosDate, step_harptos

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY", os.getenv("SUPABASE_KEY", ""))

db = SupaClient(SUPABASE_URL, SUPABASE_KEY)

# --- Harptos basics (no intercalaries) --------------------------------------
MONTHS = [
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
APP_DIR = Path(__file__).resolve().parent
app = App(page, server, static_assets=str(APP_DIR / "www"))

def harptos_to_ordinal(h: HarptosDate) -> int:
    return (h["year"] * 360) + (h["month"] - 1) * 30 + (h["day"] - 1)

def ordinal_to_harptos(n: int) -> HarptosDate:
    year = n // 360
    dyear = n % 360
    month = dyear // 30 + 1
    day = dyear % 30 + 1
    return {"year": year, "month": month, "day": day}

# --- UI fragments ------------------------------------------------------------

def day_cell(month_idx: int, day: int, current: HarptosDate, has_event: bool) -> HTML:
    classes = ["day"]
    if current["month"] == month_idx and current["day"] == day:
        classes.append("current")
    if has_event:
        classes.append("has-event")
    # Custom data attrs; clicking is handled by JS to set Shiny input 'clicked_day'
    id_value = f"d-{month_idx}-{day}"
    return ui.div(
        {"class": " ".join(classes), "data-month": month_idx, "data-day": day, "id": id_value},
        str(day)
    )

def month_grid(month_idx: int, current: HarptosDate, events_index: Dict[str, int]) -> HTML:
    # events_index key "m-d" -> count
    cells = []
    for d in range(1, DAYS_PER_MONTH + 1):
        key = f"{month_idx}-{d}"
        has_ev = key in events_index and events_index[key] > 0
        cells.append(day_cell(month_idx, d, current, has_ev))
    return ui.div(
        {"class": "month"},
        ui.div({"class": "month-title"}, MONTHS[month_idx-1]),
        ui.div({"class": "grid"}, *cells),
    )

# --- Application state -------------------------------------------------------

def default_current_date() -> HarptosDate:
    # If no state in DB, start at 1492 Alturiak 3 (arbitrary but sensible)
    return {"year": 1492, "month": 2, "day": 3}

# --- Build UI ----------------------------------------------------------------

def build_ui():
    return ui.page_fluid(
        ui.tags.link(rel="stylesheet", href="styles.css"),
        # Inject JS to capture clicks on day cells and push to Shiny input
        ui.tags.script(
            """
            document.addEventListener('click', (ev) => {
              const el = ev.target.closest('.day');
              if (!el) return;
              const m = parseInt(el.dataset.month);
              const d = parseInt(el.dataset.day);
              // forward to shiny
              Shiny.setInputValue('clicked', {month: m, day: d, nonce: Math.random()});
            });
            """
        ),
        ui.layout_columns(
            ui.card(
                ui.card_header("Harptos – Campaign Calendar"),
                ui.row(
                    ui.column(3, ui.input_action_button("set_current", "Set Current Date", class_="btn-primary")),
                    ui.column(3, ui.input_action_button("today_btn", "Jump to Today")),
                    ui.column(3, ui.input_action_button("refresh", "Refresh Events")),
                    ui.column(3, ui.output_text("current_lbl")),
                ),
                ui.div({"class": "year-grid"}, ui.output_ui("calendar"))
            ),
            col_widths={"sm": (12,)},
        ),
        # Hidden modal containers via outputs
        ui.output_ui("modal_region"),
    )

page = build_ui()

# --- Server ------------------------------------------------------------------

def server(input, output, session: Session):
    # Reactive: current date (server-truth), pulled/saved in Supabase 'state' table
    current = reactive.Value(default_current_date())

    # Load current date and events at startup
    @reactive.effect
    async def _init():
        st = await db.get_state("current_date")
        if st is not None and isinstance(st, dict):
            current.set(HarptosDate(year=int(st.get("year", 1492)), month=int(st.get("month", 1)), day=int(st.get("day", 1))))
        # Ensure auto-advance check once at start
        await maybe_advance_date()

    # Poll every 10 minutes to auto-advance Harptos by +1 day per real day
    @reactive.poll(lambda: 600000)  # 600k ms = 10 minutes
    async def tick():
        await maybe_advance_date()

    async def maybe_advance_date():
        # Last realworld date stored in state 'last_checked'
        last = await db.get_state("last_checked")
        today = date.today().isoformat()
        if last is None or last != today:
            # How many days difference since last check?
            # If last is None -> set last to today and +0
            if last is not None:
                # advance +1 for each missed real day
                c = current.get()
                c_ord = harptos_to_ordinal(c)
                # crude diff: assume last is iso date
                try:
                    d_last = datetime.fromisoformat(last).date()
                except Exception:
                    d_last = date.today()
                delta_days = (date.today() - d_last).days
                if delta_days < 0:
                    delta_days = 0
                for _ in range(delta_days):
                    c = step_harptos(c, MONTHS, DAYS_PER_MONTH)
                current.set(c)
                await db.set_state("current_date", c)
            await db.set_state("last_checked", today)

    # Events cache
    events = reactive.Value([])  # list of dict rows

    async def reload_events():
        rows = await db.load_events()
        events.set(rows or [])

    @reactive.effect
    async def _load_events_once():
        await reload_events()

    def build_events_index():
        idx: Dict[str, int] = {}
        for r in events.get():
            key = f"{int(r['month'])}-{int(r['day'])}"
            idx[key] = idx.get(key, 0) + 1
        return idx

    @output
    @render.text
    def current_lbl():
        c = current.get()
        return f"Current date: {MONTHS[c['month']-1]} {c['day']}, {c['year']}"

    @output
    @render.ui
    def calendar():
        c = current.get()
        ev_idx = build_events_index()
        months = [month_grid(i+1, c, ev_idx) for i in range(12)]
        # Arrange months in a 3x4 grid
        return ui.div({"class": "calendar"}, *months)

    # Handle clicks on days -> open modal for add/list events
    @reactive.effect
    @reactive.event(input.clicked)
    def _open_modal():
        payload = input.clicked()
        if not payload:
            return
        m = int(payload["month"])
        d = int(payload["day"])
        show_day_modal(m, d)

    def show_day_modal(month: int, day: int, edit_row: Dict[str, Any] | None = None):
        title = f"Create / Edit Events — {MONTHS[month-1]} {day}, {current.get()['year']}"
        # Filter existing events for that day
        todays = [r for r in events.get() if int(r["month"]) == month and int(r["day"]) == day and int(r["year"]) == current.get()["year"]]
        # Build a simple table of existing events
        table = ui.div()
        if todays:
            rows = []
            for r in todays:
                rows.append(
                    ui.tr(
                        ui.td(r.get("title") or "(untitled)"),
                        ui.td(r.get("real_world_date") or ""),
                        ui.td(ui.input_action_button(f"edit_{r['id']}", "Edit")),
                        ui.td(ui.input_action_button(f"delete_{r['id']}", "Delete", class_="btn-danger btn-sm"))
                    )
                )
            table = ui.table({"class": "events-table"},
                ui.tr(ui.th("Title"), ui.th("Real World Date"), ui.th(), ui.th()),
                *rows
            )
        modal = ui.modal(
            ui.row(
                ui.column(4, ui.input_select("modal_month", "Month", {i+1: MONTHS[i] for i in range(12)}, selected=month)),
                ui.column(3, ui.input_numeric("modal_day", "Day", day, min=1, max=30)),
                ui.column(3, ui.input_numeric("modal_year", "Year", current.get()["year"])),
            ),
            ui.input_text("modal_title", "Title"),
            ui.input_text_area("modal_desc", "Notes", height="120px"),
            ui.input_date("modal_real", "Real World Date"),
            ui.row(
                ui.column(3, ui.input_checkbox("modal_hidden", "Hidden", False)),
                ui.column(4, ui.input_checkbox("modal_mark_current", "Set as Current Date", False)),
            ),
            ui.hr(),
            ui.h6("Existing events"),
            table,
            footer=ui.div(
                ui.input_action_button("modal_save", "Save", class_="btn-primary"),
                ui.input_action_button("modal_close", "Close"),
            ),
            title=title,
            easy_close=True,
            size="l",
        )
        ui.modal_show(modal)

    @reactive.effect
    @reactive.event(input.modal_close)
    def _close():
        ui.modal_remove()

    @reactive.effect
    @reactive.event(input.modal_save)
    async def _save():
        m = int(input.modal_month())
        d = int(input.modal_day())
        y = int(input.modal_year())
        row = {
            "year": y,
            "month": m,
            "day": d,
            "title": input.modal_title() or None,
            "notes": input.modal_desc() or None,
            "real_world_date": input.modal_real() or None,
            "hidden": bool(input.modal_hidden() or False),
        }
        await db.add_event(row)
        if bool(input.modal_mark_current() or False):
            current.set({"year": y, "month": m, "day": d})
            await db.set_state("current_date", current.get())
        ui.modal_remove()
        await reload_events()

    # Hook dynamic delete/edit buttons
    @reactive.effect
    def _hook_row_buttons():
        for r in events.get():
            del_id = f"delete_{r['id']}"
            if session.input(del_id) is not None:
                @reactive.Effect(priority=1)  # ensure separate closure binding
                @reactive.event(session.input(del_id))
                async def _del(row_id=r['id']):
                    await db.delete_event(row_id)
                    await reload_events()

            edit_id = f"edit_{r['id']}"
            if session.input(edit_id) is not None:
                @reactive.Effect(priority=1)
                @reactive.event(session.input(edit_id))
                def _edit(row=r):
                    show_day_modal(int(row["month"]), int(row["day"]))

    # Set current date manually
    @reactive.effect
    @reactive.event(input.set_current)
    def _open_set_current():
        c = current.get()
        ui.modal_show(
            ui.modal(
                ui.input_select("set_month", "Month", {i+1: MONTHS[i] for i in range(12)}, selected=c["month"]),
                ui.input_numeric("set_day", "Day", c["day"], min=1, max=30),
                ui.input_numeric("set_year", "Year", c["year"]),
                footer=ui.div(
                    ui.input_action_button("save_current", "Save", class_="btn-primary"),
                    ui.input_action_button("cancel_current", "Cancel"),
                ),
                title="Set Current Date",
                easy_close=True
            )
        )

    @reactive.effect
    @reactive.event(input.cancel_current)
    def _cancel_current():
        ui.modal_remove()

    @reactive.effect
    @reactive.event(input.save_current)
    async def _save_current():
        c = {"month": int(input.set_month()), "day": int(input.set_day()), "year": int(input.set_year())}
        current.set(c)
        await db.set_state("current_date", c)
        ui.modal_remove()

    @reactive.effect
    @reactive.event(input.today_btn)
    def _today():
        # no-op for now; just scroll to the current element
        ui.update_action_button("today_btn", label="Today ✓")

    @reactive.effect
    @reactive.event(input.refresh)
    async def _refresh():
        await reload_events()

app = App(page, server, static_assets="www")
