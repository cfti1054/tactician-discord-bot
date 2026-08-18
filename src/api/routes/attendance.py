from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from activity_tracker import ActivityStore, KST
from api.auth import verify_api_key, verify_guild_access
from api.deps import get_store
from api.schemas import (
    AttendanceCriteria,
    AttendanceReport,
    MemberPeriodDetail,
    MemberSummaryReport,
    Period,
)

router = APIRouter(dependencies=[Depends(verify_api_key)])


def _validate_period(from_date: date, to_date: date) -> None:
    if from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="from 날짜는 to 날짜보다 이후일 수 없습니다.",
        )


def _now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _period(from_date: date, to_date: date) -> Period:
    return Period.model_validate(
        {"from": from_date.isoformat(), "to": to_date.isoformat()}
    )


@router.get(
    "/guilds/{guild_id}/attendance-report",
    response_model=AttendanceReport,
    summary="기간별 전체 멤버 출결 리포트",
)
def attendance_report(
    guild_id: str = Depends(verify_guild_access),
    from_date: date = Query(..., alias="from", description="시작일 (KST, YYYY-MM-DD)"),
    to_date: date = Query(..., alias="to", description="종료일 (KST, YYYY-MM-DD)"),
    min_voice_seconds: int = Query(
        0,
        ge=0,
        description="이 초 이상이면 해당 일을 유효 출석(qualified)으로 표시",
    ),
    store: ActivityStore = Depends(get_store),
):
    _validate_period(from_date, to_date)
    members = store.summarize_guild_period(
        int(guild_id),
        from_date.isoformat(),
        to_date.isoformat(),
        min_voice_seconds,
        include_daily=True,
        skip_empty=True,
    )
    return AttendanceReport(
        guild_id=guild_id,
        guild_name=store.get_guild_name(int(guild_id)),
        period=_period(from_date, to_date),
        criteria=AttendanceCriteria(min_voice_seconds=min_voice_seconds),
        timezone="Asia/Seoul",
        members=members,
        generated_at=_now_kst(),
    )


@router.get(
    "/guilds/{guild_id}/members/summary",
    response_model=MemberSummaryReport,
    summary="기간별 전체 멤버 출결 요약 (일별 상세 없음)",
)
def members_summary(
    guild_id: str = Depends(verify_guild_access),
    from_date: date = Query(..., alias="from", description="시작일 (KST, YYYY-MM-DD)"),
    to_date: date = Query(..., alias="to", description="종료일 (KST, YYYY-MM-DD)"),
    min_voice_seconds: int = Query(0, ge=0),
    store: ActivityStore = Depends(get_store),
):
    _validate_period(from_date, to_date)
    members = store.summarize_guild_period(
        int(guild_id),
        from_date.isoformat(),
        to_date.isoformat(),
        min_voice_seconds,
        include_daily=False,
        skip_empty=True,
    )
    return MemberSummaryReport(
        guild_id=guild_id,
        guild_name=store.get_guild_name(int(guild_id)),
        period=_period(from_date, to_date),
        criteria=AttendanceCriteria(min_voice_seconds=min_voice_seconds),
        timezone="Asia/Seoul",
        members=members,
        generated_at=_now_kst(),
    )


@router.get(
    "/guilds/{guild_id}/members/{user_id}",
    response_model=MemberPeriodDetail,
    summary="특정 멤버의 기간별 출결 상세",
)
def member_detail(
    user_id: str,
    guild_id: str = Depends(verify_guild_access),
    from_date: date = Query(..., alias="from", description="시작일 (KST, YYYY-MM-DD)"),
    to_date: date = Query(..., alias="to", description="종료일 (KST, YYYY-MM-DD)"),
    min_voice_seconds: int = Query(0, ge=0),
    store: ActivityStore = Depends(get_store),
):
    _validate_period(from_date, to_date)
    if not user_id.isdigit():
        raise HTTPException(status_code=400, detail="user_id는 숫자여야 합니다.")

    if not store.has_user(int(guild_id), int(user_id)):
        raise HTTPException(status_code=404, detail="해당 멤버의 활동 데이터가 없습니다.")

    return store.summarize_user_period(
        int(guild_id),
        int(user_id),
        from_date.isoformat(),
        to_date.isoformat(),
        min_voice_seconds,
        include_daily=True,
    )
