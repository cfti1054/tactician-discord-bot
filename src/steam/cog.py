from __future__ import annotations

import os
from typing import List, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from dotenv import load_dotenv

from steam.client import (
    SteamDeal,
    SteamSaleEvent,
    SteamStoreClient,
    format_deal_line,
)
from steam.store import PROJECT_ROOT, DEFAULT_MIN_DISCOUNT, SteamDigestStore

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

DEFAULT_POLL_MINUTES = 60
COMMAND_DEALS_PER_PAGE = 10
ALERT_DEALS_PER_PAGE = 18
ALERT_VIEW_TIMEOUT = 3600
STEAM_COLOR = 0x1B2838
STEAM_EVENT_COLOR = 0x66C0F4


def build_deals_list_embed(deals: List[SteamDeal], title: str) -> discord.Embed:
    lines = [format_deal_line(deal) for deal in deals]

    embed = discord.Embed(
        title=title,
        description="\n".join(lines) if lines else "표시할 할인 게임이 없습니다.",
        color=STEAM_COLOR,
        url="https://store.steampowered.com/search/?specials=1",
    )
    embed.set_footer(text="Steam Store · 한국 스토어 기준")
    return embed


def build_sale_event_embed(event: SteamSaleEvent) -> discord.Embed:
    emoji, title = event.display
    embed = discord.Embed(
        title=f"{emoji} {title} 시작!",
        url=event.url,
        color=STEAM_EVENT_COLOR,
        description=(
            f"**{event.name}** 이(가) Steam 스토어에 올랐습니다.\n"
            "세일 기간 동안 개별 할인 알림은 잠시 쉬고, "
            "아래 목록과 세일 페이지에서 확인하세요."
        ),
    )
    embed.add_field(
        name="세일 페이지",
        value=f"[Steam에서 보기]({event.url})",
        inline=False,
    )
    if event.image_url:
        embed.set_image(url=event.image_url)
    embed.set_footer(text="Steam Store · 한국 스토어 기준 · 시즌 세일 알림")
    return embed


class SteamDealsListView(discord.ui.View):
    def __init__(
        self,
        deals: List[SteamDeal],
        title: str,
        *,
        per_page: int = COMMAND_DEALS_PER_PAGE,
        timeout: float = 600,
    ) -> None:
        super().__init__(timeout=timeout)
        self.deals = deals
        self.title = title
        self.page = 0
        self.per_page = per_page
        self.total_pages = max(1, (len(deals) + self.per_page - 1) // self.per_page)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.prev_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self.total_pages - 1

    def build_embed(self) -> discord.Embed:
        start = self.page * self.per_page
        page_deals = self.deals[start : start + self.per_page]
        embed = build_deals_list_embed(page_deals, self.title)
        embed.set_footer(
            text=(
                f"Steam Store · 한국 스토어 기준 · "
                f"{self.page + 1}/{self.total_pages} 페이지 · "
                f"총 {len(self.deals)}건"
            )
        )
        return embed

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary)
    async def prev_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self.page > 0:
            self.page -= 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary)
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self.page < self.total_pages - 1:
            self.page += 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


async def send_paginated_deals(
    channel: discord.abc.Messageable,
    deals: List[SteamDeal],
    *,
    title: str,
    content: Optional[str] = None,
    per_page: int = ALERT_DEALS_PER_PAGE,
    timeout: float = ALERT_VIEW_TIMEOUT,
) -> None:
    if not deals:
        return

    if len(deals) > per_page:
        view = SteamDealsListView(deals, title, per_page=per_page, timeout=timeout)
        await channel.send(content=content, embed=view.build_embed(), view=view)
        return

    await channel.send(content=content, embed=build_deals_list_embed(deals, title))


