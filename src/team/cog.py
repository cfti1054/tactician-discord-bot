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

VIEW_TIMEOUT = 1800.0
MEMBER_PICKER_COLS = 3
MEMBER_PICKER_ROWS = 4
MEMBERS_PER_PICKER_PAGE = MEMBER_PICKER_COLS * MEMBER_PICKER_ROWS
MAX_MEMBER_BUTTON_LABEL = 7
BUTTON_LABEL_PADDING = "\u2002"

TEAM_EMOJIS = ("🔵", "🔴", "🟢", "🟡", "🟣", "🟠", "⚪", "🟤")


def member_button_label(display_name: str) -> str:
    label = (
        display_name
        if len(display_name) <= MAX_MEMBER_BUTTON_LABEL
        else display_name[: MAX_MEMBER_BUTTON_LABEL - 1] + "…"
    )
    padding = MAX_MEMBER_BUTTON_LABEL - len(label)
    left = padding // 2
    right = padding - left
    return BUTTON_LABEL_PADDING * left + label + BUTTON_LABEL_PADDING * right


def section_separator() -> discord.ui.Separator:
    return discord.ui.Separator(
        visible=True,
        spacing=discord.SeparatorSpacing.small,
    )


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


async def fetch_human_members(guild: discord.Guild) -> List[discord.Member]:
    if guild.chunked:
        members = [member for member in guild.members if not member.bot]
    else:
        members = [
            member
            async for member in guild.fetch_members(limit=None)
            if not member.bot
        ]
    members.sort(key=lambda member: member.display_name.casefold())
    return members


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
        self.parent_view.set_format(sizes, label=self.format_input.value.strip())
        self.parent_view.rebuild_items()
        await interaction.response.edit_message(view=self.parent_view)


class MemberSearchModal(discord.ui.Modal, title="멤버 검색"):
    search_input = discord.ui.TextInput(
        label="닉네임 또는 사용자명",
        placeholder="검색할 이름을 입력하세요",
        max_length=100,
        required=True,
    )

    def __init__(self, picker_view: MemberPickerView) -> None:
        super().__init__()
        self.picker_view = picker_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.picker_view.set_query(self.search_input.value)
        self.picker_view.rebuild_items()
        await interaction.response.edit_message(view=self.picker_view)


