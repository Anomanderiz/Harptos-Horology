# app.py
# ------------------------------------------------------------------------------
# Harptos – Year-at-a-glance calendar (Shiny for Python)
# - 3×10 layout per month with intercalary "31" labels
# - Manual Current Date controls (+ save) and Advance +1 Day (+ auto daily tick)
# - Day click opens a "Day Details" modal that lists existing events for that day
#   with an "Add New Event" button to open a labelled Add/Edit Event form
# - Events use UUID4 ids (Postgres UUID)
# ------------------------------------------------------------------------------

from __future__ import annotations

import json
import os
from datetime import date
from typing import Any, Dict, List, Optional

import anyio
from shiny import App, reactive, render, ui

from supa import SupaClient, HarptosDate, generate_event_id  # UUID4 id generator

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

FESTIVALS: Dict[int, str] = {
    1: "Midwinter",
    4: "Greengrass",
    7: "Midsummer",
    9: "Highharvestide",
    11: "Feast of the Moon",
}

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "www")

# ---------- Optional markers (moon phases) -----------------------------------

def load_markers() -> Dict[str, List[Dict[str, int]]]:
    """
    Optional: place www/moon_markers.json with
    { "new":[{"month":1,"day":1},...], "full":[{"month":1,"day":16},...] }
    """
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

def advance_one(h: HarptosDate) -> HarptosDate:
    """Advance one day with intercalaries on months 1/4/7/9/11 at day 31."""
    y, m, d = h["year"], h["month"], h["day"]
    if d == 31:
        m += 1
        if m > 12:
            m = 1
            y += 1
        return {"year": y, "month": m, "day": 1}
    if 1 <= d < 30:
        return {"year": y, "month": m, "day": d + 1}
    if d == 30:
        if m in FESTIVALS:
            return {"year": y, "month": m, "day": 31}
        m += 1
        if m > 12:
            m = 1
            y += 1
        return {"year": y, "month": m, "day": 1}
    return {"year": y, "month": 1, "day": 1}

# ---------- Shared state -----------------------------------------------------

db = SupaClient()

current: reactive.Value[Optional[HarptosDate]] = reactive.Value(None)
events: reactive.Value[List[Dict[str, Any]]] = reactive.Value([])
markers: reactive.Value[Dict[str, List[Dict[str, int]]]] = reactive.Value({"new": [], "full": []})

# remember which y/m/d the modal is for
selected_date: reactive.Value[Optional[HarptosDate]] = reactive.Value(None)

# ---------- UI builders ------------------------------------------------------

def pip_for_day(m: int, d: int) -> ui.TagChild | None:
    ms = markers.get()
    has_new = any(x["month"] == m and x["day"] == d for x in ms.get("new", []))
    has_full = any(x["month"] == m and x["day"] == d for x in ms.get("full", []))
    if not (has_new or has_full):
        return None
    spans: List[ui.TagChild] = []
    if has_new:
        spans.append(ui.span(class_="pip pip-new", title="New Moon"))
    if has_full:
        spans.append(ui.span(class_="pip pip-full", title="Full Moon"))
    return ui.span(*spans, class_="pip-wrap")

def day_cell(m: int, d: int, highlight: bool) -> ui.TagChild:
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
    label = FESTIVALS.get(m)
    if not label:
        return ui.div()
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
    view_year = (cur or {"year": 1492})["year"]
    hlt = (lambda d: bool(cur and cur["month"] == m and cur["day"] == d))
    rows: List[ui.TagChild] = []
    for r in range(3):
        start = r * 10 + 1
        row_days = [day_cell(m, d, hlt(d)) for d in range(start, start + 10)]
        rows.append(ui.div(*row_days, class_="day-row"))
    rows.append(ui.div(festival_cell(m), class_="festival-row"))
    return ui.card(
        ui.card_header(f"{month_name(m)} {view_year}"),
        *rows,
        class_="month-card glass"
    )

def events_for_day(y: int, m: int, d: int) -> List[Dict[str, Any]]:
    all_rows = events.get() or []
    return [r for r in all_rows if int(r.get("year", 0)) == y and int(r.get("month", 0)) == m and int(r.get("day", 0)) == d]

