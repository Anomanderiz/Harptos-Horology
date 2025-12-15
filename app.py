# app.py
# ------------------------------------------------------------------------------
# Harptos – Calendar + Timeline with Video Backdrop
# Refined Version (Fixed Modal Collision & Scroll Glitch)
# ------------------------------------------------------------------------------

from __future__ import annotations

import json
import os
import re
from datetime import date
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import defaultdict

import anyio
from shiny import App, reactive, render, ui

# Mocking SupaClient import if not present in environment
try:
    from supa import SupaClient, HarptosDate, generate_event_id
except ImportError:
    import uuid
    class SupaClient:
        async def load_events(self): return []
        async def get_state_value(self, k, default): return default
        async def set_state(self, k, v): return True
        async def delete_event(self, eid): pass
        async def upsert_event(self, rec): pass
    HarptosDate = Dict[str, int]
    def generate_event_id(): return str(uuid.uuid4())

# ------------------------------------------------------------------------------
# Constants & Config
# ------------------------------------------------------------------------------

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

# ------------------------------------------------------------------------------
# Injected CSS & JS
# ------------------------------------------------------------------------------

CUSTOM_CSS = """
/* Timeline Expansion Logic - Render always, toggle visibility */
.tl-desc { display: none; }
.tl-item.expanded .tl-desc { display: block; animation: fadeIn 0.3s; }

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(-5px); }
    to { opacity: 1; transform: translateY(0); }
}

/* Glass / UI Fixes */
.glass {
    background: rgba(20, 20, 30, 0.85);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    color: #e0e0e0;
}
.day-tile-btn {
    background: none; border: none; padding: 0; margin: 0;
    width: 100%; text-align: left; cursor: pointer;
}
.day-tile-btn:hover .day-tile {
    background: rgba(255, 255, 255, 0.1);
}
.pip-wrap { font-size: 0.7rem; color: #ffd700; margin-left: 4px; }
"""

CUSTOM_JS = """
$(document).ready(function() {
    // 1. Delegated Calendar Day Click
    $(document).off('click', '.day-tile-btn').on('click', '.day-tile-btn', function() {
        let m = $(this).data('month');
        let d = $(this).data('day');
        Shiny.setInputValue('js_date_click', {month: m, day: d}, {priority: 'event'});
    });

    // 2. Delegated Timeline Expansion
    $(document).off('click', '.tl-card-btn').on('click', '.tl-card-btn', function() {
        let wrapper = $(this).closest('.tl-item');
        wrapper.toggleClass('expanded');
        
        let eid = $(this).data('tl-id');
        Shiny.setInputValue('tl_toggle', eid, {priority: 'event'});
    });

    // 3. Delegated Edit Event Click
    // Using .off().on() ensures we don't accidentally bind the listener twice
    $(document).off('click', '.edit-event-btn').on('click', '.edit-event-btn', function(e) {
        e.stopPropagation(); // Prevent triggering parent day click
        let eid = $(this).data('edit-id');
        Shiny.setInputValue('edit_event_clicked', {id: eid}, {priority: 'event'});
    });
});
"""

# ------------------------------------------------------------------------------
# Logic Helpers
# ------------------------------------------------------------------------------

