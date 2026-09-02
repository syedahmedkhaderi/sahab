"""Pydantic v2 request/response models for the Sahab API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Request fields that map to a database enum are typed with the enum itself
# rather than `str`. A plain string is accepted by Pydantic, reaches Postgres,
# and fails there — which surfaces to the user as a 500 and a stack trace in the
# log instead of "that is not a valid value". Typing them here turns the same
# mistake into a 422 that names the field and lists what is allowed, and it
# cannot drift from the model because it *is* the model's enum.
from app.models import ImageKind, ResourceType, UserRole, UserStatus


# ---------------------------------------------------------------------------
# Auth / User
# ---------------------------------------------------------------------------


class SignupRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=256)
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str | None
    role: str
    status: str
    credit_balance: float
    created_at: datetime


class UserUpdateRequest(BaseModel):
    full_name: str | None = None
    role: UserRole | None = None
    status: UserStatus | None = None


class ProfileUpdateRequest(BaseModel):
    """What a user may change about their own account.

    Deliberately just these two. Role, status and credit balance are not
    self-service — a request carrying them is rejected rather than ignored, so
    nobody is left believing they changed something they did not.
    """

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(None, min_length=1, max_length=256)
    password: str | None = Field(None, min_length=8, max_length=128)


class AdminCreateUserRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=256)
    password: str = Field(..., min_length=8, max_length=128)
    role: UserRole = UserRole.student
    credit_grant: float | None = None


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


class ImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    docker_ref: str
    kind: str
    is_default: bool
    enabled: bool


class ImageCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    docker_ref: str = Field(..., min_length=1)
    kind: ImageKind
    is_default: bool = False
    enabled: bool = True


class ImageUpdateRequest(BaseModel):
    name: str | None = None
    docker_ref: str | None = None
    is_default: bool | None = None
    enabled: bool | None = None


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------


class RateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    resource_type: str
    credits_per_minute: float


class RateUpsertRequest(BaseModel):
    # Unvalidated, this wrote a priced row for a resource type nothing can ever
    # request — junk that then shows up on the public /rates listing.
    resource_type: ResourceType
    credits_per_minute: float = Field(..., ge=0)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


class SessionCreateRequest(BaseModel):
    resource_type: ResourceType = ResourceType.l4_gpu
    image_id: str | None = None
    cpu_fallback: bool = False  # If true, fall back to CPU when GPU unavailable
    # When every free GPU is busy with work started outside Sahab, the default
    # is to say so rather than queue behind something we cannot see. Set this
    # once the user has been told and has chosen to wait anyway.
    queue_if_busy: bool = False


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    image_id: str | None
    resource_type: str
    state: str
    # Which machine the workspace was placed on. Null for a queued session (not
    # placed yet), a CPU session, and anything from before multi-machine support.
    node_id: str | None = None
    queue_pos: int | None
    started_at: datetime | None
    ended_at: datetime | None
    last_metered_at: datetime | None
    created_at: datetime

    # The environment's display name. Without it every row in a session list
    # reads "Workspace", which tells the reader nothing about what ran.
    image_name: str | None = None

    # Populated on the admin listing only. A console that shows a raw user UUID
    # where an operator expects a person is not usable.
    user_email: str | None = None
    user_full_name: str | None = None
    node_name: str | None = None


class SessionConnectOut(BaseModel):
    url: str
    session_id: str


# ---------------------------------------------------------------------------
# Credits / Ledger
# ---------------------------------------------------------------------------


class CreditGrantRequest(BaseModel):
    amount: float = Field(..., gt=0)
    reason: str = "grant"


class LedgerEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    delta: float
    reason: str
    session_id: str | None
    balance_after: float
    created_at: datetime


class UsageSummary(BaseModel):
    total_sessions: int
    total_gpu_minutes: float
    total_cpu_minutes: float
    total_credits_used: float


# ---------------------------------------------------------------------------
# GPU Inventory
# ---------------------------------------------------------------------------


class GpuInventoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    gpu_uuid: str
    model: str
    vram_mb: int
    status: str
    node_id: str
    # Denormalised for the admin table, which would otherwise need a second
    # request per row just to turn a node id into a machine name.
    node_name: str | None = None


class GpuInventoryCreateRequest(BaseModel):
    gpu_uuid: str
    model: str
    vram_mb: int
    # Which machine the card is in. Omitted means the control-plane VM, which is
    # what every GPU registered before multi-node support belonged to.
    node_id: str | None = None


# ---------------------------------------------------------------------------
# Admin metrics
# ---------------------------------------------------------------------------


class AdminMetrics(BaseModel):
    total_users: int
    active_sessions: int
    queued_sessions: int
    gpus_free: int
    gpus_leased: int
    gpus_disabled: int
    total_credits_granted: float
    total_credits_used: float


# ---------------------------------------------------------------------------
# OAuth provider (Authlib / JupyterHub)
# ---------------------------------------------------------------------------


class OAuthUserInfo(BaseModel):
    sub: str
    preferred_username: str
    email: str
    name: str | None
    role: str


# ---------------------------------------------------------------------------
# Nodes (GPU servers)
# ---------------------------------------------------------------------------


class NodeOut(BaseModel):
    """A machine in the pool, as the admin console sees it.

    Deliberately omits ssh_secret_enc: the stored credential never leaves the
    server, not even encrypted.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    display_name: str | None
    address: str
    docker_port: int
    metrics_url: str | None
    status: str
    is_manager: bool
    driver_version: str | None
    docker_version: str | None
    ssh_host: str | None
    ssh_port: int
    ssh_user: str | None
    ssh_auth_kind: str | None
    has_stored_credentials: bool = False
    last_seen_at: datetime | None
    enrolled_at: datetime | None
    created_at: datetime
    gpus_total: int = 0
    gpus_free: int = 0
    gpus_leased: int = 0


