from __future__ import annotations

import asyncio
import json
import os
from typing import List, Optional

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(SRC_DIR)
DEFAULT_FILE = os.path.join(PROJECT_ROOT, "data", "tft_digest.json")


class TftDigestStore:
    def __init__(self, filepath: Optional[str] = None) -> None:
        self.filepath = filepath or os.getenv("TFT_DIGEST_FILE", DEFAULT_FILE)
        self._lock = asyncio.Lock()
        self.data: dict = {
            "channel_id": None,
            "channel_name": None,
            "seen_ids": [],
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
    def initialized(self) -> bool:
        return bool(self.data.get("initialized"))

    def seen_ids(self) -> List[str]:
        return list(self.data.get("seen_ids") or [])

    def has_seen(self, article_id: str) -> bool:
        return article_id in (self.data.get("seen_ids") or [])

    async def set_channel(self, channel_id: int, channel_name: str) -> None:
        self.data["channel_id"] = channel_id
        self.data["channel_name"] = channel_name
        await self.save()

    async def mark_seen(self, article_ids: List[str]) -> None:
        seen = self.data.setdefault("seen_ids", [])
        for article_id in article_ids:
            if article_id and article_id not in seen:
                seen.append(article_id)
        # 오래된 ID는 최근 400개만 유지
        if len(seen) > 400:
            self.data["seen_ids"] = seen[-400:]
        await self.save()

    async def mark_initialized(self, article_ids: List[str]) -> None:
        self.data["initialized"] = True
        await self.mark_seen(article_ids)
