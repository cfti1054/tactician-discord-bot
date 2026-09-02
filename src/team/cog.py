from __future__ import annotations

import random
from typing import List, Optional, Set, Tuple

import discord
from discord import app_commands
from discord.ext import commands

FORMAT_PRESETS: List[Tuple[str, List[int]]] = [
    ("2:2", [2, 2]),
    ("3:3", [3, 3]),
    ("4:4", [4, 4]),
    ("5:5", [5, 5]),
    ("2:2:2:2", [2, 2, 2, 2]),
]

FORMAT_ROW = 0
CUSTOM_ROW = 1
MEMBER_SELECT_ROW = 2
ACTION_ROW = 4
VIEW_TIMEOUT = 1800.0
MAX_MEMBER_SELECT = 25

TEAM_EMOJIS = ("🔵", "🔴", "🟢", "🟡", "🟣", "🟠", "⚪", "🟤")


def parse_team_format(text: str) -> Optional[List[int]]:
    parts = [part.strip() for part in text.strip().split(":") if part.strip()]
    if not parts:
        return None

    sizes: List[int] = []
    for part in parts:
        if not part.isdigit():
            return None
        size = int(part)
        if size < 1 or size > 50:
            return None
        sizes.append(size)
    return sizes


def split_teams(member_ids: List[int], sizes: List[int]) -> List[List[int]]:
    shuffled = member_ids.copy()
    random.shuffle(shuffled)
    teams: List[List[int]] = []
    index = 0
    for size in sizes:
        teams.append(shuffled[index : index + size])
        index += size
    return teams


class CustomFormatModal(discord.ui.Modal, title="팀 구성 직접 입력"):
    format_input = discord.ui.TextInput(
        label="팀 구성",
        placeholder="예: 3:3:2 또는 2:2:2:2",
        max_length=50,
        required=True,
    )

    def __init__(self, parent_view: TeamFormationView) -> None:
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        sizes = parse_team_format(self.format_input.value)
        if sizes is None:
            await interaction.response.send_message(
                "❌ 올바른 형식이 아닙니다. `:`로 구분된 양의 정수를 입력해주세요.\n"
                "예: `3:3:2`, `2:2:2:2`",
                ephemeral=True,
            )
            return
        if sum(sizes) > MAX_MEMBER_SELECT:
            await interaction.response.send_message(
                f"❌ UserSelect에서는 최대 **{MAX_MEMBER_SELECT}명**까지 선택할 수 있습니다.",
                ephemeral=True,
            )
            return

        self.parent_view.set_format(sizes, label=self.format_input.value.strip())
        self.parent_view.rebuild_items()
        await interaction.response.edit_message(
            embed=self.parent_view.build_embed(),
            view=self.parent_view,
        )