class MemberPickerView(discord.ui.LayoutView):
    def __init__(
        self,
        *,
        parent_view: TeamFormationView,
        members: List[discord.Member],
        owner_id: int,
        source_message: discord.Message,
    ) -> None:
        super().__init__(timeout=VIEW_TIMEOUT)
        self.parent_view = parent_view
        self.members = members
        self.owner_id = owner_id
        self.source_message = source_message
        self.selected_ids = set(parent_view.selected_ids)
        self.query = ""
        self._filtered_members = members
        self.page = 0
        self.rebuild_items()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "❌ 이 멤버 선택 화면을 연 사용자만 조작할 수 있습니다.",
            ephemeral=True,
        )
        return False

    @property
    def filtered_members(self) -> List[discord.Member]:
        return self._filtered_members

    def set_query(self, query: str) -> None:
        self.query = query.strip()
        query = self.query.casefold()
        if not query:
            self._filtered_members = self.members
        else:
            self._filtered_members = [
                member
                for member in self.members
                if query in member.display_name.casefold()
                or query in member.name.casefold()
                or (
                    member.global_name is not None
                    and query in member.global_name.casefold()
                )
            ]
        self.page = 0

    @property
    def total_pages(self) -> int:
        return max(
            1,
            (len(self.filtered_members) + MEMBERS_PER_PICKER_PAGE - 1)
            // MEMBERS_PER_PICKER_PAGE,
        )

    def page_members(self) -> List[discord.Member]:
        start = self.page * MEMBERS_PER_PICKER_PAGE
        return self.filtered_members[start : start + MEMBERS_PER_PICKER_PAGE]

    def _header_text(self) -> str:
        visible_count = len(self.filtered_members)
        query_text = f"`{self.query}`" if self.query else "전체 멤버"
        return (
            "## 👥 멤버 선택\n"
            "멤버 버튼을 눌러 선택하거나 해제하세요.\n"
            f"검색: **{query_text}** · 결과 **{visible_count}명** · "
            f"선택 **{len(self.selected_ids)}명** · "
            f"페이지 **{self.page + 1}/{self.total_pages}**"
        )

    def _selected_text(self) -> str:
        selected_members = [
            member for member in self.members if member.id in self.selected_ids
        ]
        selected_text = "  ".join(member.mention for member in selected_members)
        if len(selected_text) > 900:
            selected_text = selected_text[:896] + "…"
        return f"**✅ 선택됨**\n{selected_text}"

    def rebuild_items(self) -> None:
        self.clear_items()
        self.page = min(self.page, self.total_pages - 1)

        self.add_item(discord.ui.TextDisplay(content=self._header_text()))
        if self.selected_ids:
            self.add_item(discord.ui.TextDisplay(content=self._selected_text()))

        page = self.page_members()
        for row_index in range(MEMBER_PICKER_ROWS):
            row_members = page[
                row_index * MEMBER_PICKER_COLS : (row_index + 1) * MEMBER_PICKER_COLS
            ]
            if not row_members:
                continue
            row = discord.ui.ActionRow()
            for member in row_members:
                selected = member.id in self.selected_ids
                button = discord.ui.Button(
                    label=member_button_label(member.display_name),
                    style=(
                        discord.ButtonStyle.success
                        if selected
                        else discord.ButtonStyle.secondary
                    ),
                    custom_id=f"team_picker_member_{member.id}",
                )
                button.callback = self._make_member_callback(member.id)
                row.add_item(button)
            self.add_item(row)

        if not page:
            self.add_item(
                discord.ui.TextDisplay(
                    content=(
                        "**검색 결과 없음**\n"
                        "다른 이름으로 검색하거나 **검색 해제**를 눌러주세요."
                    )
                )
            )

        self.add_item(section_separator())

        control_row = discord.ui.ActionRow()
        previous = discord.ui.Button(
            label="이전",
            emoji="◀",
            style=discord.ButtonStyle.secondary,
            custom_id="team_picker_previous",
            disabled=self.page <= 0,
        )
        previous.callback = self._previous_callback
        control_row.add_item(previous)

        following = discord.ui.Button(
            label="다음",
            emoji="▶",
            style=discord.ButtonStyle.secondary,
            custom_id="team_picker_next",
            disabled=self.page >= self.total_pages - 1,
        )
        following.callback = self._next_callback
        control_row.add_item(following)

        search = discord.ui.Button(
            label="검색",
            emoji="🔍",
            style=discord.ButtonStyle.primary,
            custom_id="team_picker_search",
        )
        search.callback = self._search_callback
        control_row.add_item(search)

        clear_search = discord.ui.Button(
            label="검색 해제",
            style=discord.ButtonStyle.secondary,
            custom_id="team_picker_clear_search",
            disabled=not self.query,
        )
        clear_search.callback = self._clear_search_callback
        control_row.add_item(clear_search)

        submit = discord.ui.Button(
            label="선택 완료",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id="team_picker_submit",
        )
        submit.callback = self._submit_callback
        control_row.add_item(submit)
        self.add_item(control_row)

        self.add_item(
            discord.ui.TextDisplay(content="-# 봇 계정은 목록에서 제외됩니다.")
        )

    def _make_member_callback(self, member_id: int):
        async def callback(interaction: discord.Interaction) -> None:
            if member_id in self.selected_ids:
                self.selected_ids.remove(member_id)
            else:
                self.selected_ids.add(member_id)
            self.rebuild_items()
            await interaction.response.edit_message(view=self)

        return callback

    async def _previous_callback(self, interaction: discord.Interaction) -> None:
        if self.page > 0:
            self.page -= 1
        self.rebuild_items()
        await interaction.response.edit_message(view=self)

    async def _next_callback(self, interaction: discord.Interaction) -> None:
        if self.page < self.total_pages - 1:
            self.page += 1
        self.rebuild_items()
        await interaction.response.edit_message(view=self)

    async def _search_callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(MemberSearchModal(self))

    async def _clear_search_callback(self, interaction: discord.Interaction) -> None:
        self.set_query("")
        self.rebuild_items()
        await interaction.response.edit_message(view=self)

    async def _submit_callback(self, interaction: discord.Interaction) -> None:
        valid_ids = {member.id for member in self.members}
        self.selected_ids &= valid_ids
        self.parent_view.selected_ids = set(self.selected_ids)
        self.parent_view.rebuild_items()
        done_view = discord.ui.LayoutView(timeout=None)
        done_view.add_item(
            discord.ui.TextDisplay(
                content=(
                    "## ✅ 멤버 선택 완료\n"
                    f"총 **{len(self.selected_ids)}명**을 선택했습니다."
                )
            )
        )
        await interaction.response.edit_message(view=done_view)
        try:
            await self.source_message.edit(view=self.parent_view)
        except discord.HTTPException as exc:
            await interaction.followup.send(
                f"❌ 팀 정하기 화면을 갱신하지 못했습니다.\n`{exc}`",
                ephemeral=True,
            )


