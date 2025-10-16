# supa.py
# -----------------------------------------------------------------------------
# Supabase client + Harptos helpers for Shiny (async-safe wrappers).
# -----------------------------------------------------------------------------

from __future__ import annotations

from typing import Any, Optional, TypedDict, List
import anyio

from supabase import create_client
try:
    from supabase.client import ClientOptions
except Exception:
    from supabase.lib.client_options import ClientOptions


# --- Harptos helpers ---------------------------------------------------------
class HarptosDateDict(TypedDict):
    year: int
    month: int
    day: int


def HarptosDate(*, year: int, month: int, day: int) -> HarptosDateDict:
    """Callable factory to create a Harptos date dict."""
    return {"year": year, "month": month, "day": day}


def step_harptos(h: HarptosDateDict, months: List[str], dpm: int) -> HarptosDateDict:
    """Advance one day within a fixed-days-per-month scheme."""
    day = h["day"] + 1
    month = h["month"]
    year = h["year"]

    if day > dpm:
        day = 1
        month += 1
        if month > len(months):
            month = 1
            year += 1

    return {"year": year, "month": month, "day": day}


# --- Supabase client ---------------------------------------------------------
class SupaClient:
    """
    Thin async-friendly wrapper around supabase-py’s sync client.

    Tables:
      - state(key text PK/unique, value jsonb)
      - events(...)
    """

    def __init__(
        self,
        url: str,
        key: str,
        *,
        schema: str = "public",
        state_table: str = "state",
        events_table: str = "events",
    ):
        if not url or not key:
            raise RuntimeError("SUPABASE_URL or SUPABASE_KEY missing")
        self.client = create_client(url, key, options=ClientOptions(schema=schema))
        self.state_table = state_table
        self.events_table = events_table

    # -------------------------- State (key/value) --------------------------- #
    async def get_state(self, key: str) -> Optional[dict]:
        """Return a single row dict like {'key': ..., 'value': ...} or None."""
        def _q():
            q = (
                self.client.table(self.state_table)
                .select("key,value")
                .eq("key", key)
            )
            try:
                q = q.maybe_single()
            except Exception:
                try:
                    q = q.single()
                except Exception:
                    q = q.limit(1)
            return q.execute()

        try:
            resp = await anyio.to_thread.run_sync(_q)
        except Exception as e:
            print(f"[Supa] get_state({key}) failed: {e!r}")
            return None

        data = _extract_data(resp)
        if not data:
            return None
        if isinstance(data, list):
            return data[0] if data else None
        return data

    async def get_state_value(self, key: str, default: Any = None) -> Any:
        row = await self.get_state(key)
        return default if not row else row.get("value", default)

    async def set_state(self, key: str, value: Any) -> bool:
        def _q():
            return (
                self.client.table(self.state_table)
                .upsert({"key": key, "value": value}, on_conflict="key")
                .execute()
            )
        try:
            resp = await anyio.to_thread.run_sync(_q)
        except Exception as e:
            print(f"[Supa] set_state({key}) failed: {e!r}")
            return False

        data = _extract_data(resp)
        return data is not None

    # ------------------------------ Events --------------------------------- #
    async def load_events(self) -> List[dict]:
        """Return all event rows."""
        def _q():
            return self.client.table(self.events_table).select("*").execute()
        try:
            resp = await anyio.to_thread.run_sync(_q)
        except Exception as e:
            print(f"[Supa] load_events() failed: {e!r}")
            return []
        data = _extract_data(resp)
        return data or []


# --- Internal helpers -------------------------------------------------------- #
def _extract_data(resp: Any) -> Optional[Any]:
    """Normalise supabase response shapes."""
    if resp is None:
        return None
    data = getattr(resp, "data", None)
    if data is None and isinstance(resp, dict):
        data = resp.get("data")
    return data


__all__ = ["SupaClient", "HarptosDate", "HarptosDateDict", "step_harptos"]
