# iCloud Calendar MCP

Remote MCP server for Apple iCloud Calendar via CalDAV. Gives AI assistants access to your iCloud Calendar over the internet — no local server or app required.

## What it does

Exposes 7 calendar tools so AI assistants can manage your iCloud Calendar directly:

| Tool | Description |
|---|---|
| `list_calendars` | List all calendars in the iCloud account |
| `list_events` | List events in a calendar within a date range |
| `get_event` | Get a single event by UID |
| `create_event` | Create a new calendar event |
| `update_event` | Update an existing event (partial updates supported) |
| `delete_event` | Delete an event by UID |
| `search_events` | Full-text search across all calendars by title, description, or location |

> **Tip:** Always call `list_calendars` first. Calendar names are matched
> case-insensitively, and the error message lists all available names if no match is found.

### Timezone handling

Event times are stored with an explicit `TZID=<CALENDAR_TZ>` (default
`Europe/Berlin`), not as a bare UTC `Z` timestamp — so calendar apps show
*and edit* the event in that named zone instead of GMT/UTC. On the write path
(`create_event`, `update_event`), a naive datetime string (no offset, e.g.
`2026-06-17T14:15:00`) is interpreted as **local wall-clock time** in
`CALENDAR_TZ`; DST is handled automatically. A datetime with an explicit
offset is honoured, then normalized to `CALENDAR_TZ`. Pass the local time you
want to see in the calendar; do not pre-convert to UTC yourself. The read path
(`list_events`, `get_event`, `search_events`) returns times with that same
offset already applied — no further conversion needed on the caller's end.

## How it works

```
AI assistant → /authorize → GitHub login (+ 2FA) → /auth/callback
             → username verified → MCP access token issued → MCP connection
```

Access is protected by **GitHub OAuth** — only the GitHub account set in
`GITHUB_ALLOWED_USER` can authenticate. GitHub login with 2FA is required
once every 30 days; tokens are persisted to Redis. No credentials are stored
in the AI assistant's configuration.

1. The AI assistant detects the MCP server requires OAuth
2. A browser window opens — you log in to GitHub with 2FA
3. The server verifies your GitHub account matches `GITHUB_ALLOWED_USER_ID`
4. The AI assistant receives a 30-day access token and a 30-day refresh token

> **Cold start note:** If the hosting platform sleeps the container, the first
> request after wake-up takes a few seconds. OAuth tokens are persisted to
> a Redis-compatible store so the AI assistant does **not** need to re-authenticate.

## Deploy your own

You will need:

- A container hosting platform (e.g. Render, Railway, Fly.io)
- A Redis-compatible key-value store for token persistence (e.g. Upstash, Redis Cloud)
- A GitHub OAuth App for authentication
- An Apple ID with iCloud Calendar enabled and an app-specific password

### Step 1 — Apple app-specific password

iCloud requires an app-specific password — your main Apple ID password will not work.

1. Go to [appleid.apple.com](https://appleid.apple.com) → **Sign-In and Security** → **App-Specific Passwords**
2. Click **+** and label it (e.g. `icloud-calendar-mcp`)
3. Copy the generated password (format: `xxxx-xxxx-xxxx-xxxx`)

### Step 2 — Redis store

Create a Redis database on your preferred provider. Note the **REST URL** and **auth token**.

### Step 3 — GitHub OAuth App (one-time)

Create a GitHub OAuth App at **Settings → Developer settings → OAuth Apps**:

- **Application name:** anything (e.g. `My MCP Servers`)
- **Homepage URL:** `https://your-service-url`
- **Callback URL:** `https://your-service-url/auth/callback`

Note the **Client ID** and generate a **Client Secret**.

### Step 4 — Deploy

1. Fork this repo
2. Deploy to your container hosting platform (a `render.yaml` is included for Render)
3. Set the environment variables listed below
4. Trigger a deploy

### Step 5 — Connect to your AI assistant

In your MCP-compatible AI assistant, add this server as a remote MCP connection:

- **URL:** `https://your-service-url/mcp`
- Authentication: leave empty — the server handles OAuth automatically

**For Claude:** paste the URL into the connector dialog at [claude.ai](https://claude.ai). Claude Desktop and mobile sync automatically from the web connector.

## Configuration reference

| Env var | Required | Rotates | Description |
|---|---|---|---|
| `ICLOUD_USERNAME` | ✅ | Never | Apple ID email |
| `ICLOUD_APP_PASSWORD` | ✅ | On reset | Apple app-specific password |
| `GITHUB_CLIENT_ID` | ✅ | Never | GitHub OAuth App client ID |
| `GITHUB_CLIENT_SECRET` | ✅ | Never | GitHub OAuth App client secret |
| `GITHUB_ALLOWED_USER_ID` | ✅ | Never | Immutable numeric GitHub user ID allowed to connect (preferred) |
| `GITHUB_ALLOWED_USER` | — | Never | GitHub username — legacy fallback, used only if `GITHUB_ALLOWED_USER_ID` is unset |
| `SERVER_URL` | ✅ | Never | Public base URL of this service |
| `UPSTASH_REDIS_REST_URL` | ✅ | Never | Redis REST endpoint |
| `UPSTASH_REDIS_REST_TOKEN` | ✅ | Never | Redis auth token |

## Troubleshooting

**"Calendar not found" error**
Call `list_calendars` first to see the exact names iCloud returns. Names are matched case-insensitively and listed in the error message.

**Events not showing up for today**
Pass the next day as `end_date` when querying a single day (e.g. `start_date: 2026-05-18`, `end_date: 2026-05-19`). CalDAV's date range is exclusive on the end.

**Recurring events appear only once**
iCloud CalDAV does not support server-side expansion of recurring events. Events are fetched as a single entry with their recurrence rules, not as individual occurrences.

**Server slow to respond (first request)**
The hosting platform may sleep the container after inactivity. The first request after a cold start can take 30–60 seconds. Subsequent requests are fast.

## Architecture

- **Transport:** Streamable HTTP (MCP 1.x) via FastMCP + uvicorn
- **Auth:** GitHub OAuth 2.0 — server acts as Authorization Server, GitHub as Identity Provider
- **User restriction:** GitHub user ID verified against `GITHUB_ALLOWED_USER_ID` on every login (immutable; `GITHUB_ALLOWED_USER` is a legacy username fallback)
- **Token lifetime:** 30-day access token, 30-day refresh token (rotated on each refresh)
- **Token persistence:** Redis-compatible store — tokens survive container restarts
- **Calendar API:** Apple CalDAV at `caldav.icloud.com` using Apple ID + app-specific password

## Contributing

This code was built with AI assistance ([Claude Code](https://claude.ai/code)) — vibe-coded with the best intentions. Security has been a priority throughout, but the code has not been independently audited. Use it at your own risk. If you spot a bug, a vulnerability, or an opportunity to improve anything, issues and pull requests are very welcome.

## Credits

Built with [Claude Code](https://claude.ai/code).
