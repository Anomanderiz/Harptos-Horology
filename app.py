
from shiny import App, ui, reactive, render
from supabase_client import list_items, add_item

# ---- UI ----
app_ui = ui.page_fluid(
    ui.head_content(
        ui.tags.title("Mithril Glass — Shiny"),
        ui.include_css("www/styles.css"),
    ),
    ui.div({"class": "backdrop"}),
    ui.div({"class": "container"},
        ui.h2("Mithril Almanac — Private"),
        ui.p("A minimal Shiny + Supabase starter with animated glass UI."),
        ui.layout_columns(
            ui.card({"class": "glass"},
                ui.card_header("Add an item"),
                ui.input_text("title", "Title", placeholder="Enter a title"),
                ui.input_text_area("body", "Body", placeholder="Optional details", rows=4),
                ui.input_text("tags", "Tags (comma separated)", placeholder="e.g., lore, quest"),
                ui.input_action_button("add_btn", "Add", class_="btn-primary"),
                ui.div({"class": "help"}, "Tip: Keep titles short and meaningful."),
            ),
            ui.card({"class": "glass"},
                ui.card_header("Items"),
                ui.output_ui("items_panel"),
                ui.input_action_button("refresh_btn", "Refresh"),
            ),
            col_widths=(4, 8)
        ),
    )
)

# ---- Server ----
def server(input, output, session):
    items_store = reactive.value([])
    status = reactive.value("")

    @reactive.effect
    def _init_load():
        try:
            items_store.set(list_items(limit=100))
            status.set("Loaded.")
        except Exception as e:
            status.set(f"Error: {e}")

    @reactive.effect
    @reactive.event(input.refresh_btn)
    def _refresh():
        try:
            items_store.set(list_items(limit=100))
            status.set("Refreshed.")
        except Exception as e:
            status.set(f"Error: {e}")

    @reactive.effect
    @reactive.event(input.add_btn)
    def _add():
        t = input.title()
        b = input.body()
        tg = input.tags()
        if not (t and t.strip()):
            status.set("Please provide a title.")
            return
        try:
            _ = add_item(t.strip(), b.strip() if b else "", tg or "")
            items_store.set(list_items(limit=100))
            # Clear inputs (using update) — Shiny for Python uses session-based updates
            session.send_input_message("title", {"value": ""})
            session.send_input_message("body", {"value": ""})
            session.send_input_message("tags", {"value": ""})
            status.set("Item added.")
        except Exception as e:
            status.set(f"Error: {e}")

    @output.ui
    def items_panel():
        data = items_store()
        if not data:
            return ui.div({"class": "empty glass"}, "No items yet. Add your first entry above.")
        # Render a simple, readable list
        rows = []
        for row in data:
            title = row.get("title") or "(untitled)"
            body = row.get("body") or ""
            tags = row.get("tags") or []
            rows.append(
                ui.div({"class": "item"},
                    ui.div({"class": "item-title"}, title),
                    ui.div({"class": "item-meta"}, ", ".join(tags) if tags else "—"),
                    ui.div({"class": "item-body"}, body)
                )
            )
        return ui.div({"class": "items-list"}, *rows, ui.div({"class": "status"}, status()))

app = App(app_ui, server)
