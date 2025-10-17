# app.py
# ------------------------------------------------------------------------------
# Harptos – Calendar + Timeline (Shiny version-agnostic: no ui.nav usage)
# - Calendar: responsive month grid; festival day 31; current day = red tile
# - Timeline: chronological list, vertical spacing proportional to day gap
# - View switcher uses radio buttons (works on Shiny 1.5.0+)
# - FIX: timeline cards expand/collapse reliably on click
# ------------------------------------------------------------------------------

from __future__ import annotations

import json
import os
from datetime import date
from typing import Any, Dict, List, Optional, Set

import anyio
from shiny import App, reactive, render, ui

from supa import SupaClient, HarptosDate, generate_event_id

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
    src = os.path.join(ASSETS_DIR, "moon_markers.json")
    if os.path.exists(src):
        try:
            with open(src, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                return {"new": list(data.get("new", [])), "full": list(data.get("full", []))}
        except Exception as e:
            print("[App] moon_markers.json load failed:", repr(e))
    return {"new": [], "full": []}

# ---------- Utils ------------------------------------------------------------

def month_name(i: int) -> str:
    return MONTHS[i - 1] if 1 <= i <= 12 else MONTHS[0]

def month_short(i: int) -> str:
    return month_name(i).split(",")[0].strip()

def ordinal_suffix(n: int) -> str:
    if 10 <= (n % 100) <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"

def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None

def safe_id(s: str) -> str:
    return str(s).replace("-", "_")

def festivals_before(month: int) -> int:
    return sum(1 for m in FESTIVALS if m < month)

def harptos_ordinal(y: int, m: int, d: int) -> int:
    """Absolute day index (365 days/year = 12*30 + 5 festivals)."""
    base = y * 365
    before = (m - 1) * 30 + festivals_before(m)
    day_index = before + (30 if (d == 31 and m in FESTIVALS) else d - 1)
    return base + day_index

def advance_one(h: HarptosDate) -> HarptosDate:
    y, m, d = h["year"], h["month"], h["day"]
    if d == 31:
        m2 = 1 if m == 12 else m + 1
        return {"year": y + (m == 12), "month": m2, "day": 1}
    if 1 <= d < 30:
        return {"year": y, "month": m, "day": d + 1}
    if d == 30:
        return {"year": y, "month": m, "day": 31} if m in FESTIVALS else {
            "year": y + (m == 12), "month": 1 if m == 12 else m + 1, "day": 1
        }
    return {"year": y, "month": 1, "day": 1}

# ---------- Reactive state ---------------------------------------------------

db = SupaClient()

current: reactive.Value[Optional[HarptosDate]] = reactive.Value(None)
events: reactive.Value[List[Dict[str, Any]]] = reactive.Value([])
markers: reactive.Value[Dict[str, List[Dict[str, int]]]] = reactive.Value({"new": [], "full": []})

selected_date: reactive.Value[Optional[HarptosDate]] = reactive.Value(None)
selected_event_id: reactive.Value[Optional[str]] = reactive.Value(None)

# Timeline UI state
expanded_ids: reactive.Value[Set[str]] = reactive.Value(set())
_registered_edit_ids: Set[str] = set()
_registered_tl_clicks: Set[str] = set()

# ---------- Calendar helpers -------------------------------------------------

def events_for_day(y: int, m: int, d: int) -> List[Dict[str, Any]]:
    return [
        r for r in (events.get() or [])
        if int(r.get("year", 0)) == y and int(r.get("month", 0)) == m and int(r.get("day", 0)) == d
    ]

def pip_for_day(m: int, d: int):
    ms = markers.get()
    has_new = any(x["month"] == m and x["day"] == d for x in ms.get("new", []))
    has_full = any(x["month"] == m and x["day"] == d for x in ms.get("full", []))
    if not (has_new or has_full):
        return None
    dots = []
    if has_new:
        dots.append(ui.span(class_="pip", title="New Moon"))
    if has_full:
        dots.append(ui.span(class_="pip", title="Full Moon"))
    return ui.span(*dots, class_="pip-wrap")

def event_blurbs(y: int, m: int, d: int) -> ui.TagChild:
    rows = events_for_day(y, m, d)
    if not rows:
        return ui.div(class_="day-events")
    items: List[ui.TagChild] = []
    max_items = 4
    for e in rows[:max_items]:
        items.append(ui.div((e.get("title") or "(Untitled)").strip(), class_="event-blurb"))
    if len(rows) > max_items:
        items.append(ui.div(f"+{len(rows) - max_items} more", class_="event-more"))
    return ui.div(*items, class_="day-events")

def day_tile_button(y: int, m: int, d: int, highlight: bool) -> ui.TagChild:
    pid = f"m{m}_d{d}"
    tile_class = "day-tile current-day" if highlight else "day-tile"
    return ui.input_action_button(
        pid,
        ui.div(
            ui.div(str(d), class_="day-num"),
            pip_for_day(m, d),
            event_blurbs(y, m, d),
            class_=tile_class,
        ),
        class_="day-tile-btn",
    )

def festival_tile_button(y: int, m: int, highlight: bool) -> ui.TagChild:
    label = FESTIVALS.get(m)
    pid = f"m{m}_d31"
    tile_class = "day-tile current-day" if highlight else "day-tile"
    return ui.input_action_button(
        pid,
        ui.div(
            ui.div("31", class_="day-num"),
            ui.div(label, class_="festival-label"),
            event_blurbs(y, m, 31),
            class_=tile_class,
        ),
        class_="day-tile-btn",
    )

def month_card(m: int, cur: Optional[HarptosDate]) -> ui.TagChild:
    view_year = (cur or {"year": 1492})["year"]
    is_hl = lambda d: bool(cur and cur["month"] == m and cur["day"] == d)
    tiles: List[ui.TagChild] = [day_tile_button(view_year, m, d, is_hl(d)) for d in range(1, DAYS_PER_MONTH + 1)]
    if m in FESTIVALS:
        tiles.append(festival_tile_button(view_year, m, is_hl(31)))
    return ui.card(
        ui.card_header(f"{month_name(m)} {view_year}"),
        ui.div(*tiles, class_="month-grid"),
        class_="month-card glass",
    )

# ---------- Timeline helpers -------------------------------------------------

def timeline_card(event: Dict[str, Any], gap_px: int, expanded: bool) -> ui.TagChild:
    y = int(event.get("year", 1492))
    m = int(event.get("month", 1))
    d = int(event.get("day", 1))
    eid = str(event.get("id"))
    sid = safe_id(eid)
    title = (event.get("title") or "(Untitled)").strip()
    sub = f"{ordinal_suffix(d)} of {month_short(m)}, {y}"
    desc = (event.get("notes") or "").strip()

    inner = ui.div(
        ui.div(title, class_="tl-title"),
        ui.div(sub, class_="tl-sub"),
        ui.div(desc, class_="tl-desc") if (expanded and desc) else None,
        class_="tl-card",
    )
    btn = ui.input_action_button(f"tl_{sid}", inner, class_="tl-card-btn")
    return ui.div(
        ui.div(class_="tl-dot"),
        btn,
        class_=("tl-item expanded" if expanded else "tl-item"),
        style=f"margin-top:{max(0, gap_px)}px;",
    )

# ---------- UI ----------------------------------------------------------------

page = ui.page_fluid(
    ui.head_content(ui.tags.link(rel="stylesheet", href="styles.css")),
    ui.div(
        ui.div(ui.h4("Harptos Horology", class_="mb-0")),
        ui.div(ui.output_text("current_date_label"), class_="ms-auto text-on-dark"),
        class_="navbar d-flex align-items-center gap-3 flex-wrap",
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
                    ui.input_action_button("btn_jump_current", "Jump to Current Day"),
                    ui.input_action_button("btn_refresh_events", "Refresh Events"),
                    class_="d-flex gap-2 mt-1",
                ),
            ),
            class_="glass",
        ),
        class_="container mt-3",
    ),
    # View switcher (Calendar / Timeline)
    ui.div(
        ui.card(
            ui.card_header("View"),
            ui.input_radio_buttons(
                "view_select",
                None,
                choices={"calendar": "Calendar", "timeline": "Timeline"},
                selected="calendar",
                inline=True,
            ),
            class_="glass",
        ),
        class_="container mt-3",
    ),
    # Main view container
    ui.div(ui.output_ui("main_view"), class_="container-fluid px-3"),
)

