from __future__ import annotations

import os
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, Path
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer_scheme = HTTPBearer(
    scheme_name="APIKey",
    description="`.env`의 API_KEY 값을 입력하세요. (Bearer 접두사는 Swagger가 자동 추가)",
    auto_error=False,
)


async def verify_api_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> None:
    expected = os.getenv("API_KEY", "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="API_KEY 환경 변수가 설정되지 않았습니다.",
        )

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Authorization: Bearer <API_KEY> 헤더가 필요합니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials.strip()
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=401,
            detail="유효하지 않은 API 키입니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def verify_guild_access(
    guild_id: str = Path(..., description="Discord 서버 ID"),
) -> str:
    if not guild_id.isdigit():
        raise HTTPException(status_code=400, detail="guild_id는 숫자여야 합니다.")

    allowed = os.getenv("GUILD_ID", "").strip()
    if allowed and allowed != guild_id:
        raise HTTPException(
            status_code=403,
            detail="이 서버의 데이터에 접근할 수 없습니다.",
        )
    return guild_id