def day_details_modal(y: int, m: int, d: int) -> ui.TagChild:
    day_rows = events_for_day(y, m, d)
    cards: List[ui.TagChild] = []
    if not day_rows:
        cards.append(ui.div("No events saved for this day.", class_="muted mb-2"))
    else:
        for r in day_rows:
            title = r.get("title") or "(Untitled)"
            notes = r.get("notes") or ""
            rw = r.get("real_world_date") or "Unknown Real Date"
            cards.append(
                ui.div(
                    ui.div(title, class_="event-title"),
                    ui.div(rw, class_="event-date"),
                    ui.div(notes, class_="event-notes"),
                    class_="event-card"
                )
            )

    return ui.modal(
        ui.h5(f"{month_name(m)} {d}, {y}", class_="mb-3"),
        *cards,
        ui.div(
            ui.input_action_button("ev_add_new", "Add New Event", class_="btn btn-success"),
            ui.input_action_button("ev_list_close", "Close", class_="btn btn-secondary ms-2"),
            class_="mt-3"
        ),
        easy_close=True,
        size="l",
    )

def event_form_modal(y: int, m: int, d: int, title_val: str = "", notes_val: str = "", rw_date: Optional[date] = None) -> ui.TagChild:
    """Labelled Add/Edit form."""
    if rw_date is None:
        rw_date = date.today()
    return ui.modal(
        ui.h5("Add / Edit Event", class_="mb-3"),
        ui.row(
            ui.input_select("ev_month", "Month", choices=MONTHS, selected=month_name(m)),
            ui.input_numeric("ev_day", "Day", value=d, min=1, max=31),
            ui.input_numeric("ev_year", "Year", value=y),
        ),
        ui.input_text("ev_title", "Title", value=title_val),
        ui.input_text_area("ev_desc", "Description", value=notes_val),
        ui.input_date("ev_real_date", "Real-World Date", value=rw_date),
        footer=ui.div(
            ui.input_action_button("ev_save", "Save", class_="btn btn-primary me-2"),
            ui.input_action_button("ev_cancel", "Cancel", class_="btn btn-secondary"),
        ),
        easy_close=True,
        size="l",
    )

# ---------- Page -------------------------------------------------------------

