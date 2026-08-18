from __future__ import annotations

import asyncio
import io
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

KST = ZoneInfo("Asia/Seoul")
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SRC_DIR)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
ACTIVITY_FILE = os.getenv(
    "ACTIVITY_FILE",
    os.path.join(PROJECT_ROOT, "data", "activity.json"),
)
TRACKED_FIELDS = ("voice_joins", "voice_seconds", "voice_messages", "messages")
GUILD_NAME_KEY = "_guild_name"
USER_NAME_KEY = "_user_name"


def is_user_id_key(key: str) -> bool:
    return key.isdigit()


def filter_daily_stats(user_data: dict) -> dict:
    return {
        key: value
        for key, value in user_data.items()
        if not key.startswith("_")
    }


def filter_guild_users(guild_data: dict) -> dict:
    return {
        key: value
        for key, value in guild_data.items()
        if is_user_id_key(key)
    }


def today_key(when: Optional[datetime] = None) -> str:
    moment = when or datetime.now(KST)
    return moment.astimezone(KST).strftime("%Y-%m-%d")


def distribute_seconds(start: datetime, end: datetime) -> Dict[str, int]:
    start = start.astimezone(KST)
    end = end.astimezone(KST)
    if end <= start:
        return {}

    result: Dict[str, int] = {}
    current = start
    while current < end:
        next_midnight = (
            current.replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(days=1)
        )
        segment_end = min(end, next_midnight)
        seconds = int((segment_end - current).total_seconds())
        if seconds > 0:
            date_key = current.strftime("%Y-%m-%d")
            result[date_key] = result.get(date_key, 0) + seconds
        current = segment_end
    return result


def format_duration(total_seconds: int) -> str:
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}시간 {minutes}분"
    if minutes:
        return f"{minutes}분 {seconds}초"
    return f"{seconds}초"


def is_attendance_day(day_stats: dict) -> bool:
    return any(day_stats.get(field, 0) > 0 for field in TRACKED_FIELDS)


class ActivityStore:
    def __init__(self, filepath: str = ACTIVITY_FILE):
        self.filepath = filepath
        self.data: dict = {}
        self.lock = asyncio.Lock()

    def load(self) -> None:
        if not os.path.exists(self.filepath):
            self.data = {}
            return

        with open(self.filepath, "r", encoding="utf-8") as file:
            self.data = json.load(file)

    async def save(self) -> None:
        async with self.lock:
            directory = os.path.dirname(self.filepath)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.filepath, "w", encoding="utf-8") as file:
                json.dump(self.data, file, indent=4, ensure_ascii=False)

    def _update_names(
        self,
        guild_id: int,
        guild_name: str,
        user_id: int,
        user_name: str,
    ) -> None:
        guild_key = str(guild_id)
        user_key = str(user_id)
        guild_data = self.data.setdefault(guild_key, {})
        guild_data[GUILD_NAME_KEY] = guild_name
        user_data = guild_data.setdefault(user_key, {})
        user_data[USER_NAME_KEY] = user_name

    def _day_stats(self, guild_id: int, user_id: int, date_key: str) -> dict:
        guild_key = str(guild_id)
        user_key = str(user_id)
        guild_data = self.data.setdefault(guild_key, {})
        user_data = guild_data.setdefault(user_key, {})
        day_stats = user_data.setdefault(date_key, {})
        for field in TRACKED_FIELDS:
            day_stats.setdefault(field, 0)
        return day_stats

    async def record(
        self,
        guild_id: int,
        guild_name: str,
        user_id: int,
        user_name: str,
        field: str,
        amount: int = 1,
        date_key: Optional[str] = None,
    ) -> None:
        self._update_names(guild_id, guild_name, user_id, user_name)
        day_stats = self._day_stats(guild_id, user_id, date_key or today_key())
        day_stats[field] += amount
        await self.save()

    async def add_voice_seconds(
        self,
        guild_id: int,
        user_id: int,
        seconds_by_day: Dict[str, int],
        guild_name: str = "",
        user_name: str = "",
    ) -> None:
        if guild_name and user_name:
            self._update_names(guild_id, guild_name, user_id, user_name)
        for date_key, seconds in seconds_by_day.items():
            if seconds <= 0:
                continue
            day_stats = self._day_stats(guild_id, user_id, date_key)
            day_stats["voice_seconds"] += seconds
        await self.save()

    def get_user_stats(self, guild_id: int, user_id: int) -> dict:
        user_data = self.data.get(str(guild_id), {}).get(str(user_id), {})
        return filter_daily_stats(user_data)

    def get_guild_stats(self, guild_id: int) -> dict:
        guild_data = self.data.get(str(guild_id), {})
        return filter_guild_users(guild_data)

    def get_user_name(self, guild_id: int, user_id: int) -> Optional[str]:
        user_data = self.data.get(str(guild_id), {}).get(str(user_id), {})
        name = user_data.get(USER_NAME_KEY)
        return name if isinstance(name, str) else None

    def get_guild_name(self, guild_id: int) -> Optional[str]:
        name = self.data.get(str(guild_id), {}).get(GUILD_NAME_KEY)
        return name if isinstance(name, str) else None

    def has_guild(self, guild_id: int) -> bool:
        return str(guild_id) in self.data

    def has_user(self, guild_id: int, user_id: int) -> bool:
        guild_data = self.data.get(str(guild_id), {})
        return str(user_id) in filter_guild_users(guild_data)

    def summarize_user(self, guild_id: int, user_id: int) -> dict:
        daily_stats = self.get_user_stats(guild_id, user_id)
        totals = {field: 0 for field in TRACKED_FIELDS}
        attendance_days = 0

        for day_stats in daily_stats.values():
            if is_attendance_day(day_stats):
                attendance_days += 1
            for field in TRACKED_FIELDS:
                totals[field] += day_stats.get(field, 0)

        return {
            "attendance_days": attendance_days,
            "daily_stats": daily_stats,
            **totals,
        }

    def summarize_user_period(
        self,
        guild_id: int,
        user_id: int,
        from_date: str,
        to_date: str,
        min_voice_seconds: int = 0,
        include_daily: bool = True,
    ) -> dict:
        daily_stats = self.get_user_stats(guild_id, user_id)
        totals = {field: 0 for field in TRACKED_FIELDS}
        attendance_days = 0
        qualified_days = 0
        daily = []

        for date_key in sorted(daily_stats.keys()):
            if date_key < from_date or date_key > to_date:
                continue
            day = daily_stats[date_key]
            attended = is_attendance_day(day)
            qualified = day.get("voice_seconds", 0) >= min_voice_seconds
            if attended:
                attendance_days += 1
            if qualified:
                qualified_days += 1
            for field in TRACKED_FIELDS:
                totals[field] += day.get(field, 0)
            if include_daily:
                daily.append(
                    {
                        "date": date_key,
                        **{field: day.get(field, 0) for field in TRACKED_FIELDS},
                        "attended": attended,
                        "qualified": qualified,
                    }
                )

        result = {
            "user_id": str(user_id),
            "user_name": self.get_user_name(guild_id, user_id),
            "attendance_days": attendance_days,
            "qualified_days": qualified_days,
            **totals,
        }
        if include_daily:
            result["daily"] = daily
        return result

    def summarize_guild_period(
        self,
        guild_id: int,
        from_date: str,
        to_date: str,
        min_voice_seconds: int = 0,
        include_daily: bool = True,
        skip_empty: bool = True,
    ) -> list:
        members = []
        for user_id in self.get_guild_stats(guild_id):
            summary = self.summarize_user_period(
                guild_id,
                int(user_id),
                from_date,
                to_date,
                min_voice_seconds,
                include_daily=include_daily,
            )
            if skip_empty and summary["attendance_days"] == 0:
                continue
            members.append(summary)

        members.sort(key=lambda row: (row.get("user_name") or row["user_id"]).lower())
        return members