class TeamFormationView(discord.ui.LayoutView):
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
        self.member_cache: Optional[List[discord.Member]] = None
        self.rebuild_items()

    def set_format(self, sizes: List[int], *, label: str) -> None:
        self.team_sizes = sizes
        self.format_label = label

    @property
    def required_count(self) -> int:
        if not self.team_sizes:
            return 0
        return sum(self.team_sizes)

    def _format_section_text(self) -> str:
        if self.format_label and self.team_sizes:
            format_text = f"**{self.format_label}** · 총 **{self.required_count}명** 필요"
        else:
            format_text = "아직 선택되지 않음"
        return (
            "### 1️⃣ 팀 구성\n"
            f"{format_text}\n"
            "`2:2` `3:3` 등 버튼 또는 **직접입력**"
        )

    def _member_section_text(self) -> str:
        selected_count = len(self.selected_ids)
        if self.team_sizes and selected_count == self.required_count:
            count_text = f"**{selected_count}명** · ✅ 팀 나누기 가능"
        elif self.team_sizes:
            remaining = self.required_count - selected_count
            count_text = f"**{selected_count}명** · ⚠️ **{remaining}명** 더 선택"
        else:
            count_text = f"**{selected_count}명**"
        return (
            "### 2️⃣ 멤버 선택\n"
            f"{count_text}\n"
            "**👥 멤버 선택**에서 참가자를 고르거나 "
            "**🔍 검색**으로 이름을 찾으세요. **봇은 제외됩니다.**"
        )

    def _selected_members_text(self) -> str:
        mentions = []
        for member_id in sorted(self.selected_ids):
            member = self.guild.get_member(member_id)
            mentions.append(member.mention if member else f"<@{member_id}>")
        selected_text = " ".join(mentions)
        if len(selected_text) > 900:
            selected_text = selected_text[:896] + "…"
        return f"**선택된 멤버**\n{selected_text}"

    def _action_section_text(self) -> str:
        return (
            "### 3️⃣ 실행\n"
            "인원이 맞으면 **🎲 팀 나누기** 버튼을 누르세요."
        )

    def rebuild_items(self) -> None:
        self.clear_items()

        self.add_item(
            discord.ui.Section(
                "## 🎮 팀 정하기",
                f"주최: **{self.host.display_name}**",
                accessory=discord.ui.Thumbnail(self.host.display_avatar.url),
            )
        )
        self.add_item(discord.ui.TextDisplay(content=self._format_section_text()))

        preset_row = discord.ui.ActionRow()
        for index, (label, sizes) in enumerate(FORMAT_PRESETS):
            selected = self.team_sizes == sizes and self.format_label == label
            button = discord.ui.Button(
                label=label,
                style=(
                    discord.ButtonStyle.primary
                    if selected
                    else discord.ButtonStyle.secondary
                ),
                custom_id=f"team_preset_{index}",
            )
            button.callback = self._make_preset_callback(label, sizes)
            preset_row.add_item(button)
        self.add_item(preset_row)

        custom_selected = False
        if self.team_sizes and self.format_label:
            for preset_label, preset_sizes in FORMAT_PRESETS:
                if self.format_label == preset_label and self.team_sizes == preset_sizes:
                    break
            else:
                custom_selected = True
        custom_row = discord.ui.ActionRow()
        custom_button = discord.ui.Button(
            label="직접입력",
            emoji="✏️",
            style=(
                discord.ButtonStyle.primary
                if custom_selected
                else discord.ButtonStyle.secondary
            ),
            custom_id="team_custom_format",
        )
        custom_button.callback = self._custom_format_callback
        custom_row.add_item(custom_button)
        self.add_item(custom_row)

        self.add_item(section_separator())

        self.add_item(discord.ui.TextDisplay(content=self._member_section_text()))
        member_row = discord.ui.ActionRow()
        member_picker_button = discord.ui.Button(
            label="멤버 선택",
            emoji="👥",
            style=discord.ButtonStyle.primary,
            custom_id="team_open_member_picker",
        )
        member_picker_button.callback = self._member_picker_callback
        member_row.add_item(member_picker_button)
        self.add_item(member_row)

        if self.selected_ids:
            self.add_item(
                discord.ui.TextDisplay(content=self._selected_members_text())
            )

        self.add_item(section_separator())

        self.add_item(discord.ui.TextDisplay(content=self._action_section_text()))
        action_row = discord.ui.ActionRow()
        split_button = discord.ui.Button(
            label="팀 나누기",
            emoji="🎲",
            style=discord.ButtonStyle.primary,
            custom_id="team_split",
        )
        split_button.callback = self._split_callback
        action_row.add_item(split_button)

        clear_button = discord.ui.Button(
            label="선택 해제",
            style=discord.ButtonStyle.secondary,
            custom_id="team_clear_members",
        )
        clear_button.callback = self._clear_members_callback
        action_row.add_item(clear_button)

        reset_button = discord.ui.Button(
            label="초기화",
            emoji="🔄",
            style=discord.ButtonStyle.danger,
            custom_id="team_reset",
        )
        reset_button.callback = self._reset_callback
        action_row.add_item(reset_button)
        self.add_item(action_row)

        self.add_item(
            discord.ui.TextDisplay(
                content=f"-# {int(VIEW_TIMEOUT // 60)}분 후 만료"
            )
        )

    def _make_preset_callback(self, label: str, sizes: List[int]):
        async def callback(interaction: discord.Interaction) -> None:
            self.set_format(sizes, label=label)
            self.rebuild_items()
            await interaction.response.edit_message(view=self)

        return callback

    async def _custom_format_callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(CustomFormatModal(self))

    async def _member_picker_callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.message is None:
            await interaction.response.send_message(
                "❌ 서버의 팀 정하기 메시지에서만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            if self.member_cache is None:
                self.member_cache = await fetch_human_members(interaction.guild)
            members = self.member_cache
        except discord.HTTPException as exc:
            await interaction.followup.send(
                f"❌ 서버 멤버 목록을 불러오지 못했습니다.\n`{exc}`",
                ephemeral=True,
            )
            return

        if not members:
            await interaction.followup.send(
                "❌ 선택 가능한 일반 멤버가 없습니다.",
                ephemeral=True,
            )
            return

        picker = MemberPickerView(
            parent_view=self,
            members=members,
            owner_id=interaction.user.id,
            source_message=interaction.message,
        )
        await interaction.followup.send(view=picker, ephemeral=True)

    async def _clear_members_callback(self, interaction: discord.Interaction) -> None:
        self.selected_ids.clear()
        self.rebuild_items()
        await interaction.response.edit_message(view=self)

    async def _reset_callback(self, interaction: discord.Interaction) -> None:
        self.selected_ids.clear()
        self.team_sizes = None
        self.format_label = None
        self.rebuild_items()
        await interaction.response.edit_message(view=self)

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
            member_cache=self.member_cache,
        )
        await interaction.response.edit_message(view=result_view)


