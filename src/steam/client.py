from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode

import aiohttp

STEAM_STORE = "https://store.steampowered.com"
USER_AGENT = "TacticianDiscordBot/1.0 (Steam sale digest)"
SEARCH_ROW_RE = re.compile(
    r'data-ds-appid="(?P<app_id>\d+)".*?'
    r'(?:data-ds-tagids="(?P<tagids>\[[^\]]*\])".*?)?'
    r'(?:data-ds-descids="(?P<descids>\[[^\]]*\])".*?)?'
    r'<span class="title">(?P<name>.*?)</span>.*?'
    r'data-discount="(?P<discount>\d+)".*?'
    r'data-price-final="(?P<final>\d+)".*?'
    r'<div class="discount_original_price">(?P<original>.*?)</div>.*?'
    r'<div class="discount_final_price">(?P<final_text>.*?)</div>',
    re.DOTALL,
)
TAG_BROWSE_RE = re.compile(r'data-tagid="(\d+)"[^>]*>([^<]+)')
MAX_DISPLAY_TAGS = 3
SKIP_TAG_NAMES = {
    "싱글 플레이어",
    "멀티플레이어",
    "협동",
    "PvP",
    "PvE",
    "Steam 도전 과제",
    "Steam 트레이딩 카드",
    "Steam Cloud",
    "Steam Workshop",
    "컨트롤러 완벽 지원",
    "부분 컨트롤러 지원",
    "Remote Play",
    "Remote Play 태블릿",
    "Remote Play TV",
    "가족 공유",
    "크로스 플랫폼 멀티플레이어",
    "크로스 플랫폼",
    "Steam Deck",
    "HDR 사용 가능",
}
CONTENT_DESCRIPTOR_LABELS = {
    1: "성적",
    2: "폭력",
    3: "성인전용",
    4: "선정적",
    5: "성숙",
}
SEXUAL_TAG_KEYWORDS = ("성적", "선정", "헨타이", "노출", "나체", "NSFW", "감성적")
SALE_URL_RE = re.compile(
    r"(?:https?://store\.steampowered\.com)?/sale/([A-Za-z0-9_-]+)",
    re.I,
)
MAJOR_SALE_KINDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("winter", ("winter", "겨울")),
    ("summer", ("summer", "여름")),
    ("spring", ("spring", "봄")),
    ("autumn", ("autumn", "fall", "가을")),
    ("lunar", ("lunar", "newyear", "new-year", "new_year", "설날", "신년")),
    ("holiday", ("holiday", "christmas", "xmas", "크리스마스", "홀리데이")),
)
MAJOR_SALE_EXCLUDE = (
    "publisher",
    "developer",
    "weekend",
    "midweek",
    "daily",
    "nextfest",
    "next-fest",
    "festival",
)
SALE_KIND_DISPLAY = {
    "winter": ("🎄", "Steam 겨울 세일"),
    "summer": ("☀️", "Steam 여름 세일"),
    "spring": ("🌸", "Steam 봄 세일"),
    "autumn": ("🍂", "Steam 가을 세일"),
    "lunar": ("🧧", "Steam 설/신년 세일"),
    "holiday": ("🎅", "Steam 홀리데이 세일"),
    "major": ("🏷️", "Steam 시즌 세일"),
}


@dataclass
class SteamDeal:
    app_id: int
    name: str
    discount_percent: int
    original_price: int
    final_price: int
    currency: str
    image_url: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    @property
    def store_url(self) -> str:
        return f"{STEAM_STORE}/app/{self.app_id}"

    @property
    def deal_key(self) -> str:
        return f"{self.app_id}:{self.discount_percent}"


@dataclass
class SteamSaleEvent:
    sale_id: str
    name: str
    url: str
    kind: str
    image_url: Optional[str] = None
    body: Optional[str] = None

    @property
    def display(self) -> Tuple[str, str]:
        return SALE_KIND_DISPLAY.get(self.kind, SALE_KIND_DISPLAY["major"])


def classify_major_sale(sale_id: str, name: str = "") -> Optional[str]:
    sale_id_lower = sale_id.lower()
    if any(token in sale_id_lower for token in MAJOR_SALE_EXCLUDE):
        return None

    blob = f"{sale_id} {name}".lower()
    for kind, tokens in MAJOR_SALE_KINDS:
        if any(token in blob for token in tokens):
            return kind

    if sale_id_lower.startswith("steam") and "sale" in sale_id_lower:
        return "major"
    return None


