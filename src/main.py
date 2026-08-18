from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SRC_DIR)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

import uvicorn

from api.app import create_app
from bot import TOKEN, bot


async def main() -> None:
    app = create_app(bot)
    port = int(os.getenv("PORT", "8000"))
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = False

    print(f"REST API 시작 : http://0.0.0.0:{port}")
    try:
        await asyncio.gather(
            bot.start(TOKEN),
            server.serve(),
        )
    finally:
        if not bot.is_closed():
            await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
