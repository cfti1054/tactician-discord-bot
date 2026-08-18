from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Request

from activity_tracker import ActivityStore, ActivityTracker


def get_store(request: Request) -> ActivityStore:
    bot = getattr(request.app.state, "bot", None)
    if bot is None:
        raise HTTPException(
            status_code=503,
            detail="봇이 아직 초기화되지 않았습니다.",
        )

    cog: Optional[ActivityTracker] = bot.get_cog("ActivityTracker")
    if cog is None:
        raise HTTPException(
            status_code=503,
            detail="활동 집계 모듈이 아직 로드되지 않았습니다.",
        )
    return cog.store