class NodeCreateRequest(BaseModel):
    """Register a machine and get back the command that enrols it.

    SSH details are optional: leave them out for the copy-paste path, supply
    them to have the control plane run the install itself.
    """

    display_name: str | None = Field(None, max_length=253)
    # Provisional name for the row until the machine reports its real hostname.
    name: str | None = Field(None, max_length=253)
    address: str | None = Field(None, max_length=253)
    ssh_host: str | None = Field(None, max_length=253)
    ssh_port: int = Field(22, ge=1, le=65535)
    ssh_user: str | None = Field(None, max_length=64)
    ssh_password: str | None = Field(None, max_length=1024)
    ssh_private_key: str | None = Field(None, max_length=32768)


class NodeCreateResponse(BaseModel):
    node: NodeOut
    # Shown once. The plaintext is never stored, so it cannot be shown again.
    enroll_token: str
    join_command: str
    expires_at: datetime


class NodeUpdateRequest(BaseModel):
    display_name: str | None = None
    # One of: ready, draining, disabled. The other states are set by the system,
    # not by hand.
    status: str | None = None
    address: str | None = None
    metrics_url: str | None = None
    ssh_host: str | None = None
    ssh_port: int | None = Field(None, ge=1, le=65535)
    ssh_user: str | None = None
    ssh_password: str | None = None
    ssh_private_key: str | None = None


class NodeInstallRequest(BaseModel):
    """Run the join script on the machine over SSH.

    Credentials given here are saved (encrypted) so upgrades can be re-run later;
    omit them to reuse what is already stored.
    """

    ssh_host: str | None = None
    ssh_port: int | None = Field(None, ge=1, le=65535)
    ssh_user: str | None = None
    ssh_password: str | None = None
    ssh_private_key: str | None = None
    # Optional Tailscale auth key, for a machine that is not on this LAN.
    vpn_auth_key: str | None = None


class NodeInstallLogOut(BaseModel):
    node_id: str
    status: str
    log: str
    started_at: datetime | None = None
    finished_at: datetime | None = None


class NodeCheckOut(BaseModel):
    node_id: str
    status: str
    reachable: bool
    detail: str | None = None


# ---- Enrollment (called by the joining machine, not by a browser) ----


class EnrollGpu(BaseModel):
    gpu_uuid: str = Field(..., max_length=256)
    model: str = Field("Unknown GPU", max_length=128)
    vram_mb: int = 0


class EnrollRequest(BaseModel):
    token: str
    hostname: str = Field(..., max_length=253)
    # The address the manager should dial back on: the node's LAN IP, or its
    # VPN address when it is not on this network.
    advertise_addr: str = Field(..., max_length=253)
    docker_port: int = Field(2376, ge=1, le=65535)
    driver_version: str | None = Field(None, max_length=64)
    docker_version: str | None = Field(None, max_length=64)
    gpus: list[EnrollGpu] = Field(default_factory=list)


class EnrollResponse(BaseModel):
    """Everything the machine needs to join, returned exactly once."""

    node_id: str
    node_name: str
    network_name: str
    swarm_join_token: str
    manager_addr: str
    registry_addr: str
    ca_cert: str
    server_cert: str
    server_key: str
    gpu_image: str
    cpu_image: str
    dcgm_port: int
    node_exporter_port: int
    cadvisor_port: int


class EnrollCompleteRequest(BaseModel):
    token: str


class EnrollCompleteResponse(BaseModel):
    node_id: str
    node_name: str
    status: str
    gpus_registered: int
    detail: str | None = None
