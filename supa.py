# supa.py
# -----------------------------------------------------------------------------
# Supabase wrapper for Harptos calendar
# - UUID4 ids for events (Postgres UUID column)
# - Async-safe helpers
# -----------------------------------------------------------------------------

from __future__ import annotations

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

    def upsert_event(self, rec: Dict[str, Any]) -> None:
        """Synchronous call (wrap with anyio.to_thread.run_sync in app)."""
        if "id" not in rec or rec["id"] in (None, ""):
            rec["id"] = generate_event_id()
        self.client.table(self.events_table).upsert(rec, on_conflict="id").execute()


__all__ = ["SupaClient", "HarptosDate", "generate_event_id"]
