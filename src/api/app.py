from __future__ import annotations

import os

from discord.ext import commands
from fastapi import FastAPI

from api.routes import attendance
from api.schemas import HealthResponse


def create_app(bot: commands.Bot) -> FastAPI:
    app = FastAPI(
        title="Tactician Bot API",
        description="Discord 멤버 활동·출결 조회 API.",
        version="1.0.0",
    )
    app.state.bot = bot
    app.include_router(attendance.router, prefix="/api/v1")

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            guild_id=os.getenv("GUILD_ID") or None,
            bot_ready=bot.is_ready(),
        )

    return app
