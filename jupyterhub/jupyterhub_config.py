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

Placement: the control plane also passes the *machine* the GPU lives in, and
SahabDockerSpawner points its Docker client at that machine. A GPU UUID on its
own is meaningless to a container started somewhere else, so the two always
travel together.

Storage: each session gets its own volume, deleted when the session stops — the
same deal Colab offers. That is what makes several machines workable without
shared storage: a user's files never need to follow them between machines
because they do not outlive the session.
"""
import json
import logging
import os
import secrets
from concurrent.futures import ThreadPoolExecutor

import docker
from docker.tls import TLSConfig
from docker.utils import kwargs_from_env
from dockerspawner import DockerSpawner

_log = logging.getLogger("sahab.spawner")

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
# SahabDockerSpawner — DockerSpawner that can start a container on another machine
#
# Stock DockerSpawner caches ONE Docker client on the class (`cls._client`) and
# shares ONE single-threaded executor across every spawn, both of which assume a
# single machine. Overriding those two properties is the whole of what multi-node
# placement needs: everything else — the hardening, the NVIDIA runtime, the
# volume handling, the networking — is unchanged, which is exactly why this is a
# subclass rather than a move to SwarmSpawner.
#
# Machines are read from a small JSON map the control plane rewrites whenever the
# node set changes, so adding a GPU server never requires restarting the hub.
# ---------------------------------------------------------------------------
_NODE_MAP_PATH = os.environ.get("SAHAB_NODE_MAP", "/srv/sahab/secrets/nodes.json")
_LOCAL_NODE = "local"


def _read_node_map():
    """Load the node map, tolerating its absence.

    A missing or unreadable map is not fatal: it means "no other machines yet",
    which is the correct answer for a single-VM install and keeps the hub working
    if the file is momentarily mid-write.
    """
    try:
        with open(_NODE_MAP_PATH) as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        _log.debug("No usable node map at %s (%s)", _NODE_MAP_PATH, exc)
        return {}


class SahabDockerSpawner(DockerSpawner):
    """DockerSpawner whose Docker endpoint is chosen per spawn."""

    # Keyed by node name, not shared: one client per machine.
    _clients: dict = {}
    _executors: dict = {}

    # Set by load_state so a container started before a hub restart can still be
    # polled and stopped — its machine has to be remembered, not re-derived.
    _restored_node = None
    _volume_name = None

    # -- which machine -------------------------------------------------------

    @property
    def node_name(self):
        return self.user_options.get("node") or self._restored_node or _LOCAL_NODE

    def _node_entry(self):
        return (_read_node_map().get("nodes") or {}).get(self.node_name) or {}

    # -- Docker endpoint -----------------------------------------------------

    @property
    def client(self):
        """A Docker client for this spawn's machine, cached per machine.

        Overrides DockerSpawner's single global client. The local machine keeps
        the Unix socket it always used; anything else goes over the cluster's
        mutually authenticated Docker API.
        """
        name = self.node_name
        cached = type(self)._clients.get(name)
        if cached is not None:
            return cached

        entry = self._node_entry()
        if name == _LOCAL_NODE or entry.get("local") or not entry.get("address"):
            client = docker.APIClient(version="auto", **kwargs_from_env())
        else:
            node_map = _read_node_map()
            tls = TLSConfig(
                client_cert=(node_map["client_cert"], node_map["client_key"]),
                ca_cert=node_map["ca_cert"],
                verify=True,
            )
            base_url = f"https://{entry['address']}:{entry.get('docker_port', 2376)}"
            self.log.info("Spawning on node %s via %s", name, base_url)
            client = docker.APIClient(base_url=base_url, tls=tls, version="auto")

        type(self)._clients[name] = client
        return client

    @property
    def executor(self):
        """One thread pool per machine.

        Stock DockerSpawner uses a single shared thread for every Docker call in
        the hub. That was fine when every call went to a local socket; across
        machines it would let one slow or unreachable node stall every other
        user's spawn behind it.
        """
        name = self.node_name
        pool = type(self)._executors.get(name)
        if pool is None:
            pool = ThreadPoolExecutor(4)
            type(self)._executors[name] = pool
        return pool

    # -- state ---------------------------------------------------------------

    def get_state(self):
        state = super().get_state()
        state["node"] = self.node_name
        if self._volume_name:
            state["volume_name"] = self._volume_name
        return state

    def load_state(self, state):
        super().load_state(state)
        self._restored_node = state.get("node")
        self._volume_name = state.get("volume_name")


c.JupyterHub.spawner_class = SahabDockerSpawner

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

    # Give this session its own scratch volume. It is created on whichever
    # machine the container lands on and destroyed with the session, which is
    # what lets a user be placed on any machine without their files having to
    # follow them. Named per-spawn rather than per-user so two sessions can never
    # share one, and so the name is unambiguous when it comes time to delete it.
    spawner._volume_name = f"sahab-ws-{spawner.user.name}-{secrets.token_hex(4)}"
    spawner.volumes = {
        spawner._volume_name: _notebook_dir,
        _shared_datasets: {"bind": "/home/jovyan/shared", "mode": "ro"},
    }

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


async def post_stop_hook(spawner):
    """Delete the session's scratch volume once its container is gone.

    Sahab's storage is session-scoped, so this is where "your files are deleted
    when the session ends" actually happens. Two safeguards:

    * Only volumes named ``sahab-ws-*`` are ever touched, so a stray value in
      spawner state can never delete something else.
    * A sweep of this machine's other ``sahab-ws-*`` volumes follows, which
      reclaims the ones orphaned when the hub was killed mid-session. Docker
      refuses to remove a volume that is in use, so the sweep cannot take a live
      session's files.
    """
    name = getattr(spawner, "_volume_name", None)
    if name and name.startswith("sahab-ws-"):
        try:
            await spawner.docker("remove_volume", name, force=True)
            spawner.log.info("Removed session volume %s", name)
        except Exception as exc:
            spawner.log.warning("Could not remove session volume %s: %s", name, exc)
    spawner._volume_name = None

    try:
        volumes = await spawner.docker("volumes", filters={"dangling": True})
        for volume in (volumes or {}).get("Volumes") or []:
            vol_name = volume.get("Name", "")
            if not vol_name.startswith("sahab-ws-"):
                continue
            try:
                await spawner.docker("remove_volume", vol_name)
                spawner.log.info("Reclaimed orphaned session volume %s", vol_name)
            except Exception:
                # In use by a live session, or already gone. Either is fine.
                pass
    except Exception as exc:
        spawner.log.debug("Session volume sweep skipped: %s", exc)


c.Spawner.pre_spawn_hook = pre_spawn_hook
c.Spawner.post_stop_hook = post_stop_hook

# ---------------------------------------------------------------------------
# Session-scoped storage and shared read-only datasets
#
# Sahab's workspaces are ephemeral, the way Colab's are: what a user writes under
# /home/jovyan/work lives in a volume created for that session and deleted when
# it ends (see pre_spawn_hook / post_stop_hook above). Two reasons, in order of
# weight:
#
#   1. It is what makes several GPU servers workable at all. A persistent
#      per-user volume exists on exactly one machine, so a user would either be
#      pinned to that machine — wasting every GPU on the others — or find their
#      notebooks missing depending on where they landed.
#   2. It bounds disk growth on a shared university machine without a quota
#      system nobody has set up.
#
# The cost is real and the product must say so plainly rather than let someone
# discover it: the launch form and the workspace shell both carry the warning.
#
# The values below are the defaults; the per-session volume is set per spawn.
# ---------------------------------------------------------------------------
_notebook_dir = "/home/jovyan/work"
_shared_datasets = os.environ.get("SHARED_DATASETS_PATH", "/data/shared")

c.DockerSpawner.notebook_dir = _notebook_dir
c.DockerSpawner.volumes = {
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
