import io
import json
import os
from typing import List, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from activity_tracker import setup_activity_tracker
from steam import setup_steam_deals
from team import setup_team_formation
from tft import setup_tft_digest

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SRC_DIR)

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN 환경 변수가 설정되지 않았습니다. .env 파일을 확인해 주세요.")

GUILD_ID = os.getenv("GUILD_ID")

CONFIG_FILE = os.path.join(PROJECT_ROOT, "data", "config.json")

NOTICE_CHANNEL_ID = None
NOTICE_CHANNEL_NAME = None
MEMBER_LIST_CHANNEL_ID = None
MEMBER_LIST_CHANNEL_NAME = "멤버목록"


def load_config():
    global NOTICE_CHANNEL_ID, NOTICE_CHANNEL_NAME, MEMBER_LIST_CHANNEL_ID

    if not os.path.exists(CONFIG_FILE):
        return

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    NOTICE_CHANNEL_ID = config.get("notice_channel")
    NOTICE_CHANNEL_NAME = config.get("notice_channel_name")
    MEMBER_LIST_CHANNEL_ID = config.get("member_list_channel")

def save_config():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "notice_channel": NOTICE_CHANNEL_ID,
                "notice_channel_name": NOTICE_CHANNEL_NAME,
                "member_list_channel": MEMBER_LIST_CHANNEL_ID,
            },
            f,
            indent=4,
            ensure_ascii=False
        )


def build_member_rows(members: List[discord.Member]) -> Tuple[List[tuple], List[str]]:
    rows = []
    lines = []
    for member in members:
        joined_at = (
            member.joined_at.strftime("%Y-%m-%d %H:%M")
            if member.joined_at
            else "알 수 없음"
        )
        created_at = member.created_at.strftime("%Y-%m-%d %H:%M")
        rows.append((member.display_name, member.name, member.id, joined_at, created_at))
        lines.append(
            f"• **{member.display_name}** (`{member.name}`) · "
            f"ID `{member.id}` · 가입 {joined_at}"
        )
    return rows, lines


def build_member_csv(rows: List[tuple]) -> bytes:
    buffer = io.StringIO()
    buffer.write("이름,유저명,유저ID,서버가입일,계정생성일\n")
    for row in rows:
        buffer.write(f"{row[0]},{row[1]},{row[2]},{row[3]},{row[4]}\n")
    return buffer.getvalue().encode("utf-8-sig")


def chunk_lines(lines: List[str], max_length: int = 1900) -> List[str]:
    chunks = []
    current_chunk = []

    for line in lines:
        candidate = "\n".join(current_chunk + [line])
        if current_chunk and len(candidate) > max_length:
            chunks.append("\n".join(current_chunk))
            current_chunk = [line]
        else:
            current_chunk.append(line)

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return chunks


async def get_or_create_member_list_channel(
    guild: discord.Guild,
) -> Tuple[discord.TextChannel, bool]:
    global MEMBER_LIST_CHANNEL_ID

    if MEMBER_LIST_CHANNEL_ID:
        channel = guild.get_channel(MEMBER_LIST_CHANNEL_ID)
        if channel is None:
            try:
                fetched = await guild.fetch_channel(MEMBER_LIST_CHANNEL_ID)
                if isinstance(fetched, discord.TextChannel):
                    channel = fetched
            except discord.HTTPException:
                channel = None
        if isinstance(channel, discord.TextChannel):
            return channel, False

    channel = discord.utils.get(guild.text_channels, name=MEMBER_LIST_CHANNEL_NAME)
    if channel is not None:
        MEMBER_LIST_CHANNEL_ID = channel.id
        save_config()
        return channel, False

    channel = await guild.create_text_channel(
        MEMBER_LIST_CHANNEL_NAME,
        reason="멤버목록 조회용 채널"
    )
    MEMBER_LIST_CHANNEL_ID = channel.id
    save_config()
    return channel, True


