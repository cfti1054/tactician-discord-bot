from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Sequence, Set, Tuple

import discord
from discord import app_commands

MANAGEABLE_COMMANDS: List[Tuple[str, str]] = [
    ("ping", "봇 생존 확인"),
    ("공지설정", "공지 채널 지정"),
    ("공지", "공지사항 작성"),
    ("멤버목록", "서버 멤버 목록 게시"),
    ("채팅삭제", "채널 최근 메시지 삭제"),
    ("팀정하기", "팀 구성·랜덤 배정"),
    ("tft알림설정", "TFT 자동 알림 채널"),
    ("tft패치", "최신 TFT 패치 요약"),
    ("tft소식", "TFT 공식 새 소식"),
    ("스팀알림설정", "Steam 할인 알림 채널"),
    ("스팀할인", "Steam 할인 목록 조회"),
    ("출석조회", "멤버 출석·활동 요약"),
    ("활동통계", "서버 전체 활동 CSV"),
]

PROTECTED_COMMANDS = {"명령설정"}
MODAL_TIMEOUT = 300.0
VIEW_TIMEOUT = 600.0


def _read_json(filepath: str) -> dict:
    if not os.path.exists(filepath):
        return {}
    with open(filepath, "r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    return loaded if isinstance(loaded, dict) else {}


def _write_json(filepath: str, data: dict) -> None:
    directory = os.path.dirname(filepath)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=4, ensure_ascii=False)


def _known_commands() -> Set[str]:
    return {name for name, _ in MANAGEABLE_COMMANDS}


class CommandRoleStore:
    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self.command_roles: Dict[str, List[int]] = {}

    def load(self) -> None:
        data = _read_json(self.filepath)
        raw = data.get("command_roles") or {}
        if not isinstance(raw, dict):
            raw = {}

        parsed: Dict[str, List[int]] = {}
        for name, role_ids in raw.items():
            if name not in _known_commands() or not isinstance(role_ids, list):
                continue
            cleaned: List[int] = []
            seen: Set[int] = set()
            for role_id in role_ids:
                try:
                    value = int(role_id)
                except (TypeError, ValueError):
                    continue
                if value in seen:
                    continue
                seen.add(value)
                cleaned.append(value)
            if cleaned:
                parsed[str(name)] = cleaned
        self.command_roles = parsed

    def save(self) -> None:
        data = _read_json(self.filepath)
        data["command_roles"] = {
            name: role_ids for name, role_ids in sorted(self.command_roles.items())
        }
        _write_json(self.filepath, data)

    def roles_for(self, name: str) -> List[int]:
        return list(self.command_roles.get(name) or [])

    def set_roles(self, name: str, role_ids: Sequence[int]) -> bool:
        if name in PROTECTED_COMMANDS or name not in _known_commands():
            return False
        unique: List[int] = []
        seen: Set[int] = set()
        for role_id in role_ids:
            value = int(role_id)
            if value in seen:
                continue
            seen.add(value)
            unique.append(value)
        if unique:
            self.command_roles[name] = unique
        else:
            self.command_roles.pop(name, None)
        self.save()
        return True

    def add_roles(self, name: str, role_ids: Sequence[int]) -> bool:
        if name in PROTECTED_COMMANDS or name not in _known_commands():
            return False
        merged = list(dict.fromkeys(self.roles_for(name) + [int(role_id) for role_id in role_ids]))
        return self.set_roles(name, merged)

    def clear_roles(self, name: str) -> bool:
        return self.set_roles(name, [])

    def can_use(self, name: str, member: Optional[discord.abc.User]) -> bool:
        if name in PROTECTED_COMMANDS:
            return True
        if name not in _known_commands():
            return True
        allowed = self.roles_for(name)
        if not allowed:
            return True
        permissions = getattr(member, "guild_permissions", None)
        if permissions is not None and permissions.manage_guild:
            return True
        roles = getattr(member, "roles", None)
        if not roles:
            return False
        member_role_ids = {role.id for role in roles}
        return bool(member_role_ids.intersection(allowed))


def _role_mentions(role_ids: Sequence[int]) -> str:
    if not role_ids:
        return "모든 멤버"
    return ", ".join(f"<@&{role_id}>" for role_id in role_ids)


def build_role_embed(store: CommandRoleStore) -> discord.Embed:
    lines = []
    for name, description in MANAGEABLE_COMMANDS:
        allowed = store.roles_for(name)
        lines.append(f"`/{name}` — {description}\n┗ {_role_mentions(allowed)}")

    embed = discord.Embed(
        title="명령 역할 설정",
        description="\n".join(lines),
        color=discord.Color.gold(),
    )
    embed.set_footer(
        text="여러 역할이 지정되면 그중 하나만 있어도 사용할 수 있습니다. "
        "역할이 비어 있으면 모든 멤버가 사용할 수 있습니다. "
        "서버 관리자는 제한과 관계없이 사용할 수 있습니다."
    )
    return embed


