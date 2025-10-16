# supa.py
# -----------------------------------------------------------------------------
# Supabase wrapper for Harptos calendar
# - Generates 64-bit event IDs (fits BIGINT)
# - Safe async helpers
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
import time
import random
from typing import Any, Dict, List, Optional, TypedDict

import anyio
from supabase import create_client


class HarptosDate(TypedDict):
    year: int
    month: int
    day: int


def generate_event_id() -> int:
    """
    Generate a positive 64-bit integer ID:
    - Top bits = milliseconds since epoch
    - Low bits = random entropy
    Fits signed BIGINT (Postgres) and avoids NULL id inserts.
    """
    ts = int(time.time() * 1000)  # ~2^41 space
    rnd = random.getrandbits(20)  # 20 bits of entropy
    val = (ts << 20) | rnd        # <= 2^61
    # Ensure < 2^63-1 (Postgres BIGINT max)
    return val & 0x7FFFFFFFFFFFFFFF


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
        """
        Synchronous call (wrap with anyio.to_thread.run_sync in app)
        Requires 'id' in rec. Use generate_event_id() to create one.
        """
        if "id" not in rec or rec["id"] is None:
            rec["id"] = generate_event_id()
        # If your Postgres table defines UNIQUE on (id), this will update on conflicts
        self.client.table(self.events_table).upsert(rec, on_conflict="id").execute()


__all__ = ["SupaClient", "HarptosDate", "generate_event_id"]
