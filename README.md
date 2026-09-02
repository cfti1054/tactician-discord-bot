# tactician-discord-bot

Python + discord.py Discord bot, with a REST API for member activity and attendance.

## Setup

1. Install dependencies (discord.py **2.7+** required — 모달 역할 선택·팀 멤버 Select 등):

```bash
pip install -r src/requirements.txt
```

2. Create local config files from examples:

```bash
cp .env.example .env
cp data/config.example.json data/config.json
cp data/activity.example.json data/activity.json
```

TFT·Steam 알림 상태 파일(`tft_digest.json`, `steam_digest.json`)은 봇이 자동 생성합니다.

3. Edit `.env` and set:

- `DISCORD_TOKEN` — required (Discord Developer Portal → Bot → Token)
- `GUILD_ID` — optional (faster slash-command sync; also limits REST API access to that server)
- `API_KEY` — required for REST API (`Authorization: Bearer <API_KEY>`)
- `PORT` — REST API port (default `8000`; Railway injects this automatically)
- `CONFIG_FILE` — optional (공지·멤버목록·명령 역할 설정 JSON 경로)
- `ACTIVITY_FILE`, `TFT_DIGEST_FILE`, `STEAM_DIGEST_FILE` — optional (데이터 파일 경로)

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

### Railway Volume (재배포 후 설정 유지)

컨테이너 디스크는 휘발성입니다. Volume을 `/data`에 마운트한 뒤 Variables에 아래를 설정하세요.

```env
CONFIG_FILE=/data/config.json
ACTIVITY_FILE=/data/activity.json
TFT_DIGEST_FILE=/data/tft_digest.json
STEAM_DIGEST_FILE=/data/steam_digest.json
```

Volume 연결 후 **한 번 재배포**하고, TFT·Steam 알림 채널은 Discord에서 다시 설정해야 합니다.

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
| `/명령설정` | 슬래시 명령별 사용 가능 역할 지정 | 서버 관리 |

## 명령 역할 설정

`/명령설정`으로 슬래시 명령마다 **사용 가능한 Discord 역할**을 지정합니다. 팝업(Modal)에서 설정합니다.

| 기능 | 설명 |
|------|------|
| 명령 선택 | `/ping`, `/팀정하기`, `/tft패치` 등 **여러 명령 동시 선택** |
| 역할 선택 | **여러 역할 동시 선택** (지정된 역할 중 하나만 있어도 사용 가능) |
| 역할 추가 | 기존 역할에 새 역할을 **누적** |
| 다시 설정 | 선택한 역할 목록으로 **교체** |
| 제한 해제 | 역할을 비우고 저장하면 **모든 멤버** 사용 가능 |

- `/명령설정` 자체는 서버 관리자만 사용할 수 있으며, 역할 제한 대상이 아닙니다.
- 서버 관리자(`manage_guild`)는 역할 제한과 관계없이 모든 명령을 사용할 수 있습니다.
- 설정은 `config.json`의 `command_roles`에 저장됩니다.

## 팀 정하기

`/팀정하기`로 채널에 인터랙티브 UI를 띄워 팀 구성과 참가 멤버를 선택한 뒤 랜덤으로 팀을 나눕니다. **일반 서버 멤버 누구나** 사용할 수 있습니다.

Embed와 버튼 row로 **3구역**이 구분됩니다.

| 구역 | UI |
|------|-----|
| 1️⃣ 팀 구성 | `2:2`, `3:3`, `4:4`, `5:5`, `2:2:2:2` 버튼 + **직접입력** Modal |
| 2️⃣ 멤버 선택 | UserSelect에서 서버 멤버 검색·선택 (최대 25명) |
| 3️⃣ 실행 | 🎲 팀 나누기 · 선택 해제 · 🔄 초기화 |

| 기능 | 설명 |
|------|------|
| 직접입력 | Modal에서 `3:3:2` 등 자유 형식 입력 |
| 멤버 선택 | 페이지 이동 없이 검색·스크롤, 봇 선택 시 자동 제외 |
| 팀 나누기 | 선택 인원 = 구성 합계일 때 랜덤 배정 |
| 결과 | A/B/…팀 Embed, **다시 섞기**·**멤버 수정** |

세션은 30분 후 만료됩니다.

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