class TeamResultView(discord.ui.LayoutView):
    def __init__(
        self,
        *,
        guild: discord.Guild,
        host: discord.Member,
        team_sizes: List[int],
        format_label: str,
        selected_ids: Set[int],
        teams: List[List[int]],
        member_cache: Optional[List[discord.Member]],
    ) -> None:
        super().__init__(timeout=VIEW_TIMEOUT)
        self.guild = guild
        self.host = host
        self.team_sizes = team_sizes
        self.format_label = format_label
        self.selected_ids = selected_ids
        self.teams = teams
        self.member_cache = member_cache
        self.rebuild_items()

    def _result_text(self) -> str:
        sections = [
            "## 🎲 팀 배정 결과",
            f"**{self.format_label}** · {sum(self.team_sizes)}명",
            f"주최: **{self.host.display_name}**",
        ]
        for index, team in enumerate(self.teams):
            emoji = TEAM_EMOJIS[index % len(TEAM_EMOJIS)]
            team_label = chr(ord("A") + index)
            lines = []
            for member_id in team:
                member = self.guild.get_member(member_id)
                lines.append(f"• {member.mention if member else f'<@{member_id}>'}")
            sections.append(
                f"### {emoji} {team_label}팀\n"
                + ("\n".join(lines) if lines else "—")
            )
        return "\n\n".join(sections)

    def rebuild_items(self) -> None:
        self.clear_items()
        self.add_item(discord.ui.TextDisplay(content=self._result_text()))
        self.add_item(section_separator())

        action_row = discord.ui.ActionRow()
        reshuffle_button = discord.ui.Button(
            label="다시 섞기",
            emoji="🔀",
            style=discord.ButtonStyle.secondary,
            custom_id="team_result_reshuffle",
        )
        reshuffle_button.callback = self._reshuffle_callback
        action_row.add_item(reshuffle_button)

        edit_button = discord.ui.Button(
            label="멤버 수정",
            emoji="✏️",
            style=discord.ButtonStyle.primary,
            custom_id="team_result_edit_members",
        )
        edit_button.callback = self._edit_members_callback
        action_row.add_item(edit_button)
        self.add_item(action_row)
        self.add_item(
            discord.ui.TextDisplay(
                content=f"-# {int(VIEW_TIMEOUT // 60)}분 후 만료"
            )
        )

    async def _reshuffle_callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        self.teams = split_teams(list(self.selected_ids), self.team_sizes)
        self.rebuild_items()
        await interaction.response.edit_message(view=self)

    async def _edit_members_callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        formation_view = TeamFormationView(
            guild=self.guild,
            host=self.host,
        )
        formation_view.selected_ids = set(self.selected_ids)
        formation_view.team_sizes = list(self.team_sizes)
        formation_view.format_label = self.format_label
        formation_view.member_cache = self.member_cache
        formation_view.rebuild_items()
        await interaction.response.edit_message(view=formation_view)


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
            await interaction.followup.send(view=view)
        except discord.HTTPException as exc:
            await interaction.followup.send(
                f"❌ 팀 정하기 UI를 표시하지 못했습니다.\n`{exc}`",
                ephemeral=True,
            )