class CommandRoleModal(discord.ui.Modal, title="명령 역할 설정"):
    def __init__(
        self,
        store: CommandRoleStore,
        *,
        preset_commands: Optional[Sequence[str]] = None,
        merge_roles: bool = False,
    ) -> None:
        super().__init__(timeout=MODAL_TIMEOUT)
        self.store = store
        self.merge_roles = merge_roles

        command_select = discord.ui.Select(
            placeholder="명령을 선택하세요 (여러 개 가능)",
            options=[
                discord.SelectOption(
                    label=f"/{name}",
                    description=description,
                    value=name,
                    default=preset_commands is not None and name in preset_commands,
                )
                for name, description in MANAGEABLE_COMMANDS
            ],
            min_values=1,
            max_values=len(MANAGEABLE_COMMANDS),
            required=True,
        )
        self.add_item(
            discord.ui.Label(
                text="명령",
                description="같은 역할을 적용할 슬래시 명령을 하나 이상 선택하세요.",
                component=command_select,
            )
        )
        self.command_select = command_select

        default_role_ids: List[int] = []
        if preset_commands:
            seen: Set[int] = set()
            for name in preset_commands:
                for role_id in store.roles_for(name):
                    if role_id not in seen:
                        seen.add(role_id)
                        default_role_ids.append(role_id)

        role_select = discord.ui.RoleSelect(
            placeholder="역할을 선택하세요 (여러 개 가능, 비우면 전체 허용)",
            min_values=0,
            max_values=25,
            required=False,
            default_values=default_role_ids,
        )
        self.add_item(
            discord.ui.Label(
                text="사용 가능한 역할",
                description="여러 역할을 동시에 선택할 수 있습니다. "
                "선택한 역할 중 하나라도 있으면 명령을 사용할 수 있습니다.",
                component=role_select,
            )
        )
        self.role_select = role_select

    async def on_submit(self, interaction: discord.Interaction) -> None:
        names = list(self.command_select.values or [])
        if not names:
            await interaction.response.send_message(
                "❌ 명령을 선택하지 못했습니다.",
                ephemeral=True,
            )
            return

        role_ids = [role.id for role in self.role_select.values]
        updated: List[str] = []
        for name in names:
            if not role_ids:
                if self.store.clear_roles(name):
                    updated.append(name)
                continue
            if self.merge_roles:
                ok = self.store.add_roles(name, role_ids)
            else:
                ok = self.store.set_roles(name, role_ids)
            if ok:
                updated.append(name)

        if not updated:
            await interaction.response.send_message(
                "❌ 선택한 명령에 역할을 지정하지 못했습니다.",
                ephemeral=True,
            )
            return

        command_text = ", ".join(f"`/{name}`" for name in updated)
        action = "추가했습니다" if self.merge_roles and role_ids else "설정했습니다"
        if not role_ids:
            action = "제한을 해제했습니다"
        await interaction.response.send_message(
            f"✅ {command_text} 사용 역할을 {_role_mentions(role_ids)}(으)로 {action}.",
            embed=build_role_embed(self.store),
            view=OpenSettingsView(self.store),
            ephemeral=True,
        )


class OpenSettingsView(discord.ui.View):
    def __init__(self, store: CommandRoleStore) -> None:
        super().__init__(timeout=VIEW_TIMEOUT)
        self.store = store

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ 서버에서만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return False
        permissions = getattr(interaction.user, "guild_permissions", None)
        if permissions is None or not permissions.manage_guild:
            await interaction.response.send_message(
                "❌ 서버 관리 권한이 있는 관리자만 변경할 수 있습니다.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="다시 설정", style=discord.ButtonStyle.primary)
    async def reopen(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(CommandRoleModal(self.store))

    @discord.ui.button(label="역할 추가", style=discord.ButtonStyle.secondary)
    async def add_roles(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            CommandRoleModal(self.store, merge_roles=True)
        )


def setup_command_toggles(bot: discord.Client, filepath: str) -> CommandRoleStore:
    store = CommandRoleStore(filepath)
    store.load()

    async def command_enabled_check(interaction: discord.Interaction) -> bool:
        command = interaction.command
        if command is None:
            return True
        name = command.qualified_name
        if store.can_use(name, interaction.user):
            return True
        if interaction.response.is_done():
            return False
        allowed = store.roles_for(name)
        await interaction.response.send_message(
            f"❌ `/{name}` 명령은 지정된 역할만 사용할 수 있습니다.\n"
            f"허용 역할: {_role_mentions(allowed)}",
            ephemeral=True,
        )
        return False

    bot.tree.interaction_check = command_enabled_check

    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.CheckFailure):
            return
        raise error

    @bot.tree.command(
        name="명령설정",
        description="슬래시 명령을 역할별로 사용할 수 있게 설정합니다.",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def configure_commands(interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ 서버에서만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(CommandRoleModal(store))

    return store
