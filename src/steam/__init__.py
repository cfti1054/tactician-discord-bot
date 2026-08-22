from __future__ import annotations

from typing import Optional

from discord.ext import commands

from steam.cog import SteamDeals


async def setup_steam_deals(bot: commands.Bot, guild_id: Optional[str] = None) -> None:
    await bot.add_cog(SteamDeals(bot, guild_id=guild_id))