page = ui.page_fluid(
    ui.head_content(ui.tags.link(rel="stylesheet", href="styles.css")),
    ui.div(
        ui.div(ui.h4("Harptos Horology", class_="mb-0")),
        ui.div(ui.output_text("current_date_label"), class_="ms-auto text-on-dark"),
        class_="navbar d-flex align-items-center gap-3 flex-wrap"
    ),
    ui.div(
        ui.card(
            ui.card_header("Current Date Controls"),
            ui.row(
                ui.input_select("set_month", "Month", choices=MONTHS, selected=MONTHS[0]),
                ui.input_numeric("set_day", "Day", value=1, min=1, max=31),
                ui.input_numeric("set_year", "Year", value=1492),
                ui.div(
                    ui.input_action_button("btn_apply_current", "Set Current Date"),
                    ui.input_action_button("btn_save_current", "Save Current Date"),
                    ui.input_action_button("btn_advance_one", "Advance +1 Day"),
                    ui.input_action_button("btn_refresh_events", "Refresh Events"),
                    class_="d-flex gap-2 mt-1"
                ),
            ),
            class_="glass"
        ),
        class_="container mt-3"
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

    # guard for timer
    auto_state = {"started": False}

    @reactive.Effect
    async def _init():
        # load persisted current date
        st = await db.get_state_value("current_date", default=None)
        if isinstance(st, dict):
            try:
                current.set({"year": int(st["year"]), "month": int(st["month"]), "day": int(st["day"])})
                session.send_input_message("set_month", {"value": month_name(int(st["month"]))})
                session.send_input_message("set_day", {"value": int(st["day"])})
                session.send_input_message("set_year", {"value": int(st["year"])})
            except Exception:
                current.set({"year": 1492, "month": 1, "day": 1})
        else:
            current.set({"year": 1492, "month": 1, "day": 1})

        markers.set(load_markers())
        await reload_events()

    # auto daily +1
    @reactive.Effect
    async def _auto_tick():
        reactive.invalidate_later(86_400_000)
        if not auto_state["started"]:
            auto_state["started"] = True
            return
        h = current.get()
        if not h:
            return
        new_h = advance_one(h)
        current.set(new_h)
        await db.set_state("current_date", new_h)

    @render.text
    def current_date_label():
        h = current.get()
        if not h:
            return "—"
        return f"{month_name(h['month'])} {h['day']}, {h['year']}"

    @render.ui
    def calendar():
        h = current.get()
        grid = [month_card(m, h) for m in range(1, 13)]
        return ui.div(*grid, class_="months-wrap")

    # Manual current-date controls
    @reactive.Effect
    @reactive.event(input.btn_apply_current)
    def _apply_current():
        try:
            m = MONTHS.index(input.set_month()) + 1
        except ValueError:
            m = 1
        d = int(input.set_day() or 1)
        y = int(input.set_year() or 1492)
        if d < 1: d = 1
        if d > 31: d = 31
        if d == 31 and m not in FESTIVALS:
            d = 30
        current.set({"year": y, "month": m, "day": d})

    @reactive.Effect
    @reactive.event(input.btn_save_current)
    async def _save_current():
        h = current.get()
        if not h:
            ui.notification_show("Nothing to save yet.", type="warning")
            return
        ok = await db.set_state("current_date", h)
        if ok:
            ui.notification_show("Current date saved.", type="message")
        else:
            ui.notification_show("Failed saving current date (check RLS).", type="error")

    @reactive.Effect
    @reactive.event(input.btn_advance_one)
    async def _advance_one():
        h = current.get()
        if not h:
            return
        new_h = advance_one(h)
        current.set(new_h)
        await db.set_state("current_date", new_h)

    @reactive.Effect
    @reactive.event(input.btn_refresh_events)
    async def _re():
        await reload_events()
        ui.notification_show("Events refreshed.", type="message")

    # Day click handlers (including festival 31) -> show Day Details (list)
    def make_day_handler(m: int, d: int):
        trigger = getattr(input, f"m{m}_d{d}")
        @reactive.Effect
        @reactive.event(trigger)
        def _on_click():
            y = (current.get() or {"year": 1492})["year"]
            current.set({"year": y, "month": m, "day": d})
            selected_date.set({"year": y, "month": m, "day": d})
            session.send_input_message("set_month", {"value": month_name(m)})
            session.send_input_message("set_day", {"value": d})
            session.send_input_message("set_year", {"value": y})
            ui.modal_show(day_details_modal(y, m, d))

    for m in range(1, 13):
        for d in range(1, DAYS_PER_MONTH + 1):
            make_day_handler(m, d)
        if m in FESTIVALS:
            make_day_handler(m, 31)

    # Day Details modal actions
    @reactive.Effect
    @reactive.event(input.ev_list_close)
    def _close_list():
        ui.modal_remove()

    @reactive.Effect
    @reactive.event(input.ev_add_new)
    def _from_list_to_form():
        h = selected_date.get() or {"year": 1492, "month": 1, "day": 1}
        ui.modal_remove()
        ui.modal_show(event_form_modal(h["year"], h["month"], h["day"]))

    # Add/Edit form actions
    @reactive.Effect
    @reactive.event(input.ev_cancel)
    def _cancel_form():
        h = selected_date.get()
        ui.modal_remove()
        if h:
            ui.modal_show(day_details_modal(h["year"], h["month"], h["day"]))

    @reactive.Effect
    @reactive.event(input.ev_save)
    async def _save_event():
        # collect modal inputs
        try:
            m = MONTHS.index(input.ev_month()) + 1
        except ValueError:
            m = (current.get() or {"month": 1})["month"]
        d = int(input.ev_day() or (current.get() or {"day": 1})["day"])
        y = int(input.ev_year() or (current.get() or {"year": 1492})["year"])
        title = (input.ev_title() or "").strip() or None
        notes = (input.ev_desc() or "").strip() or None
        rdate = _iso(input.ev_real_date())

        if d == 31 and m not in FESTIVALS:
            d = 30
        if d < 1: d = 1
        if d > 31: d = 31

        rec = {
            "id": generate_event_id(),  # UUID for UUID column
            "year": y,
            "month": m,
            "day": d,
            "title": title,
            "notes": notes,
            "real_world_date": rdate,
        }

        try:
            await anyio.to_thread.run_sync(lambda: db.upsert_event(rec))
        except Exception as e:
            print("[App] upsert_event failed:", repr(e))
            ui.notification_show("Save failed (see logs / RLS).", type="error")
            return

        await reload_events()
        selected_date.set({"year": y, "month": m, "day": d})
        ui.modal_remove()
        ui.modal_show(day_details_modal(y, m, d))
        ui.notification_show("Event saved.", type="message")

# ---------- Create App -------------------------------------------------------

app = App(page, server=server, static_assets=ASSETS_DIR)
