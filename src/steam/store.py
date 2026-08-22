from __future__ import annotations

import asyncio
import json
import os
from typing import List, Optional

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(SRC_DIR)
DEFAULT_FILE = os.path.join(PROJECT_ROOT, "data", "steam_digest.json")
DEFAULT_MIN_DISCOUNT = 50


class SteamDigestStore:
    def __init__(self, filepath: Optional[str] = None) -> None:
        self.filepath = filepath or os.getenv("STEAM_DIGEST_FILE", DEFAULT_FILE)
        self._lock = asyncio.Lock()
        self.data: dict = {
            "channel_id": None,
            "channel_name": None,
            "min_discount": DEFAULT_MIN_DISCOUNT,
            "seen_ids": [],
            "seen_sale_ids": [],
            "active_sale_id": None,
            "initialized": False,
        }

    def load(self) -> None:
        if not os.path.exists(self.filepath):
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            self._write()
            return

        with open(self.filepath, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)

        self.data.update(loaded)
        if not isinstance(self.data.get("seen_ids"), list):
            self.data["seen_ids"] = []
        if not isinstance(self.data.get("seen_sale_ids"), list):
            self.data["seen_sale_ids"] = []

    def _write(self) -> None:
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as handle:
            json.dump(self.data, handle, indent=4, ensure_ascii=False)

    async def save(self) -> None:
        async with self._lock:
            self._write()

    @property
    def channel_id(self) -> Optional[int]:
        value = self.data.get("channel_id")
        return int(value) if value else None

    @property
    def channel_name(self) -> Optional[str]:
        return self.data.get("channel_name")

    @property
    def min_discount(self) -> int:
        try:
            return int(self.data.get("min_discount", DEFAULT_MIN_DISCOUNT))
        except (TypeError, ValueError):
            return DEFAULT_MIN_DISCOUNT

    @property
    def initialized(self) -> bool:
        return bool(self.data.get("initialized"))

    def seen_ids(self) -> List[str]:
        return list(self.data.get("seen_ids") or [])

    def has_seen(self, deal_key: str) -> bool:
        return deal_key in (self.data.get("seen_ids") or [])

    @property
    def active_sale_id(self) -> Optional[str]:
        value = self.data.get("active_sale_id")
        return str(value) if value else None

    def has_seen_sale(self, sale_id: str) -> bool:
        return sale_id in (self.data.get("seen_sale_ids") or [])

    async def set_channel(self, channel_id: int, channel_name: str) -> None:
        self.data["channel_id"] = channel_id
        self.data["channel_name"] = channel_name
        await self.save()

    async def set_min_discount(self, min_discount: int) -> None:
        self.data["min_discount"] = min_discount
        await self.save()

    async def mark_seen(self, deal_keys: List[str]) -> None:
        seen = self.data.setdefault("seen_ids", [])
        for deal_key in deal_keys:
            if deal_key and deal_key not in seen:
                seen.append(deal_key)
        if len(seen) > 500:
            self.data["seen_ids"] = seen[-500:]
        await self.save()

    async def mark_sales_seen(self, sale_ids: List[str]) -> None:
        seen = self.data.setdefault("seen_sale_ids", [])
        for sale_id in sale_ids:
            if sale_id and sale_id not in seen:
                seen.append(sale_id)
        if len(seen) > 50:
            self.data["seen_sale_ids"] = seen[-50:]
        await self.save()

    async def set_active_sale(self, sale_id: Optional[str]) -> None:
        self.data["active_sale_id"] = sale_id
        await self.save()

    async def mark_initialized(self, deal_keys: List[str]) -> None:
        self.data["initialized"] = True
        await self.mark_seen(deal_keys)
