from __future__ import annotations

import os
from typing import Dict, Any, List, Optional
from datetime import datetime
import json
import uuid

# The official supabase client
#   pip install supabase
from supabase import create_client, Client

HarptosDate = Dict[str, int]

def step_harptos(h: HarptosDate, months: list[str], dpm: int) -> HarptosDate:
    day = h["day"] + 1
    month = h["month"]
    year = h["year"]
    if day > dpm:
        day = 1
        month += 1
        if month > 12:
            month = 1
            year += 1
    return {"year": year, "month": month, "day": day}

class SupaClient:
    def __init__(self, url: str, key: str, schema: str = "public"):
        if not url or not key:
            # Create a dummy client that raises on use to make errors obvious
            self.client: Optional[Client] = None
        else:
            self.client = create_client(url, key, options={"schema": schema})

    async def _ensure(self):
        if self.client is None:
            raise RuntimeError("Supabase client not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY env vars.")

    # --- state table helpers ---
    async def get_state(self, key: str):
        await self._ensure()
        resp = self.client.table("state").select("*").eq("key", key).maybe_single().execute()
        row = None
        if resp.data:
            row = resp.data
        if isinstance(row, dict):
            return row.get("value")
        return None

    async def set_state(self, key: str, value: Any):
        await self._ensure()
        payload = {"key": key, "value": value, "updated_at": datetime.utcnow().isoformat()}
        # upsert by key
        self.client.table("state").upsert(payload, on_conflict="key").execute()

    # --- events helpers ---
    async def load_events(self) -> List[Dict[str, Any]]:
        await self._ensure()
        resp = self.client.table("events").select("*").order("year").order("month").order("day").execute()
        return resp.data or []

    async def add_event(self, row: Dict[str, Any]) -> None:
        await self._ensure()
        if "id" not in row:
            row["id"] = str(uuid.uuid4())
        self.client.table("events").insert(row).execute()

    async def delete_event(self, event_id: str) -> None:
        await self._ensure()
        self.client.table("events").delete().eq("id", event_id).execute()