# supa.py
# -----------------------------------------------------------------------------
# Supabase wrapper for Harptos calendar
# - UUID4 ids for events (Postgres UUID column)
# - Async-safe helpers
# -----------------------------------------------------------------------------

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, List, Optional, TypedDict

import anyio
from supabase import create_client


class HarptosDate(TypedDict):
    year: int
    month: int
    day: int


def generate_event_id() -> str:
    """Return a UUID4 string for the events.id (UUID) column."""
    return str(uuid.uuid4())


class SupaClient:
    state_table: str = "state"
    events_table: str = "events"

    def __init__(self) -> None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_ANON_KEY")
        if not url or not key:
            raise RuntimeError("Missing SUPABASE_URL / SUPABASE_ANON_KEY")
        self.client = create_client(url, key)

    # -------- state -----------------------------------------------------------

    async def get_state_value(self, key: str, default: Optional[Any] = None) -> Optional[Any]:
        def _q():
            return self.client.table(self.state_table).select("value").eq("key", key).limit(1).execute()
        try:
            res = await anyio.to_thread.run_sync(_q)
            rows = getattr(res, "data", None) or []
            if rows:
                return rows[0].get("value", default)
            return default
        except Exception as e:
            print("[Supa] get_state_value failed:", repr(e))
            return default

    async def set_state(self, key: str, value: Any) -> bool:
        rec = {"key": key, "value": value}
        def _q():
            return self.client.table(self.state_table).upsert(rec, on_conflict="key").execute()
        try:
            await anyio.to_thread.run_sync(_q)
            return True
        except Exception as e:
            print("[Supa] set_state failed:", repr(e))
            return False

    # -------- events ----------------------------------------------------------

    async def load_events(self) -> List[Dict[str, Any]]:
        def _q():
            return (
                self.client.table(self.events_table)
                .select("*")
                .order("year", desc=False)
                .order("month", desc=False)
                .order("day", desc=False)
                .execute()
            )
        try:
            res = await anyio.to_thread.run_sync(_q)
            return getattr(res, "data", None) or []
        except Exception as e:
            print("[Supa] load_events failed:", repr(e))
            return []

    async def sync_current_date(self, default: HarptosDate) -> Optional[HarptosDate]:
        payload = {
            "default_year": int(default.get("year", 1492)),
            "default_month": int(default.get("month", 1)),
            "default_day": int(default.get("day", 1)),
        }

        def _q():
            return self.client.rpc("advance_harptos_date_if_needed", payload).execute()

        try:
            res = await anyio.to_thread.run_sync(_q)
            data = getattr(res, "data", None)
            if isinstance(data, list):
                row = data[0] if data else None
            else:
                row = data
            if isinstance(row, str):
                try:
                    row = json.loads(row)
                except Exception:
                    row = None
            if not isinstance(row, dict):
                return None
            return {
                "year": int(row.get("year", payload["default_year"])),
                "month": int(row.get("month", payload["default_month"])),
                "day": int(row.get("day", payload["default_day"])),
            }
        except Exception as e:
            print("[Supa] sync_current_date failed:", repr(e))
            return None

    def upsert_event(self, rec: Dict[str, Any]) -> None:
        """Synchronous call (wrap with anyio.to_thread.run_sync in app)."""
        if "id" not in rec or rec["id"] in (None, ""):
            rec["id"] = generate_event_id()
        self.client.table(self.events_table).upsert(rec, on_conflict="id").execute()

    def delete_event(self, event_id: str) -> None:
        """Delete a single event by UUID."""
        self.client.table(self.events_table).delete().eq("id", event_id).execute()


__all__ = ["SupaClient", "HarptosDate", "generate_event_id"]
