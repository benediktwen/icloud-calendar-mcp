# iCloud Calendar MCP Server

Remote MCP server for Apple iCloud Calendar via CalDAV, deployed on Render.
Gives Claude read/write access to your Apple Calendar across all devices.

## What it does

Exposes 7 calendar tools via MCP so Claude can manage your iCloud Calendar directly:

- **Read:** list calendars, list events by date range, get a single event by UID
- **Write:** create, update, and delete events
- **Search:** full-text search across all calendars by title, description, or location

## Infrastructure

| Component | Provider | Region |
|---|---|---|
| MCP server | Render (Free, Instant) | Frankfurt (EU) |
| Token store | Upstash Redis | Frankfurt (EU) |
| Identity provider | GitHub OAuth | — |
| Calendar API | Apple CalDAV (`caldav.icloud.com`) | — |

> **Note — Render Free Tier cold starts:** The free Instant type spins down after
> ~15 minutes of inactivity. The first request after a cold start takes 30–60
> seconds while the container restarts. Upstash Redis ensures OAuth tokens
> survive restarts so Claude does **not** need to re-authenticate after a cold start.

## Security

Access is protected by **GitHub OAuth** — only the configured GitHub account
(`benediktwen`) can authenticate. Every MCP session requires a fresh GitHub login
with 2FA (Authy). No shared secrets are stored in Claude's config.

### How the OAuth flow works

```
Claude → /authorize → GitHub login (+ 2FA) → /auth/callback
       → username verified → MCP access token issued → MCP connection
```

1. Claude detects the MCP server requires OAuth
2. Browser opens — user logs in to GitHub with 2FA
3. Server verifies the GitHub username matches `GITHUB_ALLOWED_USER`
4. Claude receives a time-limited access token (8 h) with silent refresh (30 days)

## Available Tools

| Tool | Description |
|---|---|
| `list_calendars` | List all calendars in the iCloud account (use this first to get exact names) |
| `list_events` | List events in a calendar within a date range |
| `get_event` | Get a single event by UID |
| `create_event` | Create a new calendar event |
| `update_event` | Update an existing event (partial updates supported) |
| `delete_event` | Delete an event by UID |
| `search_events` | Full-text search across all calendars |

> **Tip:** Always call `list_calendars` first. Calendar names are matched case-insensitively,
> and if a name doesn't match, the error message will list all available names.

## Setup

### Step 1 — Apple App-Specific Password (one-time)

iCloud requires an app-specific password — your main Apple ID password will not work.

1. Go to [appleid.apple.com](https://appleid.apple.com)
2. Sign in → **Sign-In and Security** → **App-Specific Passwords**
3. Click **+** and label it `icloud-calendar-mcp`
4. Copy the generated password (format: `xxxx-xxxx-xxxx-xxxx`)

### Step 2 — GitHub OAuth App (one-time)

Create a GitHub OAuth App at Settings → Developer settings → OAuth Apps.

- **Application name:** `icloud-calendar-mcp`
- **Homepage URL:** `https://icloud-calendar-mcp-ijmw.onrender.com`
- **Callback URL:** `https://icloud-calendar-mcp-ijmw.onrender.com/auth/callback`

Note the **Client ID** and generate a **Client Secret** — both go into Render env vars.

### Step 3 — Configure Render

Render Dashboard → `icloud-calendar-mcp` → Environment Variables:

| Variable | Value |
|---|---|
| `ICLOUD_USERNAME` | Your Apple ID email address |
| `ICLOUD_APP_PASSWORD` | App-specific password from Step 1 |
| `GITHUB_CLIENT_ID` | From your GitHub OAuth App |
| `GITHUB_CLIENT_SECRET` | From your GitHub OAuth App |
| `SERVER_URL` | `https://icloud-calendar-mcp-ijmw.onrender.com` |
| `UPSTASH_REDIS_REST_URL` | From Upstash console |
| `UPSTASH_REDIS_REST_TOKEN` | From Upstash console |

`GITHUB_ALLOWED_USER` is set to `benediktwen` via `render.yaml` — no manual entry needed.

### Step 4 — Configure Claude (one-time, never changes)

Add the server to your MCP config:

```json
{
  "mcpServers": {
    "icloud-calendar": {
      "type": "http",
      "url": "https://icloud-calendar-mcp-ijmw.onrender.com/mcp"
    }
  }
}
```

### Step 5 — First connection

1. Click Connect in Claude
2. Browser opens → GitHub login → 2FA with Authy
3. Access granted — token valid for 8 hours, refreshes silently for 30 days

## Deployment

Render is connected to this GitHub repository and **auto-deploys on every push to `main`**.
No manual deploy step is needed after code changes — push the commit and Render picks it up within a minute.

For environment variable changes only (no code change), trigger a manual deploy from the Render dashboard.

## Configuration Reference

| Variable | Required | Rotates | Description |
|---|---|---|---|
| `ICLOUD_USERNAME` | ✅ | Never | Apple ID email |
| `ICLOUD_APP_PASSWORD` | ✅ | On reset | Apple app-specific password |
| `GITHUB_CLIENT_ID` | ✅ | Never | GitHub OAuth App client ID |
| `GITHUB_CLIENT_SECRET` | ✅ | Never | GitHub OAuth App client secret |
| `GITHUB_ALLOWED_USER` | ✅ | Never | GitHub username allowed to connect (set via `render.yaml`) |
| `SERVER_URL` | ✅ | Never | Public base URL of the Render service |
| `UPSTASH_REDIS_REST_URL` | ✅ | Never | Upstash Redis REST endpoint |
| `UPSTASH_REDIS_REST_TOKEN` | ✅ | Never | Upstash Redis auth token |

## Troubleshooting

**"Calendar not found" error**
Call `list_calendars` first to see the exact names iCloud returns. The tool matches case-insensitively and lists available names in the error message.

**Events not showing up for today**
Pass the next day as `end_date` when querying a single day (e.g. `start_date: 2026-05-18`, `end_date: 2026-05-19`). CalDAV's date range is exclusive on the end — same-day start/end returns nothing. The `list_events` and `search_events` tools handle this automatically for date-only strings.

**Server slow to respond (first request)**
Render's free tier spins down after inactivity. The first request after a period of no use can take 30–60 seconds while the container restarts. Subsequent requests are fast.

**Token lost after restart**
Verify Upstash Redis is configured in your environment variables. Without it, tokens are stored in memory and lost on every cold start, requiring re-authentication.

**Recurring events appear only once**
iCloud CalDAV does not support server-side expansion of recurring events. Events are fetched without expansion and appear as a single entry with their original recurrence rules, not as individual occurrences.

## Architecture

- **Runtime:** Docker on Render Free Instant tier (Frankfurt)
- **Transport:** Streamable HTTP (MCP 1.x standard) via FastMCP + uvicorn
- **MCP auth:** GitHub OAuth 2.0 — server acts as Authorization Server, GitHub as Identity Provider
- **User restriction:** GitHub username verified against `GITHUB_ALLOWED_USER` on every login
- **Token lifetime:** 8 h access token, 30-day refresh token (rotated on each refresh)
- **Token persistence:** Upstash Redis (Frankfurt) — tokens survive Render cold starts
- **Calendar API:** Apple CalDAV at `caldav.icloud.com` using Apple ID + app-specific password
