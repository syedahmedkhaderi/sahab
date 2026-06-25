"""Pydantic v2 request/response models for the Sahab API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


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
    role: str | None = None
    status: str | None = None


class AdminCreateUserRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=256)
    password: str = Field(..., min_length=8, max_length=128)
    role: str = "student"
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
    kind: str  # "gpu" | "cpu"
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
    resource_type: str  # "l4_gpu" | "cpu"
    credits_per_minute: float = Field(..., ge=0)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


class SessionCreateRequest(BaseModel):
    resource_type: str = "l4_gpu"  # "l4_gpu" | "cpu"
    image_id: str | None = None
    cpu_fallback: bool = False  # If true, fall back to CPU when GPU unavailable


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    image_id: str | None
    resource_type: str
    state: str
    queue_pos: int | None
    started_at: datetime | None
    ended_at: datetime | None
    last_metered_at: datetime | None
    created_at: datetime


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


class GpuInventoryCreateRequest(BaseModel):
    gpu_uuid: str
    model: str
    vram_mb: int


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
