# icloud-calendar-mcp

MCP server for Apple iCloud Calendar via CalDAV. Hosted on Render, secured with GitHub OAuth.

## Tools

| Tool | Description |
|---|---|
| `list_calendars` | List all calendars in the iCloud account |
| `list_events` | List events in a calendar within a date range |
| `get_event` | Get a single event by UID |
| `create_event` | Create a new calendar event |
| `update_event` | Update an existing event (partial updates supported) |
| `delete_event` | Delete an event by UID |
| `search_events` | Full-text search across all calendars |

## Setup

### 1. Apple App-Specific Password

1. Go to [appleid.apple.com](https://appleid.apple.com) → Sign-In and Security → App-Specific Passwords
2. Generate a new password labelled `icloud-calendar-mcp`

### 2. GitHub OAuth App

1. Go to GitHub → Settings → Developer settings → OAuth Apps → New OAuth App
2. Set **Authorization callback URL** to `https://<your-render-url>/auth/callback`
3. Note the **Client ID** and **Client Secret**

### 3. Deploy to Render

1. Connect this repo in Render as a new **Web Service** (Docker runtime)
2. Set environment variables:

| Variable | Value |
|---|---|
| `ICLOUD_USERNAME` | Your Apple ID email |
| `ICLOUD_APP_PASSWORD` | App-Specific Password from step 1 |
| `GITHUB_CLIENT_ID` | From step 2 |
| `GITHUB_CLIENT_SECRET` | From step 2 |
| `SERVER_URL` | Your Render URL, e.g. `https://icloud-calendar-mcp.onrender.com` |
| `UPSTASH_REDIS_REST_URL` | From Upstash (optional but recommended) |
| `UPSTASH_REDIS_REST_TOKEN` | From Upstash (optional but recommended) |

### 4. Connect in Claude Code

Add to your MCP config:

```json
{
  "mcpServers": {
    "icloud-calendar": {
      "type": "http",
      "url": "https://icloud-calendar-mcp.onrender.com/mcp"
    }
  }
}
```