def load_markers() -> Dict[str, List[Dict[str, int]]]:
    """Load moon phases from JSON."""
    src = os.path.join(ASSETS_DIR, "moon_markers.json")
    if os.path.exists(src):
        try:
            with open(src, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                return {"new": list(data.get("new", [])), "full": list(data.get("full", []))}
        except Exception as e:
            print("[App] moon_markers.json load failed:", repr(e))
    return {"new": [], "full": []}

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

def festivals_before(month: int) -> int:
    return sum(1 for m in FESTIVALS if m < month)

def harptos_ordinal(y: int, m: int, d: int) -> int:
    """Absolute day index."""
    base = y * 365
    before = (m - 1) * 30 + festivals_before(m)
    day_index = before + (30 if (d == 31 and m in FESTIVALS) else d - 1)
    return base + day_index

def _priority_from_title(title: str) -> int:
    if not title:
        return 10_000_000
    m = re.search(r'#\s*(\d+)\b', title)
    return int(m.group(1)) if m else 10_000_000

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

# ------------------------------------------------------------------------------
# UI Components
# ------------------------------------------------------------------------------

def pip_for_day(m: int, d: int, ms: Dict[str, List[Dict[str, int]]]) -> Optional[ui.TagChild]:
    has_new = any(x["month"] == m and x["day"] == d for x in ms.get("new", []))
    has_full = any(x["month"] == m and x["day"] == d for x in ms.get("full", []))
    if not (has_new or has_full):
        return None
    dots = []
    if has_new: dots.append(ui.span("●", class_="pip", title="New Moon", style="color: #aaa;"))
    if has_full: dots.append(ui.span("○", class_="pip", title="Full Moon", style="color: #fff; font-weight:bold;"))
    return ui.span(*dots, class_="pip-wrap")

def event_blurbs(events_list: List[Dict[str, Any]]) -> ui.TagChild:
    if not events_list:
        return ui.div(class_="day-events")
    items: List[ui.TagChild] = []
    max_items = 4
    for e in events_list[:max_items]:
        items.append(ui.div((e.get("title") or "(Untitled)").strip(), class_="event-blurb"))
    if len(events_list) > max_items:
        items.append(ui.div(f"+{len(events_list) - max_items} more", class_="event-more"))
    return ui.div(*items, class_="day-events")

def day_tile_button(y: int, m: int, d: int, highlight: bool, 
                    day_events: List[Dict[str, Any]], 
                    markers_data: Dict[str, List]) -> ui.TagChild:
    tile_class = "day-tile current-day" if highlight else "day-tile"
    
    day_label = str(d)
    extra_cls = "day-num"
    if d == 31:
        day_label = "31" 
        extra_cls = "day-num festival-num"
    
    return ui.tags.button(
        ui.div(
            ui.div(
                ui.span(day_label, class_=extra_cls),
                ui.div(FESTIVALS[m], class_="festival-label") if d == 31 else None,
                class_="d-flex justify-content-between"
            ),
            pip_for_day(m, d, markers_data),
            event_blurbs(day_events),
            class_=tile_class,
        ),
        class_="day-tile-btn",
        **{"data-month": str(m), "data-day": str(d), "type": "button"}
    )

def month_card(m: int, cur: Optional[HarptosDate], 
               indexed_events: Dict[Tuple[int, int, int], List[Dict[str, Any]]], 
               markers_data: Dict[str, List]) -> ui.TagChild:
    view_year = (cur or {"year": 1492})["year"]
    is_hl = lambda d: bool(cur and cur["month"] == m and cur["day"] == d)
    
    tiles: List[ui.TagChild] = []
    
    # 1-30 Days
    for d in range(1, DAYS_PER_MONTH + 1):
        d_evs = indexed_events.get((view_year, m, d), [])
        tiles.append(day_tile_button(view_year, m, d, is_hl(d), d_evs, markers_data))
        
    # Festival Day (31st)
    if m in FESTIVALS:
        d_evs = indexed_events.get((view_year, m, 31), [])
        tiles.append(day_tile_button(view_year, m, 31, is_hl(31), d_evs, markers_data))
        
    return ui.card(
        ui.card_header(f"{month_name(m)} {view_year}"),
        ui.div(*tiles, class_="month-grid"),
        class_="month-card glass",
    )

def timeline_card(event: Dict[str, Any], gap_px: int, expanded: bool) -> ui.TagChild:
    y = int(event.get("year", 1492))
    m = int(event.get("month", 1))
    d = int(event.get("day", 1))
    eid = str(event.get("id"))
    title = (event.get("title") or "(Untitled)").strip()
    sub = f"{ordinal_suffix(d)} of {month_short(m)}, {y}"
    desc = (event.get("notes") or "").strip()

    container_cls = "tl-item expanded" if expanded else "tl-item"

    inner = ui.div(
        ui.div(title, class_="tl-title"),
        ui.div(sub, class_="tl-sub"),
        ui.div(desc, class_="tl-desc") if desc else None,
        class_="tl-card",
    )
    
    btn = ui.tags.button(
        inner,
        class_="tl-card-btn",
        **{"type": "button", "data-tl-id": eid}
    )
    
    return ui.div(
        ui.div(class_="tl-dot"),
        btn,
        class_=container_cls,
        style=f"margin-top:{max(0, gap_px)}px;",
    )

# ------------------------------------------------------------------------------
# Main App
# ------------------------------------------------------------------------------

bg_video = ui.tags.video(
    ui.tags.source(src="Backdrop.webm", type="video/webm"),
    id="bg-video",
    **{"autoplay": "", "muted": "", "loop": "", "playsinline": "", "preload": "auto"}
)
bg_overlay = ui.div(id="bg-overlay")

page = ui.page_fluid(
    ui.head_content(
        ui.tags.link(rel="stylesheet", href="styles.css"),
        ui.tags.style(CUSTOM_CSS),
        ui.tags.script(CUSTOM_JS),
        ui.tags.script(src="js/delegates.js"),
    ),
    bg_video,
    bg_overlay,

    ui.div(
        ui.div(ui.h4("Harptos Horology", class_="mb-0 text-white")),
        ui.div(ui.output_text("current_date_label"), class_="ms-auto text-white fw-bold"),
        class_="navbar d-flex align-items-center gap-3 flex-wrap p-3 glass mb-3",
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
                    ui.input_action_button("btn_jump_current", "Jump to Saved"),
                    ui.input_action_button("btn_refresh_events", "Refresh Events"),
                    class_="d-flex gap-2 mt-1 flex-wrap",
                ),
            ),
            class_="glass",
        ),
        class_="container mt-3",
    ),
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
    ui.div(ui.output_ui("main_view"), class_="container-fluid px-3 pb-5"),
)

