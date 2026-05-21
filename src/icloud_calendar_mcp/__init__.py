import logging
import os
import sys

import anyio
import uvicorn
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import JSONResponse

from icloud_calendar_mcp import calendar
from icloud_calendar_mcp.github_oauth_provider import GitHubOAuthProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SERVER_URL = os.getenv("SERVER_URL", "")


def _build_app() -> tuple[FastMCP, GitHubOAuthProvider]:
    github_client_id     = os.getenv("GITHUB_CLIENT_ID", "")
    github_client_secret = os.getenv("GITHUB_CLIENT_SECRET", "")

    if not github_client_id or not github_client_secret:
        logger.error("GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET must be set.")
        sys.exit(1)

    if not SERVER_URL:
        logger.error("SERVER_URL must be set to the public base URL of this service.")
        sys.exit(1)

    oauth_provider = GitHubOAuthProvider(
        github_client_id=github_client_id,
        github_client_secret=github_client_secret,
        server_url=SERVER_URL,
    )

    auth_settings = AuthSettings(
        issuer_url=AnyHttpUrl(SERVER_URL),
        resource_server_url=AnyHttpUrl(SERVER_URL),
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["mcp"],
            default_scopes=["mcp"],
        ),
        revocation_options=RevocationOptions(enabled=True),
    )

    mcp_app = FastMCP(
        "iCloud Calendar MCP Server",
        auth_server_provider=oauth_provider,
        auth=auth_settings,
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
    )

    @mcp_app.custom_route("/auth/callback", methods=["GET"])
    async def github_callback(request: Request):
        return await oauth_provider.handle_github_callback(request)

    @mcp_app.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return mcp_app, oauth_provider


def _get_icloud_credentials() -> tuple[str, str]:
    username = os.getenv("ICLOUD_USERNAME", "")
    password = os.getenv("ICLOUD_APP_PASSWORD", "")
    if not username or not password:
        logger.error("ICLOUD_USERNAME and ICLOUD_APP_PASSWORD must be set.")
        sys.exit(1)
    return username, password


async def _serve(mcp_app: FastMCP) -> None:
    starlette_app = mcp_app.streamable_http_app()
    config = uvicorn.Config(
        starlette_app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        log_level="info",
    )
    await uvicorn.Server(config).serve()


def main() -> None:
    username, password = _get_icloud_credentials()
    mcp_app, _ = _build_app()

    calendar.register_tools(mcp_app, username, password)

    logger.info(
        "GitHub OAuth active — only '%s' can authenticate.",
        os.getenv("GITHUB_ALLOWED_USER", "(not configured)"),
    )
    logger.info("iCloud CalDAV user: %s", username)
    anyio.run(_serve, mcp_app)
