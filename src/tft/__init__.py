from __future__ import annotations

from typing import Optional

from discord.ext import commands

from tft.cog import TftDigest


async def setup_tft_digest(bot: commands.Bot, guild_id: Optional[str] = None) -> None:
    await bot.add_cog(TftDigest(bot, guild_id=guild_id))