class MemberUserSelect(discord.ui.UserSelect):
    def __init__(self, parent_view: "TeamFormationView") -> None:
        self.parent_view = parent_view
        default_values = [
            discord.Object(id=member_id)
            for member_id in sorted(parent_view.selected_ids)
        ]

        super().__init__(
            placeholder="👥 참가 멤버를 검색해 선택하세요 (최대 25명)",
            min_values=0,
            max_values=MAX_MEMBER_SELECT,
            default_values=default_values,
            row=MEMBER_SELECT_ROW,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected_ids: Set[int] = set()
        rejected_names: List[str] = []
        for user in self.values:
            member = (
                user
                if isinstance(user, discord.Member)
                else self.parent_view.guild.get_member(user.id)
            )
            if member is None or member.bot:
                rejected_names.append(user.display_name)
                continue
            selected_ids.add(member.id)

        self.parent_view.selected_ids = selected_ids
        self.parent_view.rebuild_items()
        await interaction.response.edit_message(
            embed=self.parent_view.build_embed(),
            view=self.parent_view,
        )
        if rejected_names:
            await interaction.followup.send(
                "❌ 봇 계정은 팀원으로 선택할 수 없습니다: "
                + ", ".join(rejected_names),
                ephemeral=True,
            )


class TeamFormationView(discord.ui.View):
    def __init__(
        self,
        guild: discord.Guild,
        host: discord.Member,
    ) -> None:
        super().__init__(timeout=VIEW_TIMEOUT)
        self.guild = guild
        self.host = host
        self.selected_ids: Set[int] = set()
        self.team_sizes: Optional[List[int]] = None
        self.format_label: Optional[str] = None
        self.rebuild_items()

    def set_format(self, sizes: List[int], *, label: str) -> None:
        self.team_sizes = sizes
        self.format_label = label

    @property
    def required_count(self) -> int:
        if not self.team_sizes:
            return 0
        return sum(self.team_sizes)

    def rebuild_items(self) -> None:
        self.clear_items()

        for index, (label, sizes) in enumerate(FORMAT_PRESETS):
            selected = self.team_sizes == sizes and self.format_label == label
            button = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.primary if selected else discord.ButtonStyle.secondary,
                custom_id=f"team_preset_{index}",
                row=FORMAT_ROW,
            )
            button.callback = self._make_preset_callback(label, sizes)
            self.add_item(button)

        custom_selected = False
        if self.team_sizes and self.format_label:
            for preset_label, preset_sizes in FORMAT_PRESETS:
                if self.format_label == preset_label and self.team_sizes == preset_sizes:
                    break
            else:
                custom_selected = True
        custom_button = discord.ui.Button(
            label="직접입력",
            emoji="✏️",
            style=discord.ButtonStyle.primary if custom_selected else discord.ButtonStyle.secondary,
            custom_id="team_custom_format",
            row=CUSTOM_ROW,
        )
        custom_button.callback = self._custom_format_callback
        self.add_item(custom_button)

        self.add_item(MemberUserSelect(self))

        split_button = discord.ui.Button(
            label="팀 나누기",
            emoji="🎲",
            style=discord.ButtonStyle.primary,
            custom_id="team_split",
            row=ACTION_ROW,
        )
        split_button.callback = self._split_callback
        self.add_item(split_button)

        clear_button = discord.ui.Button(
            label="선택 해제",
            style=discord.ButtonStyle.secondary,
            custom_id="team_clear_members",
            row=ACTION_ROW,
        )
        clear_button.callback = self._clear_members_callback
        self.add_item(clear_button)

        reset_button = discord.ui.Button(
            label="초기화",
            emoji="🔄",
            style=discord.ButtonStyle.danger,
            custom_id="team_reset",
            row=ACTION_ROW,
        )
        reset_button.callback = self._reset_callback
        self.add_item(reset_button)

    def _make_preset_callback(self, label: str, sizes: List[int]):
        async def callback(interaction: discord.Interaction) -> None:
            self.set_format(sizes, label=label)
            self.rebuild_items()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

        return callback

    async def _custom_format_callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(CustomFormatModal(self))

    async def _clear_members_callback(self, interaction: discord.Interaction) -> None:
        self.selected_ids.clear()
        self.rebuild_items()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _reset_callback(self, interaction: discord.Interaction) -> None:
        self.selected_ids.clear()
        self.team_sizes = None
        self.format_label = None
        self.rebuild_items()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _split_callback(self, interaction: discord.Interaction) -> None:
        self.selected_ids = {
            member_id
            for member_id in self.selected_ids
            if (member := self.guild.get_member(member_id)) is not None
            and not member.bot
        }
        if not self.team_sizes or not self.format_label:
            await interaction.response.send_message(
                "❌ 먼저 팀 구성을 선택해주세요.",
                ephemeral=True,
            )
            return

        required = self.required_count
        selected_count = len(self.selected_ids)
        if selected_count != required:
            await interaction.response.send_message(
                f"❌ 선택 인원이 맞지 않습니다.\n"
                f"**{self.format_label}** 구성은 **{required}명**이 필요합니다. "
                f"(현재 {selected_count}명 선택)",
                ephemeral=True,
            )
            return

        teams = split_teams(list(self.selected_ids), self.team_sizes)
        result_view = TeamResultView(
            guild=self.guild,
            host=self.host,
            team_sizes=self.team_sizes,
            format_label=self.format_label,
            selected_ids=set(self.selected_ids),
            teams=teams,
        )
        await interaction.response.edit_message(
            embed=result_view.build_embed(),
            view=result_view,
        )

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🎮 팀 정하기",
            color=discord.Color.blurple(),
        )
        embed.set_author(name=f"주최: {self.host.display_name}", icon_url=self.host.display_avatar.url)

        if self.format_label and self.team_sizes:
            format_text = f"**{self.format_label}** · 총 **{self.required_count}명** 필요"
        else:
            format_text = "아직 선택되지 않음"

        selected_count = len(self.selected_ids)
        if self.team_sizes and selected_count == self.required_count:
            count_text = f"**{selected_count}명** · ✅ 팀 나누기 가능"
        elif self.team_sizes:
            remaining = self.required_count - selected_count
            count_text = f"**{selected_count}명** · ⚠️ **{remaining}명** 더 선택"
        else:
            count_text = f"**{selected_count}명**"

        embed.description = (
            "아래 구역 순서대로 설정하세요.\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        embed.add_field(
            name="1️⃣ 팀 구성",
            value=f"{format_text}\n`2:2` `3:3` 등 버튼 또는 **직접입력**",
            inline=False,
        )
        embed.add_field(
            name="2️⃣ 멤버 선택",
            value=(
                f"{count_text}\n"
                "UserSelect에서 참가자를 검색해 고르세요. "
                "**봇을 선택하면 자동으로 제외됩니다.**"
            ),
            inline=False,
        )
        embed.add_field(
            name="3️⃣ 실행",
            value="인원이 맞으면 **🎲 팀 나누기** 버튼을 누르세요.",
            inline=False,
        )

        if self.selected_ids:
            mentions = []
            for member_id in sorted(self.selected_ids):
                member = self.guild.get_member(member_id)
                mentions.append(member.mention if member else f"<@{member_id}>")
            selected_text = " ".join(mentions)
            if len(selected_text) > 1024:
                selected_text = selected_text[:1020] + "…"
            embed.add_field(name="선택된 멤버", value=selected_text, inline=False)

        embed.set_footer(
            text=(
                f"최대 {MAX_MEMBER_SELECT}명 선택 · "
                f"{int(VIEW_TIMEOUT // 60)}분 후 만료"
            )
        )
        return embed


