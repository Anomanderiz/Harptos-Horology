# supa.py
# -----------------------------------------------------------------------------
# Supabase client + Harptos helpers for Shiny (async-safe wrappers).
# -----------------------------------------------------------------------------

from __future__ import annotations

from typing import Any, Optional, TypedDict, List
import anyio
import os

from supabase import create_client

# Typed structures -------------------------------------------------------------

class HarptosDate(TypedDict):
    year: int
    month: int
    day: int

# -----------------------------------------------------------------------------

class SupaClient:
    """Lightweight Supabase wrapper with async-safe helpers."""
    state_table: str = "state"
    events_table: str = "events"

    def __init__(self) -> None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_ANON_KEY")
        if not url or not key:
            raise RuntimeError(
                "Missing SUPABASE_URL / SUPABASE_ANON_KEY environment variables."
            )
        self.client = create_client(url, key)

    # --- State (key/value) ----------------------------------------------------

    async def get_state_value(self, key: str, default: Optional[Any] = None) -> Optional[Any]:
        """Return .value JSON for key from state table, else default."""
        def _q():
            return self.client.table(self.state_table).select("value").eq("key", key).execute()

        try:
            resp = await anyio.to_thread.run_sync(_q)
            data = getattr(resp, "data", None) or []
            if data:
                return data[0].get("value", default)
            return default
        except Exception:
            return default

    async def set_state(self, key: str, value: Any) -> bool:
        """Upsert a key/value into the state table."""
        rec = {"key": key, "value": value}
        def _q():
            # on_conflict="key" ensures primary-key upsert
            return self.client.table(self.state_table).upsert(rec, on_conflict="key").execute()

        try:
            await anyio.to_thread.run_sync(_q)
            return True
        except Exception as e:
            print("[Supa] set_state failed:", repr(e))
            return False

    # --- Events ---------------------------------------------------------------

    async def load_events(self) -> List[dict]:
        """Fetch all events ordered by year/month/day."""
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
            resp = await anyio.to_thread.run_sync(_q)
            return (getattr(resp, "data", None) or [])  # type: ignore[return-value]
        except Exception as e:
            print("[Supa] load_events failed:", repr(e))
            return []

__all__ = ["SupaClient", "HarptosDate"]
