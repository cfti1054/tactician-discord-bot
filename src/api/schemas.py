from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Period(BaseModel):
    from_date: str = Field(alias="from")
    to_date: str = Field(alias="to")

    model_config = {"populate_by_name": True}


class AttendanceCriteria(BaseModel):
    min_voice_seconds: int


class DailyActivity(BaseModel):
    date: str
    voice_joins: int
    voice_seconds: int
    voice_messages: int
    messages: int
    attended: bool
    qualified: bool


class MemberPeriodSummary(BaseModel):
    user_id: str
    user_name: Optional[str] = None
    attendance_days: int
    qualified_days: int
    voice_joins: int
    voice_seconds: int
    voice_messages: int
    messages: int


class MemberPeriodDetail(MemberPeriodSummary):
    daily: List[DailyActivity]


class AttendanceReport(BaseModel):
    guild_id: str
    guild_name: Optional[str] = None
    period: Period
    criteria: AttendanceCriteria
    timezone: str = "Asia/Seoul"
    members: List[MemberPeriodDetail]
    generated_at: str


class MemberSummaryReport(BaseModel):
    guild_id: str
    guild_name: Optional[str] = None
    period: Period
    criteria: AttendanceCriteria
    timezone: str = "Asia/Seoul"
    members: List[MemberPeriodSummary]
    generated_at: str


class HealthResponse(BaseModel):
    status: str
    guild_id: Optional[str] = None
    bot_ready: bool
