# icloud-calendar-mcp

MCP server for Apple iCloud Calendar via CalDAV. Gives Claude read/write access to your Apple Calendar — list, create, update, delete, and search events across all your calendars.

Hosted on Render, secured with GitHub OAuth (only your GitHub account can authenticate).

**Live URL:** `https://icloud-calendar-mcp-ijmw.onrender.com`

---

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

> **Tip:** Always call `list_calendars` first. Calendar names are matched case-insensitively, and if a name doesn't match, the error message will show all available calendar names.

---

## Setup

### 1. Generate an Apple App-Specific Password

iCloud requires an app-specific password — you cannot use your main Apple ID password.

1. Go to [appleid.apple.com](https://appleid.apple.com)
2. Sign in → **Sign-In and Security** → **App-Specific Passwords**
3. Click **+** and label it `icloud-calendar-mcp`
4. Copy the generated password (format: `xxxx-xxxx-xxxx-xxxx`)

### 2. Create a GitHub OAuth App

This controls who can authenticate with the MCP server. Only your GitHub account will be allowed.

1. Go to [github.com/settings/developers](https://github.com/settings/developers) → **OAuth Apps** → **New OAuth App**
2. Fill in:
   - **Application name:** `icloud-calendar-mcp`
   - **Homepage URL:** `https://icloud-calendar-mcp-ijmw.onrender.com`
   - **Authorization callback URL:** `https://icloud-calendar-mcp-ijmw.onrender.com/auth/callback`
3. Click **Register application**
4. On the next page, note the **Client ID** and generate a **Client Secret**

### 3. Set Environment Variables on Render

In your Render dashboard, open the `icloud-calendar-mcp` service → **Environment** and set:

| Variable | Value |
|---|---|
| `ICLOUD_USERNAME` | Your Apple ID email address |
| `ICLOUD_APP_PASSWORD` | The app-specific password from step 1 |
| `GITHUB_CLIENT_ID` | Client ID from step 2 |
| `GITHUB_CLIENT_SECRET` | Client Secret from step 2 |
| `SERVER_URL` | `https://icloud-calendar-mcp-ijmw.onrender.com` |
| `UPSTASH_REDIS_REST_URL` | From your Upstash dashboard (keeps tokens alive across cold starts) |
| `UPSTASH_REDIS_REST_TOKEN` | From your Upstash dashboard |

> **Note:** `GITHUB_ALLOWED_USER` is already set to `benediktwen` via `render.yaml` — no need to add it manually.

### 4. Connect in Claude Code

Run `/mcp` in Claude Code and add a new server, or add it directly to your MCP config file:

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

On first use, Claude will open a browser window to complete the GitHub OAuth login.

---

## Troubleshooting

**"Calendar not found" error**
Call `list_calendars` first to see the exact names iCloud returns. The tool matches case-insensitively and will list available names in the error message.

**Server slow to respond (first request)**
Render's free tier spins down after inactivity. The first request after a period of no use can take 30–60 seconds while the container restarts. Subsequent requests are fast.

**Token lost after restart**
Configure Upstash Redis in your environment variables. Without it, tokens are stored in memory and lost on every cold start, requiring re-authentication.

**Events not showing up**
iCloud CalDAV does not support server-side expansion of recurring events. The server fetches events without expansion — recurring events will appear as a single entry with their original recurrence rules, not as individual expanded occurrences.

---

## Architecture

Same pattern as `alpaca-mcp`:

- **Language:** Python + FastMCP
- **Auth:** GitHub OAuth — only `benediktwen` can authenticate
- **Token storage:** Upstash Redis — tokens survive Render free-tier cold starts
- **Transport:** Streamable HTTP (uvicorn)
- **CalDAV:** Connects to `caldav.icloud.com` using your Apple ID + app-specific password
