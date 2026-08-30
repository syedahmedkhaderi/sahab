"""Tests: the OAuth authorize hop that the JupyterHub handoff redirects through.

The workspace shell embeds JupyterLab in a same-origin iframe, so this endpoint
is now reached inside a frame. A 401 JSON body there lands on the user's screen
with no URL bar and no way out, which is why a missing session redirects to the
login page instead.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import User, UserStatus
from app.security import create_access_token


def _authorize_url() -> str:
    settings = get_settings()
    return (
        "/api/oauth/authorize"
        f"?response_type=code&client_id={settings.oauth_client_id}"
        "&redirect_uri=https%3A%2F%2Fexample.test%2Fhub%2Foauth_callback&state=xyz"
    )


@pytest.mark.asyncio
async def test_signed_out_visitor_is_redirected_to_login(client: AsyncClient) -> None:
    """No session: send them to sign in, never a bare 401 JSON body."""
    response = await client.get(_authorize_url(), follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("/login?from=")
    # The whole authorize URL, query included, must survive so the hub handoff
    # resumes rather than dumping the user on the dashboard.
    assert "response_type%3Dcode" in location
    assert "state%3Dxyz" in location


@pytest.mark.asyncio
async def test_expired_token_is_treated_as_signed_out(client: AsyncClient) -> None:
    client.cookies.set("session_token", "not-a-real-jwt")
    response = await client.get(_authorize_url(), follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("/login?from=")


@pytest.mark.asyncio
async def test_inactive_account_gets_403_not_a_login_loop(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    A disabled account can sign in perfectly well and would land right back
    here, so redirecting it to /login would loop forever. It must stay a 403.
    """
    settings = get_settings()
    user = User(
        email="pending@udst.edu.qa",
        full_name="Pending Person",
        role="student",
        status=UserStatus.pending,
        password_hash="x",
        credit_balance=0,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()

    token = create_access_token(subject=user.id, settings=settings)
    client.cookies.set("session_token", token)

    response = await client.get(_authorize_url(), follow_redirects=False)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_signed_in_user_still_gets_a_code(
    client: AsyncClient, active_user: User
) -> None:
    """The working path must be unchanged by the optional-user dependency."""
    settings = get_settings()
    token = create_access_token(subject=active_user.id, settings=settings)
    client.cookies.set("session_token", token)

    response = await client.get(_authorize_url(), follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://example.test/hub/oauth_callback")
    assert "code=" in location
    assert "state=xyz" in location
