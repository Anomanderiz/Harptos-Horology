# supa.py
# -----------------------------------------------------------------------------
# Supabase client + Harptos helpers for Shiny (async-safe wrappers).
# - Uses ClientOptions(schema=...) correctly (no dict for options).
# - Runs sync Supabase calls off-thread via anyio.to_thread.run_sync.
# - Defensive response handling (obj/dict/list), no .data on None.
# - Exposes HarptosDate(...) as a callable factory so existing code like
#     HarptosDate(year=..., month=..., day=...)
#   continues to work even though it's a dict under the hood.
# -----------------------------------------------------------------------------

from __future__ import annotations

from typing import Any, Optional, TypedDict, List, Dict
import anyio

from supabase import create_client
try:
    # Newer releases
    from supabase.client import ClientOptions
except Exception:
    # Older releases
    from supabase.lib.client_options import ClientOptions


# --- Harptos helpers ---------------------------------------------------------
class HarptosDateDict(TypedDict):
    year: int
    month: int
    day: int


def HarptosDate(*, year: int, month: int, day: int) -> HarptosDateDict:
    """
    Callable factory to create a Harptos date dict.
    Keeps compatibility with code that calls HarptosDate(...).
    """
    return {"year": year, "month": month, "day": day}


def step_harptos(h: HarptosDateDict, months: List[str], dpm: int) -> HarptosDateDict:
    """
    Advance one day within a fixed-days-per-month scheme.
    `months` is the ordered month list; `dpm` is the days per month.
    """
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

    Parameters
    ----------
    url : str
        SUPABASE_URL
    key : str
        SUPABASE service or anon key (use service key server-side if RLS blocks writes)
    schema : str
        Default Postgres schema (defaults to "public")
    state_table : str
        Table for key/value app state (defaults to "state")
        Expected columns: key (text PK/unique), value (jsonb)
    events_table : str
        Table for calendar/event rows (defaults to "events")
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
        """
        Return a single row dict like {'key': ..., 'value': ...} or None.
        """
        def _q():
            q = (
                self.client.table(self.state_table)
                .select("key,value")
                .eq("key", key)
            )
            # Try maybe_single() (preferred), fall back gracefully if not present.
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
        """
        Convenience: return the 'value' field (or default) for a given key.
        """
        row = await self.get_state(key)
        return default if not row else row.get("value", default)

    async def set_state(self, key: str, value: Any) -> bool:
        """
        UPSERT key/value. Returns True on success.
        """
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
        """
        Return all event rows; adjust select/order to match your schema as needed.
        """
        def _q():
            # Customise selection and ordering if your schema requires it.
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
    """
    Normalise supabase response shapes:
    - PostgrestResponse with .data
    - dict with 'data' key
    - None
    """
    if resp is None:
        return None
    data = getattr(resp, "data", None)
    if data is None and isinstance(resp, dict):
        data = resp.get("data")
    return data


__all__ = [
    "SupaClient",
    "HarptosDate", "HarptosDateDict", "step_harptos",
]
