# supabase_client.py
import os
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

load_dotenv(override=False)

_cached: Optional[Any] = None

def get_client() -> Any:
    global _cached
    if _cached is not None:
        return _cached

    try:
        from supabase import create_client  # lazy import so startup never hard-crashes
    except Exception as e:
        raise RuntimeError(
            "Supabase client library isn’t available. Install `supabase>=2`."
        ) from e

    url = os.getenv("SUPABASE_URL", "").strip()
    key = (os.getenv("SUPABASE_SERVICE_KEY", "").strip()
           or os.getenv("SUPABASE_ANON_KEY", "").strip())
    if not url or not key:
        raise RuntimeError(
            "Supabase credentials missing. Set SUPABASE_URL and SUPABASE_SERVICE_KEY "
            "(or SUPABASE_ANON_KEY) as environment variables."
        )

    _cached = create_client(url, key)
    return _cached

def list_items(limit: int = 100) -> List[Dict[str, Any]]:
    sb = get_client()
    resp = sb.table("items").select("*").order("created_at", desc=True).limit(limit).execute()
    return resp.data or []

def add_item(title: str, body: str, tags_csv: str = "") -> Dict[str, Any]:
    tags = [t.strip() for t in tags_csv.split(",") if t.strip()] if tags_csv else None
    payload = {"title": title, "body": body or None, "tags": tags}
    sb = get_client()
    resp = sb.table("items").insert(payload).execute()
    if not resp.data:
        raise RuntimeError("Insert failed (no data returned).")
    return resp.data[0]