def format_steam_price(amount: int, currency: str = "KRW") -> str:
    value = amount / 100
    if currency == "KRW":
        return f"₩ {int(value):,}"
    return f"{currency} {value:,.2f}"


def _parse_id_list(raw: Optional[str]) -> List[int]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [int(item) for item in parsed if str(item).isdigit()]


def build_display_tags(
    tag_ids: List[int],
    desc_ids: List[int],
    tag_names: Dict[int, str],
    *,
    max_tags: int = MAX_DISPLAY_TAGS,
) -> List[str]:
    tags: List[str] = []
    for tag_id in tag_ids:
        name = tag_names.get(tag_id)
        if not name or name in SKIP_TAG_NAMES:
            continue
        if name not in tags:
            tags.append(name)
        if len(tags) >= 2:
            break

    sexual_in_tags = any(
        any(keyword in tag for keyword in SEXUAL_TAG_KEYWORDS) for tag in tags
    )
    for desc_id in desc_ids:
        label = CONTENT_DESCRIPTOR_LABELS.get(desc_id)
        if not label or label in tags:
            continue
        if desc_id in (1, 3, 4) and sexual_in_tags:
            continue
        tags.append(label)
        break

    return tags[:max_tags]


def format_deal_line(deal: SteamDeal) -> str:
    final = format_steam_price(deal.final_price, deal.currency)
    prefix = ""
    if deal.tags:
        prefix = f"`{' · '.join(deal.tags)}` "
    return f"• **-{deal.discount_percent}%** {prefix}[{deal.name}]({deal.store_url}) — {final}"