# ---------- Server -----------------------------------------------------------

def server(input, output, session):

    async def reload_events():
        rows = await db.load_events()
        norm: List[Dict[str, Any]] = []
        for r in rows or []:
            try:
                r["year"] = int(r.get("year", 1492))
                r["month"] = int(r.get("month", 1))
                r["day"] = int(r.get("day", 1))
            except Exception:
                pass
            norm.append(r)
        events.set(norm)

    auto_state = {"started": False}

    @reactive.Effect
    async def _init():
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

    # daily +1 tick (persist)
    @reactive.Effect
    async def _auto_tick():
        reactive.invalidate_later(86_400_000)
        if not auto_state["started"]:
            auto_state["started"] = True
            return
        h = current.get()
        if not h:
            return
        nh = advance_one(h)
        current.set(nh)
        await db.set_state("current_date", nh)

    @render.text
    def current_date_label():
        h = current.get()
        return "—" if not h else f"{month_short(h['month'])} {h['day']}, {h['year']}"

    # ---- Builders for the two views (UI only) -------------------------------

    def build_calendar_ui() -> ui.TagChild:
        _ = events.get()  # depend on events so calendar re-renders
        h = current.get()
        return ui.div(*[month_card(m, h) for m in range(1, 13)], class_="months-wrap")

    def build_timeline_ui() -> ui.TagChild:
        rows = events.get() or []
        if not rows:
            return ui.div(ui.p("No events yet. Add events on the calendar to see them here."), class_="glass p-3")

        # Chronological order
        rows_sorted = sorted(
            rows,
            key=lambda r: harptos_ordinal(int(r.get("year", 1492)),
                                          int(r.get("month", 1)),
                                          int(r.get("day", 1)))
        )

        PX_PER_DAY = 6   # vertical pixels per day gap (tweak to taste)
        MIN_GAP   = 28   # minimum gap between cards
        MAX_GAP   = 320  # cap for very large gaps

        items: List[ui.TagChild] = []
        prev_ord: Optional[int] = None
        expanded = expanded_ids.get()  # <--- dependency (keeps timeline reactive to clicks)

        for r in rows_sorted:
            y, m, d = int(r["year"]), int(r["month"]), int(r["day"])
            cur_ord = harptos_ordinal(y, m, d)
            if prev_ord is None:
                gap = 0
            else:
                diff = max(0, cur_ord - prev_ord)
                gap = min(MAX_GAP, MIN_GAP + diff * PX_PER_DAY)
            prev_ord = cur_ord

            eid = str(r.get("id"))
            items.append(timeline_card(r, gap, eid in expanded))

        return ui.div(*items, class_="timeline-wrap")

    # Single render that switches between the two views
    @render.ui
    def main_view():
        sel = input.view_select() or "calendar"
        # explicit dependency so clicks always re-render when on Timeline
        _ = expanded_ids.get() if sel == "timeline" else None  # <--- key fix
        return build_timeline_ui() if sel == "timeline" else build_calendar_ui()

    # ---- Controls -----------------------------------------------------------

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
        if d == 31 and m not in FESTIVALS: d = 30
        current.set({"year": y, "month": m, "day": d})

    @reactive.Effect
    @reactive.event(input.btn_save_current)
    async def _save_current():
        h = current.get()
        if not h:
            ui.notification_show("Nothing to save yet.", type="warning"); return
        ok = await db.set_state("current_date", h)
        ui.notification_show("Current date saved." if ok else "Failed saving current date (check RLS).",
                             type="message" if ok else "error")

    @reactive.Effect
    @reactive.event(input.btn_jump_current)
    async def _jump_to_saved():
        st = await db.get_state_value("current_date", default=None)
        if not isinstance(st, dict):
            ui.notification_show("No saved current date yet. Use 'Save Current Date' first.", type="warning"); return
        try:
            y = int(st["year"]); m = int(st["month"]); d = int(st["day"])
        except Exception:
            ui.notification_show("Saved current date is invalid.", type="error"); return
        current.set({"year": y, "month": m, "day": d})
        session.send_input_message("set_month", {"value": month_name(m)})
        session.send_input_message("set_day", {"value": d})
        session.send_input_message("set_year", {"value": y})
        ui.notification_show("Jumped to saved current day.", type="message")

    @reactive.Effect
    @reactive.event(input.btn_refresh_events)
    async def _re():
        await reload_events()
        ui.notification_show("Events refreshed.", type="message")

    # ---- Calendar day click handlers ---------------------------------------

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

    # ---- Edit handlers for the day-details modal ---------------------------

    @reactive.Effect
    def _install_edit_handlers():
        for e in (events.get() or []):
            sid = safe_id(e.get("id"))
            if sid in _registered_edit_ids:
                continue
            trigger = getattr(input, f"edit_{sid}")
            @reactive.Effect
            @reactive.event(trigger)
            def _open_editor(_e=e):
                y = int(_e.get("year", 1492)); m = int(_e.get("month", 1)); d = int(_e.get("day", 1))
                selected_date.set({"year": y, "month": m, "day": d})
                selected_event_id.set(str(_e.get("id")))
                ui.modal_show(event_form_modal(
                    y, m, d,
                    title_val=_e.get("title") or "",
                    notes_val=_e.get("notes") or "",
                    rw_date=(date.fromisoformat(_e["real_world_date"]) if _e.get("real_world_date") else None),
                    event_id=str(_e.get("id")),
                ))
            _registered_edit_ids.add(sid)

    # ---- Timeline click handlers (expand/collapse) -------------------------
    @reactive.Effect
    def _install_timeline_clicks():
        # re-run when events change OR when the user switches to Timeline
        _ = events.get()
        _ = input.view_select()  # ensures bindings exist right after switching views
        for e in (events.get() or []):
            sid = safe_id(e.get("id"))
            if sid in _registered_tl_clicks:
                continue
            trigger = getattr(input, f"tl_{sid}")
            @reactive.Effect
            @reactive.event(trigger)
            def _toggle(_eid=str(e.get("id"))):
                cur = set(expanded_ids.get())
                if _eid in cur: cur.remove(_eid)
                else:           cur.add(_eid)
                expanded_ids.set(cur)
            _registered_tl_clicks.add(sid)

    # ---- Modal utils -------------------------------------------------------

    @reactive.Effect
    @reactive.event(input.ev_list_close)
    def _close_list(): ui.modal_remove()

    @reactive.Effect
    @reactive.event(input.ev_add_new)
    def _add_new_from_list():
        h = selected_date.get() or {"year": 1492, "month": 1, "day": 1}
        selected_event_id.set(None); ui.modal_remove()
        ui.modal_show(event_form_modal(h["year"], h["month"], h["day"]))

    @reactive.Effect
    @reactive.event(input.ev_cancel)
    def _cancel_form():
        h = selected_date.get(); ui.modal_remove()
        if h: ui.modal_show(day_details_modal(h["year"], h["month"], h["day"]))

    @reactive.Effect
    @reactive.event(input.ev_delete)
    async def _delete_event():
        eid = selected_event_id.get()
        if not eid:
            ui.notification_show("Nothing to delete.", type="warning"); return
        try:
            await anyio.to_thread.run_sync(lambda: db.delete_event(eid))
        except Exception as e:
            print("[App] delete_event failed:", repr(e))
            ui.notification_show("Delete failed (see logs / RLS).", type="error"); return
        await reload_events()
        h = selected_date.get(); ui.modal_remove()
        if h: ui.modal_show(day_details_modal(h["year"], h["month"], h["day"]))
        ui.notification_show("Event deleted.", type="message")

    @reactive.Effect
    @reactive.event(input.ev_save)
    async def _save_event():
        try:
            m = MONTHS.index(input.ev_month()) + 1
        except ValueError:
            m = (current.get() or {"month": 1})["month"]
        d = int(input.ev_day() or (current.get() or {"day": 1})["day"])
        y = int(input.ev_year() or (current.get() or {"year": 1492})["year"])
        title = (input.ev_title() or "").strip() or None
        notes = (input.ev_desc() or "").strip() or None
        rdate = _iso(input.ev_real_date())
        if d == 31 and m not in FESTIVALS: d = 30
        if d < 1: d = 1
        if d > 31: d = 31
        eid = selected_event_id.get()
        rec = {
            "id": eid if eid else generate_event_id(),
            "year": y, "month": m, "day": d,
            "title": title, "notes": notes, "real_world_date": rdate,
        }
        try:
            await anyio.to_thread.run_sync(lambda: db.upsert_event(rec))
        except Exception as e:
            print("[App] upsert_event failed:", repr(e))
            ui.notification_show("Save failed (see logs / RLS).", type="error"); return
        await reload_events()
        selected_date.set({"year": y, "month": m, "day": d})
        selected_event_id.set(None)
        ui.modal_remove()
        ui.modal_show(day_details_modal(y, m, d))
        ui.notification_show("Event saved.", type="message")