class MemberListDownloadView(discord.ui.View):
    def __init__(self, csv_bytes: bytes, filename: str):
        super().__init__(timeout=3600)
        self.csv_bytes = csv_bytes
        self.filename = filename

    @discord.ui.button(label="CSV 다운로드", style=discord.ButtonStyle.primary, emoji="📥")
    async def download_csv(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        file = discord.File(io.BytesIO(self.csv_bytes), filename=self.filename)
        await interaction.response.send_message(
            "📥 CSV 파일입니다.",
            file=file,
            ephemeral=True,
        )


class NoticeModal(discord.ui.Modal, title="공지사항 작성"):
    title_input = discord.ui.TextInput(
        label="제목",
        placeholder="공지 제목을 입력하세요",
        max_length=256,
        required=True,
    )
    content_input = discord.ui.TextInput(
        label="내용",
        placeholder="공지 내용을 입력하세요",
        style=discord.TextStyle.paragraph,
        max_length=4000,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        channel = bot.get_channel(NOTICE_CHANNEL_ID)

        if channel is None:
            try:
                channel = await bot.fetch_channel(NOTICE_CHANNEL_ID)
            except Exception:
                await interaction.response.send_message(
                    "❌ 공지 채널을 찾을 수 없습니다.\n다시 /공지설정을 실행해주세요.",
                    ephemeral=True
                )
                return

        embed = discord.Embed(
            title=f"📢 {self.title_input.value}",
            description=self.content_input.value,
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"작성자 : {interaction.user.display_name}")

        await interaction.response.send_message(
            "✅ 공지를 등록했습니다.",
            ephemeral=True
        )
        await channel.send(embed=embed)


intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
)


async def setup_hook():
    await setup_activity_tracker(bot, guild_id=GUILD_ID)
    await setup_tft_digest(bot, guild_id=GUILD_ID)
    await setup_steam_deals(bot, guild_id=GUILD_ID)
    await setup_team_formation(bot, guild_id=GUILD_ID)


bot.setup_hook = setup_hook


@bot.event
async def on_ready():
    load_config()

    if GUILD_ID:
        guild = discord.Object(id=int(GUILD_ID))
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"서버 동기화 완료 : {len(synced)}개 (guild_id={GUILD_ID})")
    else:
        synced = await bot.tree.sync()
        print(f"전역 동기화 완료 : {len(synced)}개 (반영까지 최대 1시간 소요)")

    print(f"{bot.user} 로그인 완료!")

    if GUILD_ID:
        guild = bot.get_guild(int(GUILD_ID))
        if guild:
            await guild.chunk()
            print(f"멤버 캐시 로드 완료 : {guild.member_count}명")

    if NOTICE_CHANNEL_ID:
        channel_name = NOTICE_CHANNEL_NAME
        if not channel_name:
            channel = bot.get_channel(NOTICE_CHANNEL_ID)
            if channel is None:
                try:
                    channel = await bot.fetch_channel(NOTICE_CHANNEL_ID)
                except Exception:
                    channel = None
            if channel:
                channel_name = channel.name

        if channel_name:
            print(f"공지채널명 : {NOTICE_CHANNEL_ID}({channel_name})")
        else:
            print(f"공지채널명 : {NOTICE_CHANNEL_ID}")
    else:
        print("공지 채널이 아직 설정되지 않았습니다.")

    if MEMBER_LIST_CHANNEL_ID:
        print(f"멤버목록채널명 : {MEMBER_LIST_CHANNEL_ID}({MEMBER_LIST_CHANNEL_NAME})")
    else:
        print("멤버목록 채널이 아직 생성되지 않았습니다.")


@bot.tree.command(name="ping", description="봇이 살아있는지 확인합니다.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Pong!")


@bot.tree.command(name="공지설정", description="공지 채널 설정")
@app_commands.describe(channel="공지를 올릴 채널")
async def set_notice(interaction: discord.Interaction, channel: discord.TextChannel):
    global NOTICE_CHANNEL_ID, NOTICE_CHANNEL_NAME

    NOTICE_CHANNEL_ID = channel.id
    NOTICE_CHANNEL_NAME = channel.name

    save_config()

    await interaction.response.send_message(
        f"✅ 공지 채널을 {channel.mention}(으)로 설정했습니다.",
        ephemeral=True
    )


@bot.tree.command(name="공지", description="공지사항 작성")
async def notice(interaction: discord.Interaction):
    if NOTICE_CHANNEL_ID is None:
        await interaction.response.send_message(
            "❌ 먼저 /공지설정 명령으로 공지 채널을 설정해주세요.",
            ephemeral=True
        )
        return

    await interaction.response.send_modal(NoticeModal())