# ------------------------------------------------------------------------------
# Server
# ------------------------------------------------------------------------------

def server(input, output, session):
    db = SupaClient()

    # State
    current: reactive.Value[Optional[HarptosDate]] = reactive.Value(None)
    events: reactive.Value[List[Dict[str, Any]]] = reactive.Value([])
    markers: reactive.Value[Dict[str, List[Dict[str, Any]]]] = reactive.Value({"new": [], "full": []})
    
    selected_date: reactive.Value[Optional[HarptosDate]] = reactive.Value(None)
    selected_event_id: reactive.Value[Optional[str]] = reactive.Value(None)
    expanded_ids: reactive.Value[Set[str]] = reactive.Value(set())

    auto_state = {"started": False}

    async def reload_events():
        rows = await db.load_events()
        norm: List[Dict[str, Any]] = []
        for r in rows or []:
            try:
                r["year"] = int(r.get("year", 1492))
                r["month"] = int(r.get("month", 1))
                r["day"] = int(r.get("day", 1))
                r["title"] = str(r.get("title") or "")
                r["notes"] = str(r.get("notes") or "")
                r["id"] = str(r.get("id"))
            except Exception:
                continue
            norm.append(r)
        events.set(norm)

    @reactive.Effect
    async def _init():
        st = await db.get_state_value("current_date", default=None)
        if isinstance(st, dict):
            try:
                y, m, d = int(st["year"]), int(st["month"]), int(st["day"])
                current.set({"year": y, "month": m, "day": d})
                ui.update_select("set_month", selected=month_name(m))
                ui.update_numeric("set_day", value=d)
                ui.update_numeric("set_year", value=y)
            except Exception:
                current.set({"year": 1492, "month": 1, "day": 1})
        else:
            current.set({"year": 1492, "month": 1, "day": 1})
        
        markers.set(load_markers())
        await reload_events()

    @reactive.Effect
    async def _auto_tick():
        reactive.invalidate_later(86_400_000)
        if not auto_state["started"]:
            auto_state["started"] = True
            return
        h = current.get()
        if h:
            nh = advance_one(h)
            current.set(nh)
            await db.set_state("current_date", nh)

    @render.text
    def current_date_label():
        h = current.get()
        return "—" if not h else f"{month_short(h['month'])} {h['day']}, {h['year']}"

    # ---- View Builders -------------------------------------------------------

    def build_calendar_ui() -> ui.TagChild:
        ev_data = events.get()
        h = current.get()
        ms = markers.get()
        
        # Performance: Index events by date immediately
        # Dict[Tuple[year, month, day], List[Event]]
        indexed = defaultdict(list)
        for e in ev_data:
            key = (int(e["year"]), int(e["month"]), int(e["day"]))
            indexed[key].append(e)
            
        return ui.div(*[month_card(m, h, indexed, ms) for m in range(1, 13)], class_="months-wrap")

    def build_timeline_ui() -> ui.TagChild:
        rows = events.get() or []
        if not rows:
            return ui.div(ui.p("No events yet.", class_="text-center mt-4"), class_="glass p-3")

        rows_sorted = sorted(
            rows,
            key=lambda r: (
                harptos_ordinal(int(r["year"]), int(r["month"]), int(r["day"])),
                _priority_from_title(r["title"]),
                r["title"].lower(),
                r["id"]
            )
        )

        PX_PER_DAY = 6
        MIN_GAP = 28
        MAX_GAP = 320

        items: List[ui.TagChild] = []
        prev_ord: Optional[int] = None
        
        # Read initial state without taking a dependency
        with reactive.isolate():
            expanded_set = expanded_ids.get()

        for r in rows_sorted:
            y, m, d = int(r["year"]), int(r["month"]), int(r["day"])
            cur_ord = harptos_ordinal(y, m, d)
            gap = 0 if prev_ord is None else min(MAX_GAP, MIN_GAP + max(0, cur_ord - prev_ord) * PX_PER_DAY)
            prev_ord = cur_ord
            items.append(timeline_card(r, gap, str(r["id"]) in expanded_set))

        return ui.div(*items, class_="timeline-wrap")

    @render.ui
    def main_view():
        sel = input.view_select()
        if sel == "timeline":
            return build_timeline_ui()
        return build_calendar_ui()

    # ---- Event Handlers ------------------------------------------------------

    @reactive.Effect
    @reactive.event(input.js_date_click)
    def _on_day_click():
        data = input.js_date_click()
        if not isinstance(data, dict): return
        
        try:
            m, d = int(data.get("month", 0)), int(data.get("day", 0))
            y = (current.get() or {"year": 1492})["year"]
            if m < 1 or m > 12 or d < 1: return

            current.set({"year": y, "month": m, "day": d})
            selected_date.set({"year": y, "month": m, "day": d})
            ui.update_select("set_month", selected=month_name(m))
            ui.update_numeric("set_day", value=d)
            ui.update_numeric("set_year", value=y)
            
            # Show the modal list (REPLACES existing if open)
            ui.modal_show(day_details_modal(y, m, d, events.get()))
        except Exception as e:
            print(f"Click error: {e}")

    @reactive.Effect
    @reactive.event(input.tl_toggle)
    def _on_tl_toggle():
        eid = str(input.tl_toggle() or "")
        if not eid: return
        # Update state silently in background
        cur = set(expanded_ids.get())
        if eid in cur: cur.remove(eid)
        else: cur.add(eid)
        expanded_ids.set(cur)

    @reactive.Effect
    @reactive.event(input.edit_event_clicked)
    async def _on_edit_click():
        payload = input.edit_event_clicked()
        eid = payload.get("id") if isinstance(payload, dict) else payload
        if not eid: return

        all_events = events.get() or []
        ev = next((e for e in all_events if str(e["id"]) == str(eid)), None)
        if not ev:
            ui.notification_show("Event not found.", type="warning")
            return
        
        y, m, d = int(ev["year"]), int(ev["month"]), int(ev["day"])
        selected_date.set({"year": y, "month": m, "day": d})
        selected_event_id.set(str(ev["id"]))
        
        rw_date = None
        raw_rw = ev.get("real_world_date")
        if raw_rw:
            try: 
                rw_date = date.fromisoformat(raw_rw)
            except (ValueError, TypeError):
                rw_date = None

        # Fix: Remove old, wait for DOM cleanup, then show new
        ui.modal_remove()
        await anyio.sleep(0.2)
        ui.modal_show(event_form_modal(
            y, m, d,
            title_val=ev.get("title", ""),
            notes_val=ev.get("notes", ""),
            rw_date=rw_date,
            event_id=str(ev["id"])
        ))

    # ---- Standard Controls ---------------------------------------------------

    @reactive.Effect
    @reactive.event(input.btn_apply_current)
    def _apply_current():
        try: m = MONTHS.index(input.set_month()) + 1
        except ValueError: m = 1
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
        if not h: return
        ok = await db.set_state("current_date", h)
        if ok: ui.notification_show("Current date saved.", type="message")
        else: ui.notification_show("Failed saving date.", type="error")

    @reactive.Effect
    @reactive.event(input.btn_jump_current)
    async def _jump_to_saved():
        st = await db.get_state_value("current_date", default=None)
        if isinstance(st, dict):
            try:
                y, m, d = int(st["year"]), int(st["month"]), int(st["day"])
                current.set({"year": y, "month": m, "day": d})
                ui.update_select("set_month", selected=month_name(m))
                ui.update_numeric("set_day", value=d)
                ui.update_numeric("set_year", value=y)
                ui.notification_show("Jumped to saved date.", type="message")
                return
            except Exception: pass
        ui.notification_show("No valid saved date.", type="warning")

    @reactive.Effect
    @reactive.event(input.btn_refresh_events)
    async def _refresh_handler():
        await reload_events()
        ui.notification_show("Events refreshed.", type="message")

    # ---- Modal Handlers -----------------------------------------------------

    @reactive.Effect
    @reactive.event(input.ev_list_close)
    def _close_list(): ui.modal_remove()

    @reactive.Effect
    @reactive.event(input.ev_add_new)
    async def _add_new_from_list():
        h = selected_date.get() or {"year": 1492, "month": 1, "day": 1}
        selected_event_id.set(None)
        
        # Fix: Transition logic
        ui.modal_remove()
        await anyio.sleep(0.2)
        ui.modal_show(event_form_modal(h["year"], h["month"], h["day"]))

    @reactive.Effect
    @reactive.event(input.ev_cancel)
    async def _cancel_form():
        h = selected_date.get()
        # Fix: Transition logic
        ui.modal_remove()
        await anyio.sleep(0.2)
        if h:
            ui.modal_show(day_details_modal(h["year"], h["month"], h["day"], events.get()))

    @reactive.Effect
    @reactive.event(input.ev_delete)
    async def _delete_event():
        eid = selected_event_id.get()
        if not eid: return
        try:
            await anyio.to_thread.run_sync(lambda: db.delete_event(eid))
            await reload_events()
            ui.notification_show("Event deleted.", type="message")
            h = selected_date.get()
            
            # Fix: Transition logic
            ui.modal_remove()
            await anyio.sleep(0.2)
            if h:
                ui.modal_show(day_details_modal(h["year"], h["month"], h["day"], events.get()))
        except Exception as e:
            ui.notification_show(f"Error: {e}", type="error")

    @reactive.Effect
    @reactive.event(input.ev_save)
    async def _save_event():
        try:
            try: m = MONTHS.index(input.ev_month()) + 1
            except ValueError: m = 1
            d = int(input.ev_day() or 1)
            y = int(input.ev_year() or 1492)
            if d == 31 and m not in FESTIVALS: d = 30
            
            eid = selected_event_id.get() or generate_event_id()
            rec = {
                "id": eid,
                "year": y, "month": m, "day": d,
                "title": (input.ev_title() or "").strip(),
                "notes": (input.ev_desc() or "").strip(),
                "real_world_date": _iso(input.ev_real_date()),
            }
            
            await anyio.to_thread.run_sync(lambda: db.upsert_event(rec))
            await reload_events()
            
            selected_date.set({"year": y, "month": m, "day": d})
            selected_event_id.set(None)
            
            # Fix: Transition logic
            ui.modal_remove()
            await anyio.sleep(0.2)
            ui.modal_show(day_details_modal(y, m, d, events.get()))
            ui.notification_show("Event saved.", type="message")
        except Exception as e:
            ui.notification_show(f"Error saving: {e}", type="error")