class TeamResultView(discord.ui.View):
    def __init__(
        self,
        *,
        guild: discord.Guild,
        host: discord.Member,
        team_sizes: List[int],
        format_label: str,
        selected_ids: Set[int],
        teams: List[List[int]],
    ) -> None:
        super().__init__(timeout=VIEW_TIMEOUT)
        self.guild = guild
        self.host = host
        self.team_sizes = team_sizes
        self.format_label = format_label
        self.selected_ids = selected_ids
        self.teams = teams

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🎲 팀 배정 결과",
            description=f"**{self.format_label}** · {sum(self.team_sizes)}명",
            color=discord.Color.green(),
        )
        embed.set_author(name=f"주최: {self.host.display_name}", icon_url=self.host.display_avatar.url)

        for index, team in enumerate(self.teams):
            emoji = TEAM_EMOJIS[index % len(TEAM_EMOJIS)]
            team_label = chr(ord("A") + index)
            lines = []
            for member_id in team:
                member = self.guild.get_member(member_id)
                lines.append(f"• {member.mention if member else f'<@{member_id}>'}")
            embed.add_field(
                name=f"{emoji} {team_label}팀",
                value="\n".join(lines) if lines else "—",
                inline=True,
            )

        embed.set_footer(text=f"{int(VIEW_TIMEOUT // 60)}분 후 만료")
        return embed

    @discord.ui.button(label="다시 섞기", emoji="🔀", style=discord.ButtonStyle.secondary)
    async def reshuffle(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.teams = split_teams(list(self.selected_ids), self.team_sizes)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="멤버 수정", emoji="✏️", style=discord.ButtonStyle.primary)
    async def edit_members(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        formation_view = TeamFormationView(
            guild=self.guild,
            host=self.host,
        )
        formation_view.selected_ids = set(self.selected_ids)
        formation_view.team_sizes = list(self.team_sizes)
        formation_view.format_label = self.format_label
        formation_view.rebuild_items()
        await interaction.response.edit_message(
            embed=formation_view.build_embed(),
            view=formation_view,
        )


class TeamFormation(commands.Cog):
    def __init__(self, bot: commands.Bot, guild_id: Optional[str] = None) -> None:
        self.bot = bot
        self.guild_id = guild_id

    def _target_guild_ok(self, guild: Optional[discord.Guild]) -> bool:
        if guild is None:
            return False
        if self.guild_id is None:
            return True
        return str(guild.id) == str(self.guild_id)

    @app_commands.command(name="팀정하기", description="팀 구성과 멤버를 선택해 팀을 자동으로 나눕니다.")
    async def team_formation(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ 서버에서만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        if not self._target_guild_ok(interaction.guild):
            await interaction.response.send_message(
                "❌ 이 서버에서는 사용할 수 없습니다.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        host = interaction.user
        if not isinstance(host, discord.Member):
            await interaction.followup.send(
                "❌ 멤버 정보를 확인할 수 없습니다.",
                ephemeral=True,
            )
            return

        view = TeamFormationView(
            guild=interaction.guild,
            host=host,
        )
        try:
            await interaction.followup.send(
                embed=view.build_embed(),
                view=view,
            )
        except discord.HTTPException as exc:
            await interaction.followup.send(
                f"❌ 팀 정하기 UI를 표시하지 못했습니다.\n`{exc}`",
                ephemeral=True,
            )
