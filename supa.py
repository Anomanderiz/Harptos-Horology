# supa.py
from typing import Any, Optional
import anyio
from supabase import create_client
try:
    # new-ish location
    from supabase.client import ClientOptions
except Exception:
    # older releases
    from supabase.lib.client_options import ClientOptions


class SupaClient:
    def __init__(self, url: str, key: str, schema: str = "public", table: str = "state"):
        if not url or not key:
            raise RuntimeError("SUPABASE_URL or SUPABASE_KEY missing")
        self.client = create_client(url, key, options=ClientOptions(schema=schema))
        self.table = table

    async def get_state(self, key: str) -> Optional[dict]:
        """Return a single row dict like {'key': ..., 'value': ...} or None."""
        def _q():
            # PostgREST query (sync)
            return (
                self.client.table(self.table)
                .select("key,value")
                .eq("key", key)
                .maybe_single()
                .execute()
            )

        try:
            resp = await anyio.to_thread.run_sync(_q)
        except Exception as e:
            print(f"[Supa] get_state({key}) failed: {e!r}")
            return None

        # Support both PostgrestResponse (obj) and dict
        data = getattr(resp, "data", None)
        if data is None and isinstance(resp, dict):
            data = resp.get("data")

        if not data:
            return None  # no row found

        # If caller ever switches off maybe_single(), handle list
        if isinstance(data, list):
            data = data[0] if data else None
        return data

    async def set_state(self, key: str, value: Any) -> bool:
        """UPSERT key/value. Returns True on success."""
        def _q():
            return (
                self.client.table(self.table)
                .upsert({"key": key, "value": value}, on_conflict="key")
                .execute()
            )

        try:
            resp = await anyio.to_thread.run_sync(_q)
        except Exception as e:
            print(f"[Supa] set_state({key}) failed: {e!r}")
            return False

        data = getattr(resp, "data", None)
        if data is None and isinstance(resp, dict):
            data = resp.get("data")
        return data is not None

    async def get_state_value(self, key: str, default: Any = None) -> Any:
        row = await self.get_state(key)
        return default if not row else row.get("value", default)