# ------------------------------------------------------------------------------
# Modals
# ------------------------------------------------------------------------------

def day_details_modal(y: int, m: int, d: int, all_events: List[Dict[str, Any]]) -> ui.TagChild:
    day_events = [
        r for r in (all_events or [])
        if int(r["year"]) == y and int(r["month"]) == m and int(r["day"]) == d
    ]
    
    items: List[ui.TagChild] = []
    if not day_events:
        items.append(ui.div("No events saved for this day.", class_="text-muted mb-3 fst-italic"))
    else:
        for r in day_events:
            title = r.get("title") or "(Untitled)"
            notes = r.get("notes") or ""
            rw = r.get("real_world_date") or "Unknown Real Date"
            
            items.append(
                ui.div(
                    ui.div(
                        ui.span(title, class_="fw-bold fs-5"),
                        ui.tags.button(
                            "✎ Edit",
                            class_="btn btn-link btn-sm edit-event-btn text-decoration-none",
                            **{"type": "button", "data-edit-id": str(r["id"])}
                        ),
                        class_="d-flex align-items-center justify-content-between",
                    ),
                    ui.div(rw, class_="small text-secondary mb-1"),
                    ui.div(notes, class_="mb-0 text-break", style="white-space: pre-wrap;"),
                    class_="p-3 mb-2 border rounded bg-light text-dark",
                )
            )
            
    return ui.modal(
        ui.h5(f"{month_name(m)} {d}, {y}", class_="mb-3"),
        *items,
        ui.div(
            ui.input_action_button("ev_add_new", "Add New Event", class_="btn btn-success"),
            ui.input_action_button("ev_list_close", "Close", class_="btn btn-secondary ms-2"),
            class_="mt-3 d-flex justify-content-end",
        ),
        easy_close=True, size="l",
    )

