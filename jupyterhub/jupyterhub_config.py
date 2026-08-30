"""jupyterhub_config.py — Sahab production JupyterHub configuration.

Supports two authentication modes selected by the AUTH_MODE env var:
  AUTH_MODE=oauth  (default) — GenericOAuthenticator pointing at the FastAPI OAuth provider.
  AUTH_MODE=native           — NativeAuthenticator for standalone Phase-1 use.

Security hardening per §16: cap_drop, no-new-privileges, pids_limit, no Docker socket
in user containers.

GPU assignment: the control plane leases a GPU and passes its UUID per-session
through the JupyterHub API user options. A pre_spawn_hook turns that into
NVIDIA_VISIBLE_DEVICES plus the nvidia runtime. Without a leased UUID the spawn
is CPU-only and never touches the NVIDIA stack.
"""
import os

# ---------------------------------------------------------------------------
# Hub network settings
# ---------------------------------------------------------------------------
c.JupyterHub.hub_ip = "0.0.0.0"
c.JupyterHub.hub_connect_ip = os.environ.get("HUB_CONNECT_IP", "jupyterhub")
c.JupyterHub.port = 8000

# The hub exposes its admin API on a separate port so Traefik only routes /hub/* /user/*
# and the admin API stays internal.
c.JupyterHub.hub_port = 8081

# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
c.JupyterHub.db_url = os.environ.get(
    "JUPYTERHUB_DB_URL", "sqlite:////srv/jupyterhub/jupyterhub.sqlite"
)
c.JupyterHub.cookie_secret_file = "/srv/jupyterhub/jupyterhub_cookie_secret"
# Prometheus scrapes the hub from the internal Docker network; disable auth so
# metrics collection works without introducing another managed service token.
c.JupyterHub.authenticate_prometheus = False

# ---------------------------------------------------------------------------
# Embedding: let the Sahab workspace shell frame the hub's pages.
#
# JupyterHub 4.1 changed the default CSP from `frame-ancestors 'self'` to
# `'none'` (see jupyterhub/handlers/base.py::content_security_policy, whose
# docstring notes it can be overridden through settings['headers']).
#
# Sahab's app, API, hub and single-user servers are all on one origin, and
# /sessions/<id>/workspace embeds the workspace there so the user has a way
# back out, a stop button and their credit usage. The hub's own pages appear in
# that frame during the OAuth handoff, so the hub needs the same policy the
# single-user servers get in images/*/jupyter_server_config.py.
#
# 'self' is the narrowest policy that allows it: same-origin pages only, so an
# attacker would already need to control a page on this domain.
# ---------------------------------------------------------------------------
c.JupyterHub.tornado_settings = {
    "headers": {"Content-Security-Policy": "frame-ancestors 'self'"}
}

# ---------------------------------------------------------------------------
# DockerSpawner
# ---------------------------------------------------------------------------
c.JupyterHub.spawner_class = "dockerspawner.DockerSpawner"

# Default to GPU image; control plane overrides per-session via user_options.
c.DockerSpawner.image = os.environ.get("WORKSPACE_GPU_IMAGE", "sahab-gpu-pytorch:latest")
# Allow the control plane to select any configured workspace image at spawn time.
c.DockerSpawner.allowed_images = "*"

# User containers join the same overlay network as the hub so they can reach
# the hub for auth, but NOT the host or the DB (network isolation per §16).
c.DockerSpawner.network_name = os.environ.get("DOCKER_NETWORK_NAME", "sahab-network")
c.DockerSpawner.use_internal_ip = True

# Remove the container on stop so stale containers don't accumulate.
c.DockerSpawner.remove = True

# ---------------------------------------------------------------------------
# Security hardening (§16): unprivileged containers, no new privileges, PID cap.
# The Docker socket is NEVER mounted into user containers.
# ---------------------------------------------------------------------------
# The NVIDIA runtime is NOT applied here: a container asking for it is rejected
# outright if any requested device is unknown to the driver, which would make a
# CPU workspace fail for a GPU-side reason. pre_spawn_hook adds it per-spawn,
# only when the control plane leased a GPU.
_BASE_HOST_CONFIG = {
    "cap_drop": ["ALL"],
    "security_opt": ["no-new-privileges:true"],
    "pids_limit": 512,
}

c.DockerSpawner.extra_host_config = dict(_BASE_HOST_CONFIG)

# ---------------------------------------------------------------------------
# Per-user GPU assignment via pre_spawn_hook.
# The control plane passes the leased GPU UUID through user_options at spawn
# time. No UUID means a CPU workspace — never "all", which would hand a user
# every GPU on the host including ones already leased to someone else.
# ---------------------------------------------------------------------------
async def pre_spawn_hook(spawner):
    """Attach a GPU only when the control plane leased one for this session."""
    gpu_uuid = spawner.user_options.get("gpu_uuid")
    host_config = dict(_BASE_HOST_CONFIG)

    if gpu_uuid:
        host_config["runtime"] = "nvidia"
        spawner.environment["NVIDIA_VISIBLE_DEVICES"] = gpu_uuid
        spawner.environment["NVIDIA_DRIVER_CAPABILITIES"] = "compute,utility"
    else:
        # A CPU workspace never touches the NVIDIA stack, so it stays launchable
        # even when the GPU inventory is wrong or the driver is unhappy.
        spawner.environment["NVIDIA_VISIBLE_DEVICES"] = "void"

    spawner.extra_host_config = host_config

    # Allow the control plane to select a different image per-session.
    if "image" in spawner.user_options:
        spawner.image = spawner.user_options["image"]
    if "mem_limit" in spawner.user_options:
        spawner.mem_limit = spawner.user_options["mem_limit"]
    if "cpu_limit" in spawner.user_options:
        spawner.cpu_limit = float(spawner.user_options["cpu_limit"])


