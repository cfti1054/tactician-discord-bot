from __future__ import annotations

from typing import Optional

from discord.ext import commands

from team.cog import TeamFormation


async def setup_team_formation(bot: commands.Bot, guild_id: Optional[str] = None) -> None:
    await bot.add_cog(TeamFormation(bot, guild_id=guild_id))