def event_form_modal(y: int, m: int, d: int, *, title_val: str = "", notes_val: str = "",
                     rw_date: Optional[date] = None, event_id: Optional[str] = None) -> ui.TagChild:
    if rw_date is None: rw_date = date.today()
    
    footer: List[ui.TagChild] = [ui.input_action_button("ev_save", "Save", class_="btn btn-primary me-2")]
    if event_id:
        footer.append(ui.input_action_button("ev_delete", "Delete", class_="btn btn-danger me-2"))
    footer.append(ui.input_action_button("ev_cancel", "Cancel", class_="btn btn-secondary"))
    
    return ui.modal(
        ui.h5("Add / Edit Event", class_="mb-3"),
        ui.row(
            ui.input_select("ev_month", "Month", choices=MONTHS, selected=month_name(m)),
            ui.input_numeric("ev_day", "Day", value=d, min=1, max=31),
            ui.input_numeric("ev_year", "Year", value=y),
        ),
        ui.input_text("ev_title", "Title", value=title_val, placeholder="Event Title"),
        ui.input_text_area("ev_desc", "Description", value=notes_val, height="150px", placeholder="Details..."),
        ui.input_date("ev_real_date", "Real-World Date", value=rw_date),
        footer=ui.div(*footer, class_="d-flex justify-content-end"), 
        easy_close=True, size="l",
    )

app = App(page, server=server, static_assets=ASSETS_DIR)
