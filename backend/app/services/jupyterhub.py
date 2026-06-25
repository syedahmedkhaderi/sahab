"""JupyterHub REST API client.

Provides: ensure_user, start_server, stop_server, poll_status.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class JupyterHubClient:
    """Thin async wrapper around the JupyterHub REST API."""

    def __init__(self, settings: Settings) -> None:
        self._base = settings.jupyterhub_api_url.rstrip("/")
        self._token = settings.jupyterhub_api_token
        self._public_url = settings.jupyterhub_public_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"token {self._token}",
            "Content-Type": "application/json",
        }

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=self._headers(),
            timeout=30.0,
        )

    # ------------------------------------------------------------------
    # User management
    # ------------------------------------------------------------------

    async def ensure_user(self, username: str) -> None:
        """Create the JupyterHub user if they do not already exist."""
        async with self._client() as client:
            resp = await client.get(f"{self._base}/users/{username}")
            if resp.status_code == 404:
                resp2 = await client.post(f"{self._base}/users/{username}")
                resp2.raise_for_status()
                logger.info("JupyterHub: created user %s", username)
            elif resp.status_code != 200:
                resp.raise_for_status()

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------

    async def start_server(
        self,
        username: str,
        gpu_uuid: str | None,
        image: str,
        mem_limit: str = "32G",
        cpu_limit: float = 8.0,
    ) -> None:
        """
        Request JupyterHub to start this user's single-user server.

        The JupyterHub spawn API forwards the JSON body into spawner
        user_options, which our pre_spawn_hook reads to apply image,
        GPU assignment, and container resource limits.
        """
        payload: dict[str, Any] = {
            "image": image,
            "mem_limit": mem_limit,
            "cpu_limit": cpu_limit,
        }
        if gpu_uuid:
            payload["gpu_uuid"] = gpu_uuid

        async with self._client() as client:
            resp = await client.post(
                f"{self._base}/users/{username}/server",
                json=payload,
            )
            if resp.status_code not in (200, 201, 202):
                logger.error(
                    "JupyterHub start_server failed for %s: %s %s",
                    username,
                    resp.status_code,
                    resp.text,
                )
                resp.raise_for_status()
            logger.info("JupyterHub: requested server start for user %s", username)

    async def stop_server(self, username: str) -> None:
        """Request JupyterHub to stop this user's single-user server."""
        async with self._client() as client:
            resp = await client.delete(f"{self._base}/users/{username}/server")
            if resp.status_code not in (200, 202, 204):
                logger.error(
                    "JupyterHub stop_server failed for %s: %s %s",
                    username,
                    resp.status_code,
                    resp.text,
                )
                resp.raise_for_status()
            logger.info("JupyterHub: requested server stop for user %s", username)

    async def poll_status(self, username: str) -> str:
        """
        Return the server status for the user.

        Returns one of: "running", "starting", "stopped", "error".
        """
        async with self._client() as client:
            resp = await client.get(f"{self._base}/users/{username}")
            if resp.status_code == 404:
                return "stopped"
            resp.raise_for_status()
            data = resp.json()
            server = data.get("server") or data.get("servers", {}).get("", {})
            if not server:
                return "stopped"
            if server.get("ready"):
                return "running"
            if server.get("pending"):
                return "starting"
            return "stopped"

    def workspace_url(self, username: str) -> str:
        """Return the URL the browser should be redirected to for the workspace."""
        return f"{self._public_url}/user/{username}/lab"