c.Spawner.pre_spawn_hook = pre_spawn_hook

# ---------------------------------------------------------------------------
# Per-user persistent volume and shared read-only datasets
# ---------------------------------------------------------------------------
_notebook_dir = "/home/jovyan/work"
_shared_datasets = os.environ.get("SHARED_DATASETS_PATH", "/data/shared")

c.DockerSpawner.notebook_dir = _notebook_dir
c.DockerSpawner.volumes = {
    "sahab-user-{username}": _notebook_dir,
    _shared_datasets: {"bind": "/home/jovyan/shared", "mode": "ro"},
}

# ---------------------------------------------------------------------------
# Resource limits per container (§16)
# ---------------------------------------------------------------------------
c.DockerSpawner.mem_limit = os.environ.get("CONTAINER_MEM_LIMIT", "32G")
c.DockerSpawner.cpu_limit = float(os.environ.get("CONTAINER_CPU_LIMIT", "8"))

# ---------------------------------------------------------------------------
# Idle-culler service (§7: idle timeout = 45 min = 2700 s)
# ---------------------------------------------------------------------------
c.JupyterHub.load_roles = [
    {
        "name": "idle-culler",
        "scopes": [
            "list:users",
            "read:users:activity",
            "servers",
        ],
        "services": ["idle-culler"],
    }
]

c.JupyterHub.services = [
    {
        "name": "idle-culler",
        "command": [
            "python", "-m", "jupyterhub_idle_culler",
            f"--timeout={os.environ.get('IDLE_TIMEOUT_SECONDS', '2700')}",
            "--cull-users=False",
        ],
    }
]

# ---------------------------------------------------------------------------
# Authentication — selected by AUTH_MODE env var
# ---------------------------------------------------------------------------
_auth_mode = os.environ.get("AUTH_MODE", "oauth").lower()

if _auth_mode == "native":
    # Phase-1 standalone: NativeAuthenticator (username + password stored locally)
    c.JupyterHub.authenticator_class = "nativeauthenticator.NativeAuthenticator"
    c.NativeAuthenticator.enable_signup = True
    c.NativeAuthenticator.minimum_password_length = 8
    c.NativeAuthenticator.check_common_password = True
    c.Authenticator.admin_users = {
        u.strip()
        for u in os.environ.get("JUPYTERHUB_ADMIN_USERS", "admin").split(",")
        if u.strip()
    }

else:
    # Production: GenericOAuthenticator -> FastAPI OAuth provider (§9)
    from oauthenticator.generic import GenericOAuthenticator

    c.JupyterHub.authenticator_class = GenericOAuthenticator

    # Two distinct base URLs are required:
    #   - internal: hub -> backend, server-to-server over the Docker network.
    #   - public:   browser redirects the user must be able to resolve.
    # authorize_url is a BROWSER redirect, so it MUST be the public URL.
    # token_url / userdata_url are server-to-server, so they use the internal URL.
    _api_internal = os.environ.get("API_BASE_URL", "http://backend:8000").rstrip("/")
    _public_host = os.environ.get("PUBLIC_HOSTNAME", "localhost")
    _api_public = f"https://{_public_host}"

    c.GenericOAuthenticator.client_id = os.environ.get("OAUTH_CLIENT_ID", "jupyterhub")
    c.GenericOAuthenticator.client_secret = os.environ.get("OAUTH_CLIENT_SECRET", "")
    c.GenericOAuthenticator.oauth_callback_url = f"{_api_public}/hub/oauth_callback"
    c.GenericOAuthenticator.authorize_url = f"{_api_public}/api/oauth/authorize"
    c.GenericOAuthenticator.token_url = f"{_api_internal}/api/oauth/token"
    c.GenericOAuthenticator.userdata_url = f"{_api_internal}/api/oauth/userinfo"

    # The JupyterHub username must match the username the control plane spawns
    # servers under (email local-part). userinfo returns it as preferred_username;
    # "sub" stays the stable user UUID. Mismatching these breaks the handoff.
    c.GenericOAuthenticator.username_claim = "preferred_username"
    c.GenericOAuthenticator.login_service = "Sahab"
    c.GenericOAuthenticator.allow_all = True  # access control is in FastAPI

    # Sahab is the only way in, so the hub's login page offers exactly one
    # button. Skipping it removes a click, and removes the one hub page that
    # would otherwise render inside the workspace shell's iframe mid-handoff.
    c.Authenticator.auto_login = True

# ---------------------------------------------------------------------------
# Service API token (used by the control plane to call JupyterHub's REST API)
# ---------------------------------------------------------------------------
_api_token = os.environ.get("JUPYTERHUB_API_TOKEN", "")
if _api_token:
    c.JupyterHub.services.append(
        {
            "name": "sahab-control-plane",
            "api_token": _api_token,
            "admin": True,
        }
    )
