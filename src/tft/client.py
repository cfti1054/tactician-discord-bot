from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional
from urllib.parse import urljoin

import aiohttp

TFT_ORIGIN = "https://teamfighttactics.leagueoflegends.com"
PATCH_LIST_URL = f"{TFT_ORIGIN}/ko-kr/news/tags/patch-notes/"
NEWS_LIST_URL = f"{TFT_ORIGIN}/ko-kr/news/"
USER_AGENT = (
    "TacticianDiscordBot/1.0 (TFT official news digest)"
)
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)


@dataclass
class NewsCard:
    id: str
    title: str
    description: str
    url: str
    published_at: str
    category: str
    category_title: str
    tags: List[str] = field(default_factory=list)
    image_url: Optional[str] = None
    is_patch: bool = False


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        if "body" in value:
            return _strip_tags(str(value.get("body") or "")).strip()
        if "title" in value:
            return str(value.get("title") or "").strip()
    return str(value).strip()


def _strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


def _absolute_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("/"):
        return urljoin(TFT_ORIGIN, url)
    return url


def _media_url(item: dict) -> Optional[str]:
    for key in ("imageMedia", "media", "banner"):
        media = item.get(key)
        if isinstance(media, dict) and media.get("url"):
            return str(media["url"])
    return None


def _extract_next_data(html: str) -> dict:
    match = NEXT_DATA_RE.search(html)
    if not match:
        raise ValueError("공식 페이지에서 기사 데이터를 찾지 못했습니다.")
    return json.loads(match.group(1))


def _page_from_next_data(payload: dict) -> dict:
    return payload["props"]["pageProps"]["page"]


def _card_from_item(item: dict) -> Optional[NewsCard]:
    title = _text(item.get("title"))
    action = item.get("action") or {}
    payload = action.get("payload") or {}
    url = _absolute_url(payload.get("url") or action.get("url") or "")
    if not title or not url:
        return None

    analytics = item.get("analytics") or {}
    article_id = str(
        analytics.get("contentId")
        or url
        or title
    )
    category = item.get("category") or {}
    tags = []
    for tag in item.get("tags") or []:
        name = tag.get("machineName") or tag.get("title") or ""
        if name:
            tags.append(str(name))

    is_patch = (
        "patch_notes" in tags
        or "패치 노트" in tags
        or "patch-" in url
        or ("패치" in title and "game-updates" in str(category.get("machineName") or ""))
    )
    return NewsCard(
        id=article_id,
        title=title,
        description=_text(item.get("description")),
        url=url,
        published_at=str(item.get("publishedAt") or analytics.get("publishDate") or ""),
        category=str(category.get("machineName") or ""),
        category_title=str(category.get("title") or ""),
        tags=tags,
        image_url=_media_url(item),
        is_patch=is_patch,
    )


def parse_article_cards(html: str) -> List[NewsCard]:
    page = _page_from_next_data(_extract_next_data(html))
    cards: List[NewsCard] = []
    seen = set()
    for blade in page.get("blades") or []:
        if blade.get("type") != "articleCardGrid":
            continue
        for item in blade.get("items") or []:
            card = _card_from_item(item)
            if card is None or card.id in seen:
                continue
            seen.add(card.id)
            cards.append(card)
    return cards


def parse_article_page(html: str, fallback: Optional[NewsCard] = None) -> dict:
    page = _page_from_next_data(_extract_next_data(html))
    masthead = {}
    rich_html = ""
    for blade in page.get("blades") or []:
        blade_type = blade.get("type")
        if blade_type == "articleMasthead":
            masthead = blade
        elif blade_type in ("patchNotesRichText", "articleRichText", "richText"):
            rich = blade.get("richText") or {}
            if isinstance(rich, dict):
                rich_html = str(rich.get("body") or "")
            elif isinstance(rich, str):
                rich_html = rich

    title = _text(masthead.get("title") or page.get("title") or (fallback.title if fallback else ""))
    description = _text(
        masthead.get("description")
        or page.get("description")
        or (fallback.description if fallback else "")
    )
    url = page.get("url") or (fallback.url if fallback else "")
    published_at = str(
        masthead.get("publishDate")
        or page.get("displayedPublishDate")
        or (fallback.published_at if fallback else "")
    )
    image_url = _media_url(masthead) or (fallback.image_url if fallback else None)
    tags = []
    for tag in masthead.get("tags") or []:
        name = tag.get("machineName") or tag.get("title") or ""
        if name:
            tags.append(str(name))
    if fallback:
        for tag in fallback.tags:
            if tag not in tags:
                tags.append(tag)

    is_patch = page.get("type") == "patchNote" or (fallback.is_patch if fallback else False)
    return {
        "id": fallback.id if fallback else str(page.get("id") or url),
        "title": title,
        "description": description,
        "url": url,
        "published_at": published_at,
        "image_url": image_url,
        "tags": tags,
        "is_patch": is_patch,
        "body_html": rich_html,
        "category_title": (fallback.category_title if fallback else "")
        or _text((masthead.get("category") or {}).get("title")),
    }


class TftNewsClient:
    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None

    async def _session_get(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=25)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept-Language": "ko-KR,ko;q=0.9",
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Encoding": "gzip, deflate",
                },
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def fetch_html(self, url: str) -> str:
        session = await self._session_get()
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.text()

    async def fetch_cards(self, url: str) -> List[NewsCard]:
        html = await self.fetch_html(url)
        return parse_article_cards(html)

    async def fetch_patch_cards(self) -> List[NewsCard]:
        return await self.fetch_cards(PATCH_LIST_URL)

    async def fetch_news_cards(self) -> List[NewsCard]:
        return await self.fetch_cards(NEWS_LIST_URL)

    async def fetch_article(self, card: NewsCard) -> dict:
        if not card.url.startswith(TFT_ORIGIN):
            return {
                "id": card.id,
                "title": card.title,
                "description": card.description,
                "url": card.url,
                "published_at": card.published_at,
                "image_url": card.image_url,
                "tags": card.tags,
                "is_patch": card.is_patch,
                "body_html": "",
                "category_title": card.category_title,
            }
        html = await self.fetch_html(card.url)
        return parse_article_page(html, fallback=card)
