# app.py
# ------------------------------------------------------------------------------
# Harptos – Year-at-a-glance calendar (Shiny for Python)
# - Full 12-month grid like the screenshot
# - Intercalaries shown as a labelled "31" in 1, 4, 7, 9, 11
# - Current date highlighted green; click any day to select & open modal
# - Supabase event save (with generated 64-bit ID)
# ------------------------------------------------------------------------------

from __future__ import annotations

import json
import os
from datetime import date
from typing import Any, Dict, List, Optional

import anyio
from shiny import App, reactive, render, ui

from supa import SupaClient, HarptosDate, generate_event_id

# ---------- Constants ---------------------------------------------------------

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

# Intercalary festivals per FR canon
FESTIVALS: Dict[int, str] = {
    1: "Midwinter",
    4: "Greengrass",
    7: "Midsummer",
    9: "Highharvestide",
    11: "Feast of the Moon",
}

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "www")

# ---------- Optional markers (e.g., moon phases) -----------------------------
# If you place a JSON file at www/moon_markers.json with:
# { "new":[{"month":1,"day":1}, ...], "full":[{"month":1,"day":16}, ...] }
# we’ll draw small pips on those dates.
def load_markers() -> Dict[str, List[Dict[str, int]]]:
    src = os.path.join(ASSETS_DIR, "moon_markers.json")
    if os.path.exists(src):
        try:
            with open(src, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                return {
                    "new": list(data.get("new", [])),
                    "full": list(data.get("full", [])),
                }
        except Exception as e:
            print("[App] moon_markers.json load failed:", repr(e))
    return {"new": [], "full": []}

# ---------- Utils ------------------------------------------------------------

def month_name(idx: int) -> str:
    return MONTHS[idx - 1] if 1 <= idx <= 12 else MONTHS[0]

def _iso(d: Optional[date]) -> Optional[str]:
    try:
        return d.isoformat() if d else None
    except Exception:
        return None

# Simple mapping for "Jump to Today" (360-day wrap, ignores intercalaries)
def map_real_to_harptos(d: date) -> HarptosDate:
    doy = d.timetuple().tm_yday
    idx = ((doy - 1) % 360) + 1
    month = ((idx - 1) // DAYS_PER_MONTH) + 1
    day = ((idx - 1) % DAYS_PER_MONTH) + 1
    return {"year": 1492, "month": month, "day": day}

# ---------- Shared state -----------------------------------------------------

db = SupaClient()

current: reactive.Value[Optional[HarptosDate]] = reactive.Value(None)
today_h: reactive.Value[Optional[HarptosDate]] = reactive.Value(None)
events: reactive.Value[List[Dict[str, Any]]] = reactive.Value([])
markers: reactive.Value[Dict[str, List[Dict[str, int]]]] = reactive.Value({"new": [], "full": []})

# ---------- UI builders ------------------------------------------------------

def pip_for_day(m: int, d: int) -> ui.TagChild | None:
    """Return a pip span if day (m,d) is in markers."""
    ms = markers.get()
    has_new = any(x["month"] == m and x["day"] == d for x in ms.get("new", []))
    has_full = any(x["month"] == m and x["day"] == d for x in ms.get("full", []))
    if not (has_new or has_full):
        return None

    # Choose class: new => light pip; full => dark pip. If both, show both side-by-side.
    spans: List[ui.TagChild] = []
    if has_new:
        spans.append(ui.span(class_="pip pip-new", title="New Moon"))
    if has_full:
        spans.append(ui.span(class_="pip pip-full", title="Full Moon"))
    return ui.span(*spans, class_="pip-wrap")

def day_cell(m: int, d: int, highlight: bool) -> ui.TagChild:
    """One numbered day as a button with optional highlight and markers."""
    pid = f"m{m}_d{d}"
    classes = ["day-btn", "btn", "btn-outline-light"]
    if highlight:
        classes.append("day-current")
    return ui.div(
        ui.input_action_button(pid, str(d), class_=" ".join(classes)),
        pip_for_day(m, d),
        class_="day-cell"
    )

def festival_cell(m: int) -> ui.TagChild:
    """Optional '31' festival cell shown under each month that has one."""
    label = FESTIVALS.get(m)
    if not label:
        return ui.div()  # empty spacer
    pid = f"m{m}_d31"
    return ui.div(
        ui.div(
            ui.input_action_button(pid, "31", class_="btn btn-outline-light day-btn"),
            ui.div(label, class_="festival-label"),
            class_="festival-wrap",
        ),
        class_="day-cell festival-cell"
    )

def month_card(m: int, cur: Optional[HarptosDate]) -> ui.TagChild:
    """Card with header and 3 rows of 10 days + festival label."""
    hlt = (lambda d: bool(cur and cur["month"] == m and cur["day"] == d))
    # three rows of 10
    rows: List[ui.TagChild] = []
    for r in range(3):
        start = r * 10 + 1
        row_days = [day_cell(m, d, hlt(d)) for d in range(start, start + 10)]
        rows.append(ui.div(*row_days, class_="day-row"))
    # festival row
    rows.append(ui.div(festival_cell(m), class_="festival-row"))
    return ui.card(
        ui.card_header(f"{month_name(m)} 1492"),
        *rows,
        class_="month-card glass"
    )

# ---------- Page -------------------------------------------------------------

page = ui.page_fluid(
    ui.head_content(ui.tags.link(rel="stylesheet", href="styles.css")),
    ui.div(
        ui.div(ui.h4("Harptos Horology", class_="mb-0")),
        ui.div(ui.output_text("current_date_label"), class_="ms-auto text-on-dark"),
        ui.div(
            ui.input_action_button("btn_set_current", "Save Current Date"),
            ui.input_action_button("btn_jump_today", "Jump to Today"),
            ui.input_action_button("btn_refresh_events", "Refresh Events"),
            class_="d-flex gap-2"
        ),
        class_="navbar d-flex align-items-center gap-3 flex-wrap"
    ),
    ui.div(
        ui.output_ui("calendar"),
        class_="year-grid container"
    ),
)

# ---------- Server -----------------------------------------------------------

def server(input, output, session):

    async def reload_events():
        rows = await db.load_events()
        events.set(rows or [])

    @reactive.Effect
    async def _init():
        # load persisted current date
        st = await db.get_state_value("current_date", default=None)
        if isinstance(st, dict):
            try:
                current.set({"year": int(st["year"]), "month": int(st["month"]), "day": int(st["day"])})
            except Exception:
                current.set({"year": 1492, "month": 1, "day": 1})
        else:
            current.set({"year": 1492, "month": 1, "day": 1})

        today_h.set(map_real_to_harptos(date.today()))
        markers.set(load_markers())
        await reload_events()

    @render.text
    def current_date_label():
        h = current.get()
        if not h:
            return "—"
        s = f"{month_name(h['month'])} {h['day']}, {h['year']}"
        return s

    @render.ui
    def calendar():
        h = current.get()
        grid = [month_card(m, h) for m in range(1, 13)]
        # 4 columns × 3 rows visually achieved in CSS grid
        return ui.div(*grid, class_="months-wrap")

    # Persist current to Supabase state
    @reactive.Effect
    @reactive.event(input.btn_set_current)
    async def _persist_current():
        h = current.get()
        if not h:
            ui.notification_show("Nothing to save yet.", type="warning")
            return
        ok = await db.set_state("current_date", h)
        if ok:
            ui.notification_show("Current date saved.", type="message")
        else:
            ui.notification_show("Failed saving current date (check RLS).", type="error")

    # Jump to today mapping
    @reactive.Effect
    @reactive.event(input.btn_jump_today)
    def _jtoday():
        t = today_h.get()
        if t:
            current.set(t)

    @reactive.Effect
    @reactive.event(input.btn_refresh_events)
    async def _re():
        await reload_events()
        ui.notification_show("Events refreshed.", type="message")

    # Generate handlers for every day (including festival '31' buttons)
    def make_day_handler(m: int, d: int):
        trigger = getattr(input, f"m{m}_d{d}")
        @reactive.Effect
        @reactive.event(trigger)
        def _on_click():
            # select the day and open the add/edit modal
            current.set({"year": 1492, "month": m, "day": d})
            ui.modal_show(event_modal_ui(m, d))

    for m in range(1, 13):
        for d in range(1, DAYS_PER_MONTH + 1):
            make_day_handler(m, d)
        if m in FESTIVALS:
            make_day_handler(m, 31)

    # Modal UI + save/cancel
    def event_modal_ui(m: int, d: int) -> ui.TagChild:
        h = current.get() or {"year": 1492, "month": m, "day": d}
        return ui.modal(
            ui.h5(f"Add / Edit Event — {month_name(m)} {d}, {h['year']}"),
            ui.row(
                ui.input_select("ev_month", "Month", choices=MONTHS, selected=month_name(m)),
                ui.input_numeric("ev_day", "Day", value=d, min=1, max=31),
                ui.input_numeric("ev_year", "Year", value=h["year"]),
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

    @reactive.Effect
    @reactive.event(input.ev_cancel)
    def _cancel():
        ui.modal_remove()

    @reactive.Effect
    @reactive.event(input.ev_save)
    async def _save():
        # collect modal inputs
        mname = input.ev_month()
        try:
            m = MONTHS.index(mname) + 1
        except ValueError:
            m = (current.get() or {"month": 1})["month"]
        d = int(input.ev_day() or (current.get() or {"day": 1})["day"])
        y = int(input.ev_year() or 1492)
        title = (input.ev_title() or "").strip() or None
        notes = (input.ev_desc() or "").strip() or None
        rdate = _iso(input.ev_real_date())

        rec = {
            "id": generate_event_id(),
            "year": y,
            "month": m,
            "day": d,
            "title": title,
            "notes": notes,
            "real_world_date": rdate,
            # If your table has is_holiday boolean default false, leaving it out is fine.
        }

        # upsert on id (safe even if user spam-clicks Save)
        try:
            await anyio.to_thread.run_sync(lambda: db.upsert_event(rec))
        except Exception as e:
            print("[App] upsert_event failed:", repr(e))
            ui.notification_show("Save failed (see logs / RLS).", type="error")
            return

        ui.modal_remove()
        await reload_events()
        ui.notification_show("Event saved.", type="message")

# ---------- Create App -------------------------------------------------------

app = App(page, server=server, static_assets=ASSETS_DIR)