class ActivityTracker(commands.Cog):
    def __init__(self, bot: commands.Bot, guild_id: Optional[str] = None):
        self.bot = bot
        self.guild_id = int(guild_id) if guild_id else None
        self.store = ActivityStore()
        self.voice_sessions: dict[tuple[int, int], datetime] = {}

    async def cog_load(self) -> None:
        self.store.load()
        print(f"활동 집계 모듈 로드 완료 (저장 경로: {self.store.filepath})")

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        synced = 0
        for guild in self.bot.guilds:
            if not self._should_track(guild.id):
                continue
            for channel in guild.voice_channels:
                for member in channel.members:
                    if member.bot:
                        continue
                    session_key = (guild.id, member.id)
                    if session_key not in self.voice_sessions:
                        self.voice_sessions[session_key] = datetime.now(KST)
                        synced += 1
        if synced:
            print(f"음성 세션 동기화 완료 : {synced}명")
        await self._backfill_names()

    async def _backfill_names(self) -> None:
        updated = False
        for guild_key, guild_data in self.store.data.items():
            if not is_user_id_key(guild_key):
                continue

            guild = self.bot.get_guild(int(guild_key))
            if guild and guild_data.get(GUILD_NAME_KEY) != guild.name:
                guild_data[GUILD_NAME_KEY] = guild.name
                updated = True

            for user_key, user_data in filter_guild_users(guild_data).items():
                if not isinstance(user_data, dict):
                    continue
                if guild is None:
                    continue
                member = guild.get_member(int(user_key))
                if member and user_data.get(USER_NAME_KEY) != member.display_name:
                    user_data[USER_NAME_KEY] = member.display_name
                    updated = True

        if updated:
            await self.store.save()

    def _should_track(self, guild_id: Optional[int]) -> bool:
        if guild_id is None:
            return False
        if self.guild_id is None:
            return True
        return guild_id == self.guild_id

    async def _record_voice_join(self, member: discord.Member) -> None:
        await self.store.record(
            member.guild.id,
            member.guild.name,
            member.id,
            member.display_name,
            "voice_joins",
        )

    async def _record_voice_leave(self, member: discord.Member, joined_at: datetime) -> None:
        seconds_by_day = distribute_seconds(joined_at, datetime.now(KST))
        await self.store.add_voice_seconds(
            member.guild.id,
            member.id,
            seconds_by_day,
            guild_name=member.guild.name,
            user_name=member.display_name,
        )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.bot or not self._should_track(member.guild.id):
            return

        session_key = (member.guild.id, member.id)

        if before.channel is None and after.channel is not None:
            self.voice_sessions[session_key] = datetime.now(KST)
            await self._record_voice_join(member)
            return

        if before.channel is not None and after.channel is None:
            joined_at = self.voice_sessions.pop(session_key, None)
            if joined_at is not None:
                await self._record_voice_leave(member, joined_at)
            return

        if before.channel is not None and after.channel is not None and before.channel != after.channel:
            joined_at = self.voice_sessions.get(session_key)
            if joined_at is not None:
                await self._record_voice_leave(member, joined_at)
            self.voice_sessions[session_key] = datetime.now(KST)
            await self._record_voice_join(member)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if not self._should_track(message.guild.id):
            return

        if isinstance(message.channel, (discord.VoiceChannel, discord.StageChannel)):
            await self.store.record(
                message.guild.id,
                message.guild.name,
                message.author.id,
                message.author.display_name,
                "voice_messages",
            )
            return

        await self.store.record(
            message.guild.id,
            message.guild.name,
            message.author.id,
            message.author.display_name,
            "messages",
        )

    @app_commands.command(name="출석조회", description="멤버의 출석 일수와 활동 통계를 조회합니다.")
    @app_commands.describe(member="조회할 멤버 (미입력 시 본인)")
    @app_commands.default_permissions(manage_guild=True)
    async def attendance(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ 서버에서만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        target = member or interaction.user
        summary = self.store.summarize_user(interaction.guild.id, target.id)

        if summary["attendance_days"] == 0:
            await interaction.response.send_message(
                f"📋 **{target.display_name}** 님의 집계 데이터가 아직 없습니다.\n"
                "봇 실행 이후 음성 입장·메시지 활동부터 기록됩니다.",
                ephemeral=True,
            )
            return

        recent_days = sorted(summary["daily_stats"].keys(), reverse=True)[:7]
        recent_lines = []
        for date_key in recent_days:
            day_stats = summary["daily_stats"][date_key]
            recent_lines.append(
                f"`{date_key}` · 입장 {day_stats.get('voice_joins', 0)}회 · "
                f"음성 {format_duration(day_stats.get('voice_seconds', 0))} · "
                f"음성채팅 {day_stats.get('voice_messages', 0)} · "
                f"메시지 {day_stats.get('messages', 0)}"
            )

        embed = discord.Embed(
            title=f"📋 {target.display_name} 활동 통계",
            color=discord.Color.green(),
        )
        embed.add_field(name="출석 일수", value=f"{summary['attendance_days']}일", inline=True)
        embed.add_field(name="음성 입장", value=f"{summary['voice_joins']}회", inline=True)
        embed.add_field(
            name="음성 시간",
            value=format_duration(summary["voice_seconds"]),
            inline=True,
        )
        embed.add_field(name="음성 채팅", value=f"{summary['voice_messages']}개", inline=True)
        embed.add_field(name="일반 메시지", value=f"{summary['messages']}개", inline=True)
        embed.add_field(name="최근 7일", value="\n".join(recent_lines), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="활동통계", description="서버 전체 활동 통계를 CSV로 내보냅니다.")
    @app_commands.default_permissions(manage_guild=True)
    async def activity_export(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ 서버에서만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        guild_stats = self.store.get_guild_stats(interaction.guild.id)
        if not guild_stats:
            await interaction.followup.send(
                "📋 아직 집계된 활동 데이터가 없습니다.",
                ephemeral=True,
            )
            return

        members = {str(member.id): member for member in interaction.guild.members}
        rows = []

        for user_id, user_data in guild_stats.items():
            summary = self.store.summarize_user(interaction.guild.id, int(user_id))
            member = members.get(user_id)
            display_name = (
                member.display_name
                if member
                else self.store.get_user_name(interaction.guild.id, int(user_id)) or user_id
            )
            rows.append(
                (
                    display_name,
                    user_id,
                    summary["attendance_days"],
                    summary["voice_joins"],
                    summary["voice_seconds"],
                    summary["voice_messages"],
                    summary["messages"],
                )
            )

        rows.sort(key=lambda row: row[0].lower())

        buffer = io.StringIO()
        buffer.write("이름,유저ID,출석일수,음성입장,음성시간(초),음성채팅,일반메시지\n")
        for row in rows:
            buffer.write(
                f"{row[0]},{row[1]},{row[2]},{row[3]},{row[4]},{row[5]},{row[6]}\n"
            )

        filename = f"activity_{interaction.guild.name}.csv"
        file = discord.File(
            io.BytesIO(buffer.getvalue().encode("utf-8-sig")),
            filename=filename,
        )

        await interaction.followup.send(
            f"✅ 총 **{len(rows)}명**의 활동 통계입니다.",
            file=file,
            ephemeral=True,
        )


async def setup_activity_tracker(bot: commands.Bot, guild_id: Optional[str] = None) -> None:
    await bot.add_cog(ActivityTracker(bot, guild_id=guild_id))
