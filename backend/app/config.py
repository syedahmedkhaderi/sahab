"""Application configuration loaded from environment variables / .env file."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import AnyHttpUrl, EmailStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Domain and exposure ----
    public_hostname: str = "localhost"
    cloudflare_tunnel_token: str = ""

    # ---- Database / cache ----
    postgres_user: str = "sahab"
    postgres_password: str = "sahab"
    postgres_db: str = "sahab"
    database_url: str = "sqlite+aiosqlite:///./sahab_dev.db"
    redis_url: str = "redis://localhost:6379/0"

    # ---- Auth ----
    jwt_secret: str = "dev-secret-change-in-production"
    # Fernet key used to encrypt node SSH credentials at rest (app/services/crypto.py).
    # bootstrap.sh generates a real one; the default only keeps local dev working.
    secrets_key: str = "dev-secrets-key-change-in-production"
    jwt_expire_minutes: int = 720
    # Comma-separated list of allowed signup email domains
    allowed_signup_domains: str = "udst.edu.qa"
    require_admin_approval: bool = True

    # Bootstrap admin seeded on first run
    bootstrap_admin_email: str = "admin@udst.edu.qa"
    bootstrap_admin_password: str = "change-me-admin-password"

    # ---- OAuth provider (FastAPI -> JupyterHub SSO) ----
    oauth_client_id: str = "jupyterhub"
    oauth_client_secret: str = "change-me-oauth-secret"

    # ---- JupyterHub integration ----
    jupyterhub_api_url: str = "http://jupyterhub:8081/hub/api"
    jupyterhub_api_token: str = "change-me-hub-api-token"
    jupyterhub_public_url: str = "http://jupyterhub:8000"

    # ---- Policy defaults ----
    gpu_session_max_minutes: int = 240
    idle_timeout_minutes: int = 45
    default_user_disk_quota_gb: int = 50
    credits_per_minute_l4: float = 1.0
    credits_per_minute_cpu: float = 0.0
    default_credit_grant: float = 240.0
    max_concurrent_sessions_per_user: int = 1

    # ---- Workspace ----
    workspace_gpu_image: str = "sahab-gpu-pytorch:latest"
    workspace_cpu_image: str = "sahab-cpu-base:latest"
    docker_network_name: str = "sahab-network"
    shared_datasets_path: str = "/data/shared"
    user_volumes_path: str = "/data/users"

    # ---- Multi-node cluster ----
    # Hostname of the machine running the control plane. It is seeded as the first
    # node, and workspaces placed on it use the local Docker socket.
    manager_node_name: str = ""
    # Address other machines dial to reach this one: swarm 2377, registry 5000,
    # and the enrollment API. Written by bootstrap.sh from `docker swarm init`.
    manager_advertise_addr: str = ""
    # `docker swarm join-token -q worker` output, captured by bootstrap.sh. The
    # backend has no Docker access by design, so it is passed in rather than read.
    swarm_worker_token: str = ""
    # Where the CA lives. Bind-mounted rw into backend, ro into jupyterhub.
    node_pki_dir: str = "/srv/sahab/secrets/docker-ca"
    # The spawner reads this file to learn each node's address and cert paths.
    node_map_path: str = "/srv/sahab/secrets/nodes.json"
    # Prometheus file_sd target list, rewritten whenever the node set changes.
    prometheus_targets_path: str = "/srv/sahab/targets/nodes.json"
    # Private registry the workspace images are pushed to and nodes pull from.
    registry_addr: str = ""
    # Public base URL a joining node uses to reach this API. Falls back to
    # https://{public_hostname} when unset.
    node_enroll_base_url: str = ""
    # How long a node's Docker API may stay unreachable before its running
    # sessions are failed and its GPUs taken out of the pool.
    node_unreachable_grace_seconds: int = 300
    # Git remote + branch a joining node installs from.
    sahab_repo_url: str = "https://github.com/syedahmedkhaderi/sahab.git"
    sahab_branch: str = "main"

    # ---- GPU busy probe ----
    # The scheduler cross-checks the DCGM exporter before handing out a GPU that
    # the DB believes is free, so a job started outside Sahab is not overwritten.
    dcgm_metrics_url: str = "http://dcgm-exporter:9400/metrics"
    busy_vram_mb: float = 1024.0
    busy_util_pct: float = 30.0

    # ---- Monitoring ----
    grafana_admin_user: str = "admin"
    grafana_admin_password: str = "change-me-grafana"

    # ---- Debug ----
    # Publishes /api/docs, /api/redoc and /api/openapi.json. Off in production.
    debug: bool = False

    @property
    def enroll_base_url(self) -> str:
        """Base URL a joining node posts its enrollment to."""
        if self.node_enroll_base_url:
            return self.node_enroll_base_url.rstrip("/")
        return f"https://{self.public_hostname}"

    @property
    def allowed_domains_list(self) -> list[str]:
        """Return allowed signup domains as a list."""
        return [d.strip().lower() for d in self.allowed_signup_domains.split(",") if d.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
