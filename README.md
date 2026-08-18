# tactician-discord-bot

Python + discord.py Discord bot.

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
- `GUILD_ID` — optional (faster slash-command sync for one server)

4. In [Discord Developer Portal](https://discord.com/developers/applications) → Bot, enable:

- Message Content Intent
- Server Members Intent

5. Invite the bot (OAuth2 → URL Generator → scopes: `bot`, `applications.commands`) and run from the project root:

```bash
python src/bot.py
```
