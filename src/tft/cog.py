from __future__ import annotations

import os
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from dotenv import load_dotenv

from tft.client import NewsCard, TftNewsClient
from tft.store import PROJECT_ROOT, TftDigestStore
from tft.summarize import (
    ChangeItem,
    PatchSummary,
    build_section_fields,
    summarize_patch_html,
)

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

KST = ZoneInfo("Asia/Seoul")
DEFAULT_POLL_MINUTES = 30
MAX_POSTS_PER_CYCLE = 3
NOTIFY_CATEGORIES = {"game-updates", "dev"}
SKIP_CATEGORIES = {"merch"}
PATCH_COLOR = 0xC8AA6E
BUFF_COLOR = 0x57F287
NERF_COLOR = 0xED4245
MIXED_COLOR = 0xFEE75C
OTHER_COLOR = 0x5865F2
NEWS_COLOR = 0x5865F2
EMBED_BATCH_SIZE = 10


def _parse_published_at(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _footer_time(value: str) -> str:
    parsed = _parse_published_at(value)
    if parsed is None:
        return "공식 TFT 사이트"
    local = parsed.astimezone(KST)
    return f"공식 TFT 사이트 · {local.strftime('%Y-%m-%d %H:%M')} KST"


def _category_embeds(title: str, items: List[ChangeItem], color: int) -> List[discord.Embed]:
    if not items:
        return []

    fields = build_section_fields(items)
    embeds: List[discord.Embed] = []
    current = discord.Embed(title=title, color=color)
    field_count = 0

    for name, value in fields:
        if field_count >= 25:
            embeds.append(current)
            current = discord.Embed(title=f"{title} (계속)", color=color)
            field_count = 0
        current.add_field(name=f"▸ {name}", value=value, inline=False)
        field_count += 1

    embeds.append(current)
    return embeds


def build_patch_embeds(summary: PatchSummary) -> List[discord.Embed]:
    intro = summary.intro or "공식 패치 노트에서 변경 사항을 정리했습니다."
    if len(intro) > 300:
        intro = intro[:297] + "..."

    header = discord.Embed(
        title=f"📌 {summary.title}",
        description=intro,
        url=summary.url,
        color=PATCH_COLOR,
    )
    header.add_field(name="🔺 상향", value=f"**{len(summary.buffs)}**", inline=True)
    header.add_field(name="🔻 하향", value=f"**{len(summary.nerfs)}**", inline=True)
    if summary.mixed:
        header.add_field(name="⚖️ 조정", value=f"**{len(summary.mixed)}**", inline=True)
    if summary.others:
        header.add_field(name="📝 기타", value=f"**{len(summary.others)}**", inline=True)
    header.add_field(
        name="📄 원문",
        value=f"[패치 노트 열기]({summary.url})",
        inline=False,
    )
    if summary.image_url:
        header.set_thumbnail(url=summary.image_url)
    header.set_footer(text=_footer_time(summary.published_at) + " · 규칙 기반 요약")

    embeds: List[discord.Embed] = [header]
    embeds.extend(_category_embeds("🔺 상향", summary.buffs, BUFF_COLOR))
    embeds.extend(_category_embeds("🔻 하향", summary.nerfs, NERF_COLOR))
    embeds.extend(_category_embeds("⚖️ 조정", summary.mixed, MIXED_COLOR))
    embeds.extend(_category_embeds("📝 기타 변경", summary.others, OTHER_COLOR))

    if len(embeds) == 1:
        header.add_field(
            name="요약",
            value="규칙으로 나눌 변경 줄을 찾지 못했습니다. 원문을 확인해 주세요.",
            inline=False,
        )

    return embeds


async def send_patch_summary(
    target,
    summary: PatchSummary,
    *,
    prefix: str = "",
) -> None:
    embeds = build_patch_embeds(summary)
    first_batch = embeds[:EMBED_BATCH_SIZE]
    await target.send(content=prefix or None, embeds=first_batch)

    for index in range(EMBED_BATCH_SIZE, len(embeds), EMBED_BATCH_SIZE):
        await target.send(embeds=embeds[index : index + EMBED_BATCH_SIZE])


def build_patch_embed(summary: PatchSummary) -> discord.Embed:
    return build_patch_embeds(summary)[0]


def build_news_embed(card: NewsCard, extra_description: str = "") -> discord.Embed:
    description = extra_description or card.description or "공식 TFT 새 소식입니다."
    if len(description) > 400:
        description = description[:397] + "..."

    embed = discord.Embed(
        title=f"📰 {card.title}",
        description=description,
        url=card.url,
        color=NEWS_COLOR,
    )
    if card.image_url:
        embed.set_image(url=card.image_url)
    if card.category_title:
        embed.add_field(name="분류", value=card.category_title, inline=True)
    embed.add_field(name="원문", value=f"[글 열기]({card.url})", inline=True)
    embed.set_footer(text=_footer_time(card.published_at))
    return embed


def should_auto_notify(card: NewsCard) -> bool:
    if card.category in SKIP_CATEGORIES:
        return False
    if card.is_patch:
        return True
    return card.category in NOTIFY_CATEGORIES


class TftDigest(commands.Cog):
    def __init__(self, bot: commands.Bot, guild_id: Optional[str] = None) -> None:
        self.bot = bot
        self.guild_id = int(guild_id) if guild_id else None
        self.store = TftDigestStore()
        self.client = TftNewsClient()
        self.poll_minutes = DEFAULT_POLL_MINUTES

    async def cog_load(self) -> None:
        self.store.load()
        try:
            self.poll_minutes = max(5, int(os.getenv("TFT_POLL_MINUTES", str(DEFAULT_POLL_MINUTES))))
        except ValueError:
            self.poll_minutes = DEFAULT_POLL_MINUTES
        self.check_tft_news.change_interval(minutes=self.poll_minutes)
        if not self.check_tft_news.is_running():
            self.check_tft_news.start()
        print(
            f"TFT 소식 모듈 로드 완료 (저장 경로: {self.store.filepath}, "
            f"확인 주기: {self.poll_minutes}분)"
        )

    async def cog_unload(self) -> None:
        self.check_tft_news.cancel()
        await self.client.close()

    def _target_guild_ok(self, guild: Optional[discord.Guild]) -> bool:
        if guild is None:
            return False
        if self.guild_id is None:
            return True
        return guild.id == self.guild_id

    async def _resolve_channel(self) -> Optional[discord.TextChannel]:
        channel_id = self.store.channel_id
        if channel_id is None:
            return None
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                fetched = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                return None
            channel = fetched
        if not isinstance(channel, discord.TextChannel):
            return None
        if not self._target_guild_ok(channel.guild):
            return None
        return channel

    async def _latest_patch_card(self) -> Optional[NewsCard]:
        cards = await self.client.fetch_patch_cards()
        return cards[0] if cards else None

    async def _build_patch_summary(self, card: NewsCard) -> PatchSummary:
        article = await self.client.fetch_article(card)
        return summarize_patch_html(
            body_html=article.get("body_html") or "",
            title=article.get("title") or card.title,
            url=article.get("url") or card.url,
            published_at=article.get("published_at") or card.published_at,
            image_url=article.get("image_url") or card.image_url,
            intro_fallback=article.get("description") or card.description,
        )

    async def _collect_new_cards(self) -> List[NewsCard]:
        patch_cards = await self.client.fetch_patch_cards()
        news_cards = await self.client.fetch_news_cards()

        combined: List[NewsCard] = []
        seen = set()
        for card in patch_cards + news_cards:
            if card.id in seen:
                continue
            seen.add(card.id)
            combined.append(card)

        combined.sort(
            key=lambda card: card.published_at or "",
            reverse=True,
        )
        return combined

    async def _post_new_items(self, channel: discord.TextChannel, cards: List[NewsCard]) -> int:
        posted = 0
        newly_seen: List[str] = []
        for card in cards:
            if self.store.has_seen(card.id):
                continue
            if not should_auto_notify(card):
                newly_seen.append(card.id)
                continue
            if posted >= MAX_POSTS_PER_CYCLE:
                break
            try:
                if card.is_patch:
                    summary = await self._build_patch_summary(card)
                    await send_patch_summary(channel, summary)
                else:
                    embed = build_news_embed(card)
                    await channel.send(embed=embed)
                posted += 1
            except Exception as exc:
                print(f"TFT 소식 게시 실패 ({card.title}): {exc}")
            newly_seen.append(card.id)

        await self.store.mark_seen(newly_seen)
        return posted

    @tasks.loop(minutes=DEFAULT_POLL_MINUTES)
    async def check_tft_news(self) -> None:
        channel = await self._resolve_channel()
        if channel is None:
            return

        try:
            cards = await self._collect_new_cards()
        except Exception as exc:
            print(f"TFT 소식 수집 실패: {exc}")
            return

        if not cards:
            return

        if not self.store.initialized:
            latest_patch = next((card for card in cards if card.is_patch), None)
            if latest_patch is not None:
                try:
                    summary = await self._build_patch_summary(latest_patch)
                    await send_patch_summary(
                        channel,
                        summary,
                        prefix="✅ TFT 알림을 시작했습니다. 현재 최신 패치입니다.",
                    )
                except Exception as exc:
                    print(f"TFT 초기 패치 게시 실패: {exc}")
            await self.store.mark_initialized([card.id for card in cards])
            print(f"TFT 소식 초기화 완료 : 기존 {len(cards)}건은 중복 알림에서 제외")
            return

        posted = await self._post_new_items(channel, cards)
        if posted:
            print(f"TFT 새 소식 게시 : {posted}건")

    @check_tft_news.before_loop
    async def before_check_tft_news(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(name="tft알림설정", description="TFT 패치·소식 자동 알림 채널을 설정합니다.")
    @app_commands.describe(channel="알림을 받을 텍스트 채널")
    async def set_tft_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ):
        if interaction.guild is None or not self._target_guild_ok(interaction.guild):
            await interaction.response.send_message(
                "❌ 이 서버에서는 사용할 수 없습니다.",
                ephemeral=True,
            )
            return

        await self.store.set_channel(channel.id, channel.name)
        await interaction.response.send_message(
            f"✅ TFT 알림 채널을 {channel.mention}(으)로 설정했습니다.\n"
            f"약 {self.poll_minutes}분마다 공식 패치·소식을 확인하고, "
            "새 글이 있으면 규칙 기반으로 요약해 올립니다.",
            ephemeral=True,
        )
        if not self.store.initialized:
            self.check_tft_news.restart()

    @app_commands.command(name="tft패치", description="최신 롤토체스 공식 패치를 규칙 기반으로 요약합니다.")
    async def latest_patch(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            card = await self._latest_patch_card()
            if card is None:
                await interaction.followup.send("❌ 공식 패치 노트를 찾지 못했습니다.")
                return
            summary = await self._build_patch_summary(card)
        except Exception as exc:
            await interaction.followup.send(
                f"❌ 패치 노트를 가져오지 못했습니다.\n`{exc}`"
            )
            return
        await send_patch_summary(interaction.followup, summary)

    @app_commands.command(name="tft소식", description="롤토체스 공식 새 소식 최근 글을 보여줍니다.")
    async def latest_news(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            cards = await self.client.fetch_news_cards()
        except Exception as exc:
            await interaction.followup.send(
                f"❌ 공식 소식을 가져오지 못했습니다.\n`{exc}`"
            )
            return

        cards = cards[:5]
        if not cards:
            await interaction.followup.send("❌ 표시할 소식이 없습니다.")
            return

        lines = []
        for card in cards:
            stamp = card.published_at[:10] if card.published_at else ""
            kind = "패치" if card.is_patch else (card.category_title or "소식")
            lines.append(f"• **[{kind}]** [{card.title}]({card.url}) `{stamp}`")

        embed = discord.Embed(
            title="📰 TFT 공식 새 소식",
            description="\n".join(lines),
            color=NEWS_COLOR,
            url="https://teamfighttactics.leagueoflegends.com/ko-kr/news/",
        )
        embed.set_footer(text="공식 TFT 사이트")
        await interaction.followup.send(embed=embed)