# ---------- Day details & Event form modals ---------------------------------

def day_details_modal(y: int, m: int, d: int) -> ui.TagChild:
    dr = events_for_day(y, m, d)
    items: List[ui.TagChild] = []
    if not dr:
        items.append(ui.div("No events saved for this day.", class_="muted mb-2"))
    else:
        for r in dr:
            title = r.get("title") or "(Untitled)"
            notes = r.get("notes") or ""
            rw = r.get("real_world_date") or "Unknown Real Date"
            eid = safe_id(r.get("id"))
            items.append(
                ui.div(
                    ui.div(
                        ui.span(title, class_="event-title"),
                        ui.input_action_button(f"edit_{eid}", "✎ Edit", class_="btn btn-link btn-sm edit-link ms-2"),
                        class_="d-flex align-items-center gap-1",
                    ),
                    ui.div(rw, class_="event-date"),
                    ui.div(notes, class_="event-notes"),
                    class_="event-card",
                )
            )
    return ui.modal(
        ui.h5(f"{month_name(m)} {d}, {y}", class_="mb-3"),
        *items,
        ui.div(
            ui.input_action_button("ev_add_new", "Add New Event", class_="btn btn-success"),
            ui.input_action_button("ev_list_close", "Close", class_="btn btn-secondary ms-2"),
            class_="mt-3",
        ),
        easy_close=True, size="l",
    )

def event_form_modal(y: int, m: int, d: int, *, title_val: str = "", notes_val: str = "",
                     rw_date: Optional[date] = None, event_id: Optional[str] = None) -> ui.TagChild:
    if rw_date is None: rw_date = date.today()
    footer: List[ui.TagChild] = [ui.input_action_button("ev_save", "Save", class_="btn btn-primary me-2")]
    if event_id: footer.append(ui.input_action_button("ev_delete", "Delete", class_="btn btn-danger me-2"))
    footer.append(ui.input_action_button("ev_cancel", "Cancel", class_="btn btn-secondary"))
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
        footer=ui.div(*footer), easy_close=True, size="l",
    )

app = App(page, server=server, static_assets=ASSETS_DIR)
