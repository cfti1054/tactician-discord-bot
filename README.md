# tactician-discord-bot

Python + discord.py Discord bot.

## Setup

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Create local env from the example (already present as `.env`):

```bash
cp .env.example .env
```

3. Edit `.env` and set:

- `DISCORD_TOKEN` — required (Discord Developer Portal → Bot → Token)
- `GUILD_ID` — optional (faster slash-command sync for one server)

4. In [Discord Developer Portal](https://discord.com/developers/applications) → Bot, enable:

- Message Content Intent
- Server Members Intent

5. Invite the bot (OAuth2 → URL Generator → scopes: `bot`, `applications.commands`) and run:

```bash
python bot.py
```