class SteamDeals(commands.Cog):
    def __init__(self, bot: commands.Bot, guild_id: Optional[str] = None) -> None:
        self.bot = bot
        self.guild_id = int(guild_id) if guild_id else None
        self.store = SteamDigestStore()
        self.client = SteamStoreClient()
        self.poll_minutes = DEFAULT_POLL_MINUTES
        self.search_count = 100

    async def cog_load(self) -> None:
        self.store.load()
        try:
            self.poll_minutes = max(
                15,
                int(os.getenv("STEAM_POLL_MINUTES", str(DEFAULT_POLL_MINUTES))),
            )
        except ValueError:
            self.poll_minutes = DEFAULT_POLL_MINUTES
        try:
            self.search_count = max(
                20,
                min(100, int(os.getenv("STEAM_SEARCH_COUNT", "100"))),
            )
        except ValueError:
            self.search_count = 100

        self.check_steam_deals.change_interval(minutes=self.poll_minutes)
        if not self.check_steam_deals.is_running():
            self.check_steam_deals.start()
        print(
            f"Steam 할인 모듈 로드 완료 (저장 경로: {self.store.filepath}, "
            f"확인 주기: {self.poll_minutes}분, 최소 할인: {self.store.min_discount}%)"
        )

    async def cog_unload(self) -> None:
        self.check_steam_deals.cancel()
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

    async def _fetch_deals(self, min_discount: Optional[int] = None) -> List[SteamDeal]:
        threshold = min_discount if min_discount is not None else self.store.min_discount
        return await self.client.fetch_deals(
            min_discount=threshold,
            search_count=self.search_count,
        )

    async def _post_new_deals(self, channel: discord.TextChannel, deals: List[SteamDeal]) -> int:
        new_deals = [deal for deal in deals if not self.store.has_seen(deal.deal_key)]
        if not new_deals:
            return 0

        try:
            await send_paginated_deals(
                channel,
                new_deals,
                content=f"🛎️ 새 Steam 할인 **{len(new_deals)}**건",
                title=f"🛒 Steam 신규 할인 · {self.store.min_discount}%+",
                per_page=ALERT_DEALS_PER_PAGE,
                timeout=ALERT_VIEW_TIMEOUT,
            )
        except Exception as exc:
            print(f"Steam 할인 게시 실패: {exc}")
            return 0

        await self.store.mark_seen([deal.deal_key for deal in new_deals])
        return len(new_deals)

    async def _sync_active_sale(self, major_sale_ids: List[str]) -> None:
        active = self.store.active_sale_id
        if active and active not in major_sale_ids:
            await self.store.set_active_sale(None)
            print(f"Steam 시즌 세일 종료 : {active}")

    async def _post_new_major_sales(
        self,
        channel: discord.TextChannel,
        events: List[SteamSaleEvent],
        deals: List[SteamDeal],
    ) -> int:
        posted = 0
        for event in events:
            if self.store.has_seen_sale(event.sale_id):
                continue
            try:
                await channel.send(embed=build_sale_event_embed(event))
                if deals:
                    await send_paginated_deals(
                        channel,
                        deals,
                        title=f"🛒 {event.display[1]} 할인 목록 · {self.store.min_discount}%+",
                        per_page=ALERT_DEALS_PER_PAGE,
                        timeout=ALERT_VIEW_TIMEOUT,
                    )
            except Exception as exc:
                print(f"Steam 시즌 세일 게시 실패 ({event.sale_id}): {exc}")
                continue
            await self.store.mark_sales_seen([event.sale_id])
            await self.store.set_active_sale(event.sale_id)
            posted += 1
            print(f"Steam 시즌 세일 게시 : {event.sale_id}")
        return posted

    async def _suppress_deals_during_sale(self, deals: List[SteamDeal]) -> int:
        new_keys = [
            deal.deal_key for deal in deals if not self.store.has_seen(deal.deal_key)
        ]
        if new_keys:
            await self.store.mark_seen(new_keys)
        return len(new_keys)

    @tasks.loop(minutes=DEFAULT_POLL_MINUTES)
    async def check_steam_deals(self) -> None:
        channel = await self._resolve_channel()
        if channel is None:
            return

        events: List[SteamSaleEvent] = []
        try:
            events = await self.client.fetch_major_sale_events()
        except Exception as exc:
            print(f"Steam 시즌 세일 수집 실패: {exc}")

        major_sale_ids = [event.sale_id for event in events]
        await self._sync_active_sale(major_sale_ids)

        try:
            deals = await self._fetch_deals()
        except Exception as exc:
            print(f"Steam 할인 수집 실패: {exc}")
            return

        if not deals:
            return

        if not self.store.initialized:
            try:
                await send_paginated_deals(
                    channel,
                    deals,
                    content=(
                        "✅ Steam 할인 알림을 시작했습니다. "
                        f"현재 **{self.store.min_discount}%** 이상 할인 목록입니다."
                    ),
                    title=f"🛒 Steam 할인 게임 · {self.store.min_discount}%+",
                    per_page=ALERT_DEALS_PER_PAGE,
                    timeout=ALERT_VIEW_TIMEOUT,
                )
            except Exception as exc:
                print(f"Steam 초기 할인 게시 실패: {exc}")
            await self.store.mark_initialized([deal.deal_key for deal in deals])
            await self.store.mark_sales_seen(major_sale_ids)
            if major_sale_ids:
                await self.store.set_active_sale(major_sale_ids[0])
            print(f"Steam 할인 초기화 완료 : 기존 {len(deals)}건은 중복 알림에서 제외")
            return

        announced = await self._post_new_major_sales(channel, events, deals)
        if announced:
            suppressed = await self._suppress_deals_during_sale(deals)
            if suppressed:
                print(f"Steam 시즌 세일 진행 중 : 게임 할인 {suppressed}건은 저장만")
            return

        if self.store.active_sale_id:
            suppressed = await self._suppress_deals_during_sale(deals)
            if suppressed:
                print(f"Steam 시즌 세일 진행 중 : 게임 할인 {suppressed}건은 저장만")
            return

        posted = await self._post_new_deals(channel, deals)
        if posted:
            print(f"Steam 새 할인 게시 : {posted}건")

    @check_steam_deals.before_loop
    async def before_check_steam_deals(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="스팀알림설정",
        description="Steam 할인 게임 자동 알림 채널과 최소 할인율을 설정합니다.",
    )
    @app_commands.describe(
        channel="알림을 받을 텍스트 채널",
        min_discount="알림할 최소 할인율(%)",
    )
    async def set_steam_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        min_discount: app_commands.Range[int, 1, 95] = DEFAULT_MIN_DISCOUNT,
    ):
        if interaction.guild is None or not self._target_guild_ok(interaction.guild):
            await interaction.response.send_message(
                "❌ 이 서버에서는 사용할 수 없습니다.",
                ephemeral=True,
            )
            return

        await self.store.set_channel(channel.id, channel.name)
        await self.store.set_min_discount(int(min_discount))
        await interaction.response.send_message(
            f"✅ Steam 할인 알림 채널을 {channel.mention}(으)로 설정했습니다.\n"
            f"**{min_discount}%** 이상 할인 게임을 약 **{self.poll_minutes}분**마다 확인합니다.\n"
            "겨울·여름 등 **대형 시즌 세일**이 시작되면 별도 공지를 올리고, "
            "세일 기간 중에는 개별 할인 알림을 잠시 쉽니다.",
            ephemeral=True,
        )
        if not self.store.initialized:
            self.check_steam_deals.restart()

    @app_commands.command(name="스팀할인", description="Steam 할인 게임 목록을 조회합니다.")
    @app_commands.describe(
        min_discount="최소 할인율(%)",
        count="표시할 게임 수",
    )
    async def list_steam_deals(
        self,
        interaction: discord.Interaction,
        min_discount: app_commands.Range[int, 1, 95] = DEFAULT_MIN_DISCOUNT,
        count: app_commands.Range[int, 1, 100] = 100,
    ):
        await interaction.response.defer()
        try:
            deals = await self._fetch_deals(min_discount=int(min_discount))
        except Exception as exc:
            await interaction.followup.send(
                f"❌ Steam 할인 정보를 가져오지 못했습니다.\n`{exc}`"
            )
            return

        deals = deals[: int(count)]
        title = f"🛒 Steam 할인 TOP {len(deals)} · {min_discount}%+"
        if not deals:
            await interaction.followup.send(
                embed=build_deals_list_embed(
                    deals,
                    f"🛒 Steam 할인 · {min_discount}%+",
                )
            )
            return

        if len(deals) > COMMAND_DEALS_PER_PAGE:
            view = SteamDealsListView(
                deals,
                title,
                per_page=COMMAND_DEALS_PER_PAGE,
            )
            await interaction.followup.send(embed=view.build_embed(), view=view)
            return

        await interaction.followup.send(embed=build_deals_list_embed(deals, title))
