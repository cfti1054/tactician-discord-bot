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