class SteamStoreClient:
    def __init__(self) -> None:
        self.cc = os.getenv("STEAM_CC", "kr")
        self.lang = os.getenv("STEAM_LANG", "korean")
        self._session: Optional[aiohttp.ClientSession] = None
        self._tag_names: Dict[int, str] = {}
        self._tags_loaded = False

    async def _session_get(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept-Language": "ko-KR,ko;q=0.9",
                    "Accept": "application/json,text/html",
                    "Accept-Encoding": "gzip, deflate",
                },
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def fetch_json(self, path: str, params: Optional[dict] = None) -> dict:
        session = await self._session_get()
        query = {"cc": self.cc, "l": self.lang}
        if params:
            query.update(params)
        url = f"{STEAM_STORE}{path}?{urlencode(query)}"
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.json(content_type=None)

    async def _ensure_tag_names(self) -> None:
        if self._tags_loaded:
            return
        session = await self._session_get()
        url = f"{STEAM_STORE}/tag/browse/?l={self.lang}"
        async with session.get(url) as response:
            response.raise_for_status()
            html = await response.text()
        self._tag_names = {
            int(tag_id): name.strip()
            for tag_id, name in TAG_BROWSE_RE.findall(html)
        }
        self._tags_loaded = True

    async def fetch_featured_specials(self) -> List[SteamDeal]:
        payload = await self.fetch_json("/api/featuredcategories/")
        return self.parse_featured_specials(payload)

    def parse_featured_specials(self, payload: dict) -> List[SteamDeal]:
        specials = payload.get("specials") or {}
        deals: List[SteamDeal] = []
        for item in specials.get("items") or []:
            deal = self._deal_from_featured_item(item)
            if deal is not None:
                deals.append(deal)
        return deals

    def parse_sale_events(self, payload: dict) -> List[SteamSaleEvent]:
        events: List[SteamSaleEvent] = []
        seen: set[str] = set()
        for value in payload.values():
            if not isinstance(value, dict):
                continue
            items = value.get("items")
            candidates = items if isinstance(items, list) else [value]
            for item in candidates:
                event = self._event_from_featured_item(item)
                if event is None or event.sale_id in seen:
                    continue
                seen.add(event.sale_id)
                events.append(event)
        return events

    async def fetch_major_sale_events(self) -> List[SteamSaleEvent]:
        payload = await self.fetch_json("/api/featuredcategories/")
        return [event for event in self.parse_sale_events(payload) if event.kind]

    def _event_from_featured_item(self, item: object) -> Optional[SteamSaleEvent]:
        if not isinstance(item, dict):
            return None
        url = str(item.get("url") or "")
        match = SALE_URL_RE.search(url)
        if not match:
            return None
        sale_id = match.group(1)
        name = str(item.get("name") or sale_id).strip() or sale_id
        kind = classify_major_sale(sale_id, name)
        if kind is None:
            return None
        return SteamSaleEvent(
            sale_id=sale_id,
            name=name,
            url=f"{STEAM_STORE}/sale/{sale_id}",
            kind=kind,
            image_url=item.get("header_image") or None,
            body=str(item.get("body") or "") or None,
        )

    async def fetch_search_specials(
        self,
        min_discount: int,
        count: int = 100,
        start: int = 0,
    ) -> List[SteamDeal]:
        session = await self._session_get()
        params = {
            "query": "",
            "start": str(start),
            "count": str(count),
            "dynamic_data": "",
            "sort_by": "Price ASC",
            "specials": "1",
            "maxdiscount": "999",
            "mindiscount": str(min_discount),
            "supportedlang": "koreana" if self.lang == "korean" else self.lang,
            "infinite": "1",
            "cc": self.cc,
            "l": self.lang,
        }
        url = f"{STEAM_STORE}/search/results/?{urlencode(params)}"
        async with session.get(url) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)

        html = payload.get("results_html") or ""
        await self._ensure_tag_names()
        return self.parse_search_html(html, self._tag_names)

    def parse_search_html(
        self,
        html: str,
        tag_names: Optional[Dict[int, str]] = None,
    ) -> List[SteamDeal]:
        tag_names = tag_names or {}
        deals: List[SteamDeal] = []
        seen: set[int] = set()
        for match in SEARCH_ROW_RE.finditer(html):
            app_id = int(match.group("app_id"))
            if app_id in seen:
                continue
            seen.add(app_id)
            name = re.sub(r"\s+", " ", match.group("name")).strip()
            original_text = match.group("original").strip()
            tag_ids = _parse_id_list(match.group("tagids"))
            desc_ids = _parse_id_list(match.group("descids"))
            tags = build_display_tags(tag_ids, desc_ids, tag_names)
            deals.append(
                SteamDeal(
                    app_id=app_id,
                    name=name,
                    discount_percent=int(match.group("discount")),
                    original_price=self._price_text_to_int(original_text),
                    final_price=int(match.group("final")),
                    currency="KRW" if "₩" in original_text else self.cc.upper(),
                    image_url=(
                        f"https://shared.fastly.steamstatic.com/store_item_assets/"
                        f"steam/apps/{app_id}/header.jpg"
                    ),
                    tags=tags,
                )
            )
        return deals

    async def fetch_deals(self, min_discount: int, search_count: int = 100) -> List[SteamDeal]:
        featured = await self.fetch_featured_specials()
        searched = await self.fetch_search_specials(
            min_discount=min_discount,
            count=search_count,
        )

        merged: Dict[int, SteamDeal] = {}
        for deal in featured + searched:
            if deal.discount_percent < min_discount:
                continue
            current = merged.get(deal.app_id)
            if current is None or deal.discount_percent > current.discount_percent:
                merged[deal.app_id] = deal
            elif (
                deal.discount_percent == current.discount_percent
                and deal.tags
                and not current.tags
            ):
                merged[deal.app_id] = deal

        deals = list(merged.values())
        deals.sort(key=lambda deal: (-deal.discount_percent, deal.name.lower()))
        return deals

    def _deal_from_featured_item(self, item: dict) -> Optional[SteamDeal]:
        if not item.get("discounted"):
            return None
        app_id = item.get("id")
        name = item.get("name")
        if not app_id or not name:
            return None
        return SteamDeal(
            app_id=int(app_id),
            name=str(name),
            discount_percent=int(item.get("discount_percent") or 0),
            original_price=int(item.get("original_price") or 0),
            final_price=int(item.get("final_price") or 0),
            currency=str(item.get("currency") or "KRW"),
            image_url=item.get("header_image") or item.get("large_capsule_image"),
        )

    @staticmethod
    def _price_text_to_int(text: str) -> int:
        digits = re.sub(r"[^\d]", "", text)
        if not digits:
            return 0
        # HTML display uses whole won; API stores won * 100
        return int(digits) * 100
