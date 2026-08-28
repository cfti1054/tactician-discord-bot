# tactician-discord-bot

Python + discord.py Discord bot, with a REST API for member activity and attendance.

## Setup

1. Install dependencies:

```bash
pip install -r src/requirements.txt
```

2. Create local config files from examples:

```bash
cp .env.example .env
cp data/config.example.json data/config.json
cp data/activity.example.json data/activity.json
```

TFT 패치 알림 상태 파일은 봇이 `data/tft_digest.json`을 자동 생성합니다. Steam 할인 알림은 `data/steam_digest.json`을 사용합니다. Railway Volume을 쓰면 `TFT_DIGEST_FILE`, `STEAM_DIGEST_FILE` 등으로 경로를 바꿀 수 있습니다.

3. Edit `.env` and set:

- `DISCORD_TOKEN` — required (Discord Developer Portal → Bot → Token)
- `GUILD_ID` — optional (faster slash-command sync; also limits REST API access to that server)
- `API_KEY` — required for REST API (`Authorization: Bearer <API_KEY>`)
- `PORT` — REST API port (default `8000`; Railway injects this automatically)

4. In [Discord Developer Portal](https://discord.com/developers/applications) → Bot, enable:

- Message Content Intent
- Server Members Intent

5. Invite the bot (OAuth2 → URL Generator → scopes: `bot`, `applications.commands`) and run from the project root.

Bot + REST API (Railway / 외부 조회용):

```bash
python src/main.py
```

Bot only:

```bash
python src/bot.py
```

## 기본 명령

| 명령 | 설명 | 권한 |
|------|------|------|
| `/ping` | 봇 생존 확인 | 모두 |
| `/공지설정` | 공지 채널 지정 | 모두 |
| `/공지` | 모달로 공지 임베드 게시 | 모두 |
| `/멤버목록` | 멤버목록 채널에 서버 멤버·CSV 버튼 게시 | 서버 관리 |
| `/채팅삭제` | 채널 최근 메시지 삭제 (1~100개) | 메시지 관리 |
| `/출석조회` | 멤버 출석·활동 요약 | 서버 관리 |
| `/활동통계` | 서버 전체 활동 CSV | 서버 관리 |

## 팀 정하기

`/팀정하기`로 채널에 인터랙티브 UI를 띄워 팀 구성과 참가 멤버를 선택한 뒤 랜덤으로 팀을 나눕니다. **일반 서버 멤버 누구나** 사용할 수 있습니다.

| 기능 | 설명 |
|------|------|
| 팀 구성 버튼 | `2:2`, `3:3`, `4:4`, `5:5`, `2:2:2:2` |
| 직접입력 | Modal에서 `3:3:2` 등 자유 형식 입력 |
| 멤버 선택 | 서버 멤버 버튼 토글 (봇 계정 제외) |
| 팀 나누기 | 선택 인원 = 구성 합계일 때 랜덤 배정 |
| 결과 | A/B/…팀 Embed, **다시 섞기**·**멤버 수정** |

멤버가 많으면 페이지(14명/페이지)로 넘깁니다. 세션은 30분 후 만료됩니다.

## TFT 패치·소식 (AI 없음)

공식 TFT 사이트([패치 노트](https://teamfighttactics.leagueoflegends.com/ko-kr/news/tags/patch-notes/), [새 소식](https://teamfighttactics.leagueoflegends.com/ko-kr/news/))를 주기적으로 확인하고, 변경 줄을 규칙으로 상향/하향/조정으로 나눠 Discord에 올립니다. OpenAI 등 유료 API는 사용하지 않습니다.

| 명령 | 설명 |
|------|------|
| `/tft알림설정` | 자동 알림 채널 지정 (서버 관리 권한) |
| `/tft패치` | 최신 공식 패치 요약 |
| `/tft소식` | 공식 새 소식 최근 5건 |

알림 채널을 처음 설정하면 현재 최신 패치 1건을 올리고, 이후에는 새로 올라온 패치·게임 업데이트·개발자 글만 알립니다. 확인 주기는 기본 30분(`TFT_POLL_MINUTES`)입니다.

## Steam 할인 알림 (AI 없음)

Steam 스토어([특가 목록](https://store.steampowered.com/search/?specials=1))에서 할인 게임을 주기적으로 확인하고 Discord에 알립니다. **한국 스토어(`kr`)** 가격 기준이며, API 키는 필요 없습니다.

| 명령 | 설명 |
|------|------|
| `/스팀알림설정` | 알림 채널 + 최소 할인율 설정 (서버 관리 권한) |
| `/스팀할인` | 할인 게임 목록 조회 |

처음 채널을 설정하면 현재 할인 목록을 보여 주고, 이후에는 **새로 감지된 할인**만 알립니다. 겨울·여름·설 등 **대형 시즌 세일**이 시작되면 별도 공지를 한 번 올리고, 세일 기간 중에는 개별 할인 알림을 잠시 쉽니다. 확인 주기는 기본 60분(`STEAM_POLL_MINUTES`)입니다.

## REST API

Base URL 예: `http://localhost:8000` 또는 Railway Public URL.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | 없음 | 서버·봇 상태 |
| `GET` | `/api/v1/guilds/{guild_id}/attendance-report` | Bearer | 기간별 전체 멤버 출결 (일별 포함) |
| `GET` | `/api/v1/guilds/{guild_id}/members/summary` | Bearer | 기간별 전체 멤버 요약 |
| `GET` | `/api/v1/guilds/{guild_id}/members/{user_id}` | Bearer | 특정 멤버 기간 상세 |

Query: `from`, `to` (`YYYY-MM-DD`, KST), optional `min_voice_seconds` (해당 초 이상이면 `qualified`).

```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
  "http://localhost:8000/api/v1/guilds/GUILD_ID/attendance-report?from=2026-08-11&to=2026-08-17&min_voice_seconds=1800"
```

OpenAPI docs: `http://localhost:8000/docs`

포인트 계산·지급은 이 API 밖에서 수행합니다. `qualified_days`를 출석 일수로 사용하면 됩니다.