@bot.tree.command(name="멤버목록", description="멤버목록 채널에 서버 멤버 목록을 게시합니다.")
@app_commands.default_permissions(manage_guild=True)
async def member_list(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ 서버에서만 사용할 수 있습니다.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    try:
        list_channel, created = await get_or_create_member_list_channel(interaction.guild)
    except discord.Forbidden:
        await interaction.followup.send(
            "❌ 채널을 생성할 권한이 없습니다. 봇에게 **채널 관리** 권한을 부여해주세요.",
            ephemeral=True,
        )
        return

    members = [member async for member in interaction.guild.fetch_members(limit=None)]
    members.sort(key=lambda member: member.display_name.lower())

    rows, lines = build_member_rows(members)
    csv_bytes = build_member_csv(rows)
    filename = f"members_{interaction.guild.name}.csv"
    view = MemberListDownloadView(csv_bytes, filename)

    header_embed = discord.Embed(
        title="📋 서버 멤버 목록",
        description=f"총 **{len(members)}명**",
        color=discord.Color.green(),
    )
    header_embed.set_footer(
        text=f"조회 : {interaction.user.display_name} · "
        f"{discord.utils.format_dt(discord.utils.utcnow(), 'F')}"
    )

    await list_channel.send(embed=header_embed, view=view)

    for chunk in chunk_lines(lines):
        await list_channel.send(chunk)

    if created:
        result_message = (
            f"✅ {list_channel.mention} 채널을 새로 만들고 멤버 **{len(members)}명** 목록을 게시했습니다."
        )
    else:
        result_message = (
            f"✅ {list_channel.mention} 채널에 멤버 **{len(members)}명** 목록을 게시했습니다."
        )

    await interaction.followup.send(
        f"{result_message}\n"
        f"CSV가 필요하면 채널 메시지의 **CSV 다운로드** 버튼을 눌러주세요.",
        ephemeral=True,
    )


@bot.tree.command(name="채팅삭제", description="채널의 최근 메시지를 삭제합니다.")
@app_commands.describe(
    count="삭제할 메시지 개수 (1~100)",
    channel="삭제할 채널 (미입력 시 현재 채널)",
    pinned="고정(핀)된 메시지도 함께 삭제할지 여부",
)
async def clear_messages(
    interaction: discord.Interaction,
    count: app_commands.Range[int, 1, 100],
    channel: Optional[discord.TextChannel] = None,
    pinned: bool = False,
):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ 서버에서만 사용할 수 있습니다.",
            ephemeral=True,
        )
        return

    target_channel = channel or interaction.channel
    if not isinstance(target_channel, discord.TextChannel):
        await interaction.response.send_message(
            "❌ 텍스트 채널에서만 사용할 수 있습니다.",
            ephemeral=True,
        )
        return

    me = interaction.guild.me
    if me is None:
        await interaction.response.send_message(
            "❌ 봇 정보를 확인할 수 없습니다.",
            ephemeral=True,
        )
        return

    permissions = target_channel.permissions_for(me)
    if not permissions.manage_messages:
        await interaction.response.send_message(
            f"❌ {target_channel.mention}에서 **메시지 관리** 권한이 없습니다.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    def should_delete(message: discord.Message) -> bool:
        if message.pinned and not pinned:
            return False
        return True

    try:
        deleted = await target_channel.purge(
            limit=count,
            check=should_delete,
            reason=f"채팅삭제 명령 ({interaction.user})",
        )
    except discord.Forbidden:
        await interaction.followup.send(
            f"❌ {target_channel.mention}의 메시지를 삭제할 권한이 없습니다.",
            ephemeral=True,
        )
        return
    except discord.HTTPException as exc:
        if getattr(exc, "code", None) == 50034:
            await interaction.followup.send(
                "❌ Discord는 **14일이 지난 메시지**를 한 번에 삭제할 수 없습니다.\n"
                "최근 14일 이내 메시지만 삭제 가능합니다.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            f"❌ 메시지 삭제 중 오류가 발생했습니다.\n`{exc}`",
            ephemeral=True,
        )
        return

    result = (
        f"✅ {target_channel.mention}에서 **{len(deleted)}개** 메시지를 삭제했습니다."
    )
    if not pinned:
        result += "\n📌 고정 메시지는 기본적으로 삭제하지 않습니다."

    await interaction.followup.send(result, ephemeral=True)


if __name__ == "__main__":
    bot.run(TOKEN)
