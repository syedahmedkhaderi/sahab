"""Tests for multi-machine placement.

The thing worth protecting here is one invariant: a GPU is only ever handed out
together with the machine it is in, and only from a machine that is accepting
work. Get that wrong and a user gets a workspace that cannot start, with a GPU
UUID that means nothing on the host it was started on.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import fakeredis.aioredis as fakeredis
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    EnrollmentStatus,
    GpuInventory,
    GpuStatus,
    Node,
    NodeStatus,
    ResourceType,
    Session,
    SessionState,
    User,
)
from app.services import gpu_probe, node_certs
from app.services import node_health as health_svc
from app.services import nodes as nodes_svc
from app.services import scheduler as scheduler_svc


async def _make_session(db: AsyncSession, user_id: str) -> Session:
    session = Session(
        user_id=user_id,
        resource_type=ResourceType.l4_gpu,
        state=SessionState.requested,
    )
    db.add(session)
    await db.flush()
    return session


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lease_carries_the_machine(
    db_session: AsyncSession,
    active_user: User,
    manager_node: Node,
    gpu_inventory: list[GpuInventory],
) -> None:
    """A lease names both the GPU and the machine it is in."""
    redis = fakeredis.FakeRedis()
    session = await _make_session(db_session, active_user.id)

    lease = await scheduler_svc.try_lease_gpu(session.id, db_session, redis)

    assert lease is not None
    assert lease.node_name == manager_node.name
    assert lease.node_id == manager_node.id
    await redis.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [NodeStatus.draining, NodeStatus.unreachable, NodeStatus.disabled, NodeStatus.pending],
)
async def test_no_placement_on_a_machine_that_is_not_ready(
    db_session: AsyncSession,
    active_user: User,
    manager_node: Node,
    gpu_inventory: list[GpuInventory],
    status: NodeStatus,
) -> None:
    """Only a 'ready' machine takes new work — draining included.

    Draining is the important one: its GPUs may still read as free, because its
    running sessions have not finished yet. Placing on it would defeat the point
    of draining a machine before taking it away.
    """
    redis = fakeredis.FakeRedis()
    manager_node.status = status
    await db_session.flush()
    session = await _make_session(db_session, active_user.id)

    lease = await scheduler_svc.try_lease_gpu(session.id, db_session, redis)

    assert lease is None
    await redis.aclose()


@pytest.mark.asyncio
async def test_placement_moves_to_the_other_machine(
    db_session: AsyncSession,
    active_user: User,
    manager_node: Node,
    worker_node: Node,
    gpu_inventory: list[GpuInventory],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Draining one machine sends the next workspace to the other."""
    redis = fakeredis.FakeRedis()

    db_session.add(
        GpuInventory(
            gpu_uuid="GPU-on-the-worker",
            node_id=worker_node.id,
            model="NVIDIA L4",
            vram_mb=24576,
            status=GpuStatus.free,
        )
    )
    manager_node.status = NodeStatus.draining
    await db_session.flush()

    async def no_probe(_url: str):
        return None

    monkeypatch.setattr(gpu_probe, "get_gpu_readings", no_probe)
    session = await _make_session(db_session, active_user.id)

    lease = await scheduler_svc.try_lease_gpu(session.id, db_session, redis)

    assert lease is not None
    assert lease.gpu_uuid == "GPU-on-the-worker"
    assert lease.node_name == worker_node.name
    await redis.aclose()


@pytest.mark.asyncio
async def test_each_machine_is_probed_at_its_own_url(
    db_session: AsyncSession,
    active_user: User,
    manager_node: Node,
    worker_node: Node,
    gpu_inventory: list[GpuInventory],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two machines mean two exporters, not one shared reading.

    Reading the manager's numbers for the worker's cards is exactly how a busy
    GPU gets handed out, so the scheduler must scrape each machine separately.
    """
    redis = fakeredis.FakeRedis()
    db_session.add(
        GpuInventory(
            gpu_uuid="GPU-on-the-worker",
            node_id=worker_node.id,
            model="NVIDIA L4",
            vram_mb=24576,
            status=GpuStatus.free,
        )
    )
    await db_session.flush()

    scraped: list[str] = []

    async def per_node(url: str):
        scraped.append(url)
        if url == worker_node.metrics_url:
            # The worker's card is idle; both of the manager's are busy.
            return {"GPU-on-the-worker": gpu_probe.GpuReading(util_pct=0, used_mb=10)}
        return {
            gpu.gpu_uuid: gpu_probe.GpuReading(util_pct=95, used_mb=20000)
            for gpu in gpu_inventory
        }

    monkeypatch.setattr(gpu_probe, "get_gpu_readings", per_node)
    session = await _make_session(db_session, active_user.id)

    lease = await scheduler_svc.try_lease_gpu(session.id, db_session, redis)

    assert lease is not None
    assert lease.gpu_uuid == "GPU-on-the-worker"
    assert worker_node.metrics_url in scraped
    assert get_settings().dcgm_metrics_url in scraped
    await redis.aclose()


@pytest.mark.asyncio
async def test_a_confirmed_idle_gpu_beats_an_unprobed_one(
    db_session: AsyncSession,
    active_user: User,
    manager_node: Node,
    worker_node: Node,
    gpu_inventory: list[GpuInventory],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A machine whose probe is down stays usable, but ranks last.

    The old behaviour — fail open — is preserved: a monitoring outage must never
    block a launch. It just should not be *preferred* over a card we can see is
    genuinely idle.
    """
    redis = fakeredis.FakeRedis()
    db_session.add(
        GpuInventory(
            gpu_uuid="GPU-on-the-worker",
            node_id=worker_node.id,
            model="NVIDIA L4",
            vram_mb=24576,
            status=GpuStatus.free,
        )
    )
    await db_session.flush()

    async def worker_probe_down(url: str):
        if url == worker_node.metrics_url:
            return None
        return {
            gpu.gpu_uuid: gpu_probe.GpuReading(util_pct=0, used_mb=5)
            for gpu in gpu_inventory
        }

    monkeypatch.setattr(gpu_probe, "get_gpu_readings", worker_probe_down)
    session = await _make_session(db_session, active_user.id)

    lease = await scheduler_svc.try_lease_gpu(session.id, db_session, redis)

    assert lease is not None
    assert lease.node_name == manager_node.name
    await redis.aclose()


# ---------------------------------------------------------------------------
# The probe cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_cache_is_keyed_by_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """One machine's readings must never be served for another's.

    A single shared cache slot was the original shape, and with two machines it
    would silently answer questions about node B with node A's numbers.
    """
    gpu_probe.reset_cache()

    bodies = {
        "http://a:9400/metrics": 'DCGM_FI_DEV_GPU_UTIL{UUID="GPU-a"} 5\n'
                                 'DCGM_FI_DEV_FB_USED{UUID="GPU-a"} 100\n',
        "http://b:9400/metrics": 'DCGM_FI_DEV_GPU_UTIL{UUID="GPU-b"} 90\n'
                                 'DCGM_FI_DEV_FB_USED{UUID="GPU-b"} 20000\n',
    }

    class _Response:
        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            return None

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def get(self, url: str):
            return _Response(bodies[url])

    monkeypatch.setattr(gpu_probe.httpx, "AsyncClient", _Client)

    a = await gpu_probe.get_gpu_readings("http://a:9400/metrics")
    b = await gpu_probe.get_gpu_readings("http://b:9400/metrics")

    assert a is not None and "GPU-a" in a
    assert b is not None and "GPU-b" in b
    assert "GPU-a" not in b

    gpu_probe.reset_cache()


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrollment_token_is_single_use_and_never_stored(
    db_session: AsyncSession, worker_node: Node, admin_user: User
) -> None:
    token, enrollment = await nodes_svc.create_enrollment(db_session, worker_node, admin_user.id)

    # Only the hash is kept: a database dump must not hand over the ability to
    # add machines to the cluster.
    assert token not in enrollment.token_hash
    assert len(enrollment.token_hash) == 64

    resolved, node = await nodes_svc.resolve_enrollment(db_session, token)
    assert node.id == worker_node.id

    resolved.status = EnrollmentStatus.completed
    await db_session.flush()
    with pytest.raises(nodes_svc.NodeError):
        await nodes_svc.resolve_enrollment(db_session, token)


@pytest.mark.asyncio
async def test_expired_token_is_refused(
    db_session: AsyncSession, worker_node: Node, admin_user: User
) -> None:
    token, enrollment = await nodes_svc.create_enrollment(db_session, worker_node, admin_user.id)
    enrollment.expires_at = datetime.now(tz=timezone.utc) - timedelta(minutes=1)
    await db_session.flush()

    with pytest.raises(nodes_svc.NodeError):
        await nodes_svc.resolve_enrollment(db_session, token)


@pytest.mark.asyncio
async def test_unknown_token_is_refused(db_session: AsyncSession) -> None:
    with pytest.raises(nodes_svc.NodeError):
        await nodes_svc.resolve_enrollment(db_session, "not-a-real-token")


@pytest.mark.asyncio
async def test_gpus_are_registered_against_their_machine(
    db_session: AsyncSession, worker_node: Node
) -> None:
    added, updated = await nodes_svc.sync_node_gpus(
        db_session,
        worker_node,
        [
            {"gpu_uuid": "GPU-new-1", "model": "NVIDIA L4", "vram_mb": 23034},
            {"gpu_uuid": "GPU-new-2", "model": "NVIDIA L4", "vram_mb": 23034},
        ],
    )

    assert (added, updated) == (2, 0)
    rows = (
        await db_session.execute(
            select(GpuInventory).where(GpuInventory.node_id == worker_node.id)
        )
    ).scalars().all()
    assert {row.gpu_uuid for row in rows} == {"GPU-new-1", "GPU-new-2"}
    assert all(row.status == GpuStatus.free for row in rows)


@pytest.mark.asyncio
async def test_an_empty_gpu_report_disables_nothing(
    db_session: AsyncSession, worker_node: Node
) -> None:
    """A machine reporting no GPUs means nvidia-smi failed, not that the cards left.

    Treating it as "the GPUs are gone" would empty the pool on every driver
    hiccup, which is much more common than a card actually being removed.
    """
    await nodes_svc.sync_node_gpus(
        db_session, worker_node, [{"gpu_uuid": "GPU-still-here", "model": "L4", "vram_mb": 1}]
    )

    await nodes_svc.sync_node_gpus(db_session, worker_node, [])

    gpu = (
        await db_session.execute(
            select(GpuInventory).where(GpuInventory.gpu_uuid == "GPU-still-here")
        )
    ).scalar_one()
    assert gpu.status == GpuStatus.free


@pytest.mark.asyncio
async def test_reported_gpus_round_trip(
    db_session: AsyncSession, worker_node: Node, admin_user: User
) -> None:
    """A machine's GPU list is stashed at /enroll and used at /enroll/complete."""
    _token, enrollment = await nodes_svc.create_enrollment(db_session, worker_node, admin_user.id)
    payload = [{"gpu_uuid": "GPU-x", "model": "NVIDIA L4", "vram_mb": 23034}]

    await nodes_svc.stash_reported_gpus(db_session, enrollment, payload)
    assert json.loads(enrollment.reported_gpus) == payload
    assert await nodes_svc.take_reported_gpus(db_session, enrollment) == payload


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_dead_machine_frees_what_it_held(
    db_session: AsyncSession,
    active_user: User,
    worker_node: Node,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A machine gone past the grace period stops holding a GPU hostage."""
    redis = fakeredis.FakeRedis()
    settings = get_settings()

    gpu = GpuInventory(
        gpu_uuid="GPU-stranded",
        node_id=worker_node.id,
        model="NVIDIA L4",
        vram_mb=24576,
        status=GpuStatus.free,
    )
    db_session.add(gpu)
    await db_session.flush()

    session = await _make_session(db_session, active_user.id)
    lease = await scheduler_svc.try_lease_gpu(session.id, db_session, redis)
    assert lease is not None
    session.state = SessionState.running
    session.node_id = worker_node.id
    await db_session.flush()

    # The machine has been unreachable for longer than the grace period.
    async def unreachable(_node):
        return False, "connection refused"

    monkeypatch.setattr(nodes_svc, "ping_node", unreachable)
    worker_node.status = NodeStatus.unreachable
    worker_node.unreachable_since = datetime.now(tz=timezone.utc) - timedelta(
        seconds=settings.node_unreachable_grace_seconds + 60
    )
    await db_session.flush()

    await health_svc.check_all_nodes(db_session, redis, settings)

    await db_session.refresh(session)
    await db_session.refresh(gpu)
    assert session.state == SessionState.failed
    # Out of the pool, not silently back to 'free' where it would be handed out
    # again to someone whose workspace also could not start.
    assert gpu.status == GpuStatus.disabled
    await redis.aclose()


@pytest.mark.asyncio
async def test_a_brief_outage_is_not_treated_as_death(
    db_session: AsyncSession,
    active_user: User,
    worker_node: Node,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dockerd restart must not fail someone's afternoon of work."""
    redis = fakeredis.FakeRedis()
    settings = get_settings()

    gpu = GpuInventory(
        gpu_uuid="GPU-blip",
        node_id=worker_node.id,
        model="NVIDIA L4",
        vram_mb=24576,
        status=GpuStatus.leased,
    )
    db_session.add(gpu)
    session = await _make_session(db_session, active_user.id)
    session.state = SessionState.running
    session.node_id = worker_node.id
    await db_session.flush()

    async def unreachable(_node):
        return False, "connection refused"

    monkeypatch.setattr(nodes_svc, "ping_node", unreachable)

    await health_svc.check_all_nodes(db_session, redis, settings)

    await db_session.refresh(session)
    await db_session.refresh(worker_node)
    assert worker_node.status == NodeStatus.unreachable
    assert session.state == SessionState.running  # still inside the grace period
    await redis.aclose()


@pytest.mark.asyncio
async def test_a_machine_that_never_enrolled_is_not_health_checked(
    db_session: AsyncSession, worker_node: Node, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A machine waiting on its join command is not broken.

    Calling it 'unreachable' tells the admin something is wrong when nothing is,
    and sends them looking for a firewall problem that does not exist.
    """
    redis = fakeredis.FakeRedis()
    worker_node.status = NodeStatus.pending
    worker_node.enrolled_at = None
    await db_session.flush()

    async def unreachable(_node):
        return False, "connection refused"

    monkeypatch.setattr(nodes_svc, "ping_node", unreachable)

    await health_svc.check_all_nodes(db_session, redis, get_settings())

    assert worker_node.status == NodeStatus.pending
    assert worker_node.unreachable_since is None
    await redis.aclose()


@pytest.mark.asyncio
async def test_a_machine_cannot_reach_ready_without_enrolling(
    db_session: AsyncSession, worker_node: Node
) -> None:
    """Enrollment is the only way into the pool.

    Otherwise any Docker daemon answering on that address with a certificate our
    CA trusts would carry the row to 'ready' — a machine in the pool that never
    registered a GPU or agreed to anything.
    """
    worker_node.status = NodeStatus.pending
    worker_node.enrolled_at = None
    await db_session.flush()

    await nodes_svc.record_health(db_session, worker_node, reachable=True, detail="27.0")

    assert worker_node.status == NodeStatus.pending


@pytest.mark.asyncio
async def test_an_admin_disabled_machine_is_left_alone(
    db_session: AsyncSession, worker_node: Node
) -> None:
    """A probe result is not a reason to undo a deliberate admin decision."""
    worker_node.status = NodeStatus.draining
    await db_session.flush()

    await nodes_svc.record_health(db_session, worker_node, reachable=False, detail="down")

    assert worker_node.status == NodeStatus.draining


# ---------------------------------------------------------------------------
# PKI
# ---------------------------------------------------------------------------


def test_issued_certificates_chain_to_the_cluster_ca(tmp_path, monkeypatch) -> None:
    """A node certificate has to be signed by our CA and name the node's IP.

    An IP in a DNS SAN is silently ignored by OpenSSL, and dockerd is verified by
    IP as often as by name — so the split between IP and DNS entries is the part
    worth asserting.
    """
    from cryptography import x509
    from cryptography.x509.oid import NameOID

    monkeypatch.setattr(node_certs, "pki_dir", lambda: tmp_path)
    node_certs.ensure_ca()

    cert_pem, key_pem = node_certs.issue_server_cert("worker-1", ["10.0.0.9", "worker-1"])
    cert = x509.load_pem_x509_certificate(cert_pem.encode())
    ca = x509.load_pem_x509_certificate((tmp_path / "ca.crt").read_bytes())

    assert cert.issuer == ca.subject
    assert cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == "worker-1"
    assert "BEGIN RSA PRIVATE KEY" in key_pem

    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "worker-1" in san.get_values_for_type(x509.DNSName)
    assert str(san.get_values_for_type(x509.IPAddress)[0]) == "10.0.0.9"


def test_the_client_certificate_is_created_once(tmp_path, monkeypatch) -> None:
    """Reissuing it on every call would rotate the identity every node trusts."""
    monkeypatch.setattr(node_certs, "pki_dir", lambda: tmp_path)

    first_cert, _ = node_certs.ensure_client_cert()
    second_cert, _ = node_certs.ensure_client_cert()

    assert first_cert == second_cert


# ---------------------------------------------------------------------------
# The admin endpoints
#
# These go through the real HTTP layer on purpose. The service-level tests above
# all passed while /admin/gpus and /admin/nodes returned 500, because the bug was
# in how the response model was built — which only a request exercises.
# ---------------------------------------------------------------------------


async def _login(client, email: str, password: str) -> dict[str, str]:
    resp = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_admin_gpus_lists_the_machine_each_card_is_in(
    client, admin_user: User, manager_node: Node, gpu_inventory: list[GpuInventory]
) -> None:
    headers = await _login(client, admin_user.email, "adminpassword123")

    resp = await client.get("/api/admin/gpus", headers=headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 2
    assert all(row["node_name"] == manager_node.name for row in body)
    assert all(row["node_id"] == manager_node.id for row in body)


@pytest.mark.asyncio
async def test_admin_nodes_reports_gpu_counts(
    client, admin_user: User, manager_node: Node, gpu_inventory: list[GpuInventory]
) -> None:
    headers = await _login(client, admin_user.email, "adminpassword123")

    resp = await client.get("/api/admin/nodes", headers=headers)

    assert resp.status_code == 200, resp.text
    row = next(n for n in resp.json() if n["name"] == manager_node.name)
    assert row["gpus_total"] == 2
    assert row["gpus_free"] == 2
    assert row["is_manager"] is True
    # The stored SSH secret must never leave the server, encrypted or not.
    assert "ssh_secret_enc" not in row


@pytest.mark.asyncio
async def test_adding_a_machine_returns_a_join_command(
    client, admin_user: User, manager_node: Node
) -> None:
    headers = await _login(client, admin_user.email, "adminpassword123")

    resp = await client.post(
        "/api/admin/nodes", json={"address": "10.0.0.42", "display_name": "Lab 2"},
        headers=headers,
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["enroll_token"]
    assert "join_node.sh" in body["join_command"]
    assert body["enroll_token"] in body["join_command"]
    assert body["node"]["status"] == "pending"


@pytest.mark.asyncio
async def test_checking_a_machine_that_is_not_set_up_says_so(
    client, admin_user: User, worker_node: Node, db_session: AsyncSession
) -> None:
    worker_node.status = NodeStatus.pending
    worker_node.enrolled_at = None
    await db_session.commit()
    headers = await _login(client, admin_user.email, "adminpassword123")

    resp = await client.post(f"/api/admin/nodes/{worker_node.id}/check", headers=headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert "has not been set up yet" in body["detail"]


@pytest.mark.asyncio
async def test_re_adding_a_failed_machine_starts_it_over(
    client, admin_user: User, db_session: AsyncSession
) -> None:
    """A fresh join token means a fresh attempt, and the status must say so.

    Otherwise the admin re-registers a machine and is greeted by 'Unreachable'
    for something nobody has tried yet — and goes hunting for a firewall problem
    that is not there.
    """
    headers = await _login(client, admin_user.email, "adminpassword123")
    first = await client.post(
        "/api/admin/nodes", json={"address": "10.0.0.55"}, headers=headers
    )
    node_id = first.json()["node"]["id"]

    node = await db_session.get(Node, node_id)
    node.status = NodeStatus.unreachable
    node.unreachable_since = datetime.now(tz=timezone.utc)
    await db_session.commit()

    again = await client.post(
        "/api/admin/nodes", json={"address": "10.0.0.55"}, headers=headers
    )

    assert again.status_code == 201, again.text
    assert again.json()["node"]["status"] == "pending"


@pytest.mark.asyncio
async def test_re_adding_an_enrolled_machine_does_not_pull_it_from_the_pool(
    client, admin_user: User, worker_node: Node
) -> None:
    """Re-issuing a token to repair a live machine must not interrupt it."""
    headers = await _login(client, admin_user.email, "adminpassword123")

    resp = await client.post(
        "/api/admin/nodes", json={"address": worker_node.address, "name": worker_node.name},
        headers=headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["node"]["status"] == "ready"


@pytest.mark.asyncio
async def test_a_machine_cannot_be_forced_into_a_system_owned_state(
    client, admin_user: User, worker_node: Node
) -> None:
    """'unreachable' is a conclusion the health check draws, not an admin input."""
    headers = await _login(client, admin_user.email, "adminpassword123")

    resp = await client.patch(
        f"/api/admin/nodes/{worker_node.id}", json={"status": "unreachable"}, headers=headers
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_a_machine_with_gpus_is_not_silently_deleted(
    client, admin_user: User, worker_node: Node, db_session: AsyncSession
) -> None:
    """Deleting it would orphan the lease history the credit ledger refers to."""
    db_session.add(
        GpuInventory(
            gpu_uuid="GPU-keep-me",
            node_id=worker_node.id,
            model="NVIDIA L4",
            vram_mb=24576,
            status=GpuStatus.free,
        )
    )
    await db_session.commit()
    headers = await _login(client, admin_user.email, "adminpassword123")

    resp = await client.delete(f"/api/admin/nodes/{worker_node.id}", headers=headers)

    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_the_control_plane_cannot_remove_itself(
    client, admin_user: User, manager_node: Node
) -> None:
    headers = await _login(client, admin_user.email, "adminpassword123")

    resp = await client.delete(f"/api/admin/nodes/{manager_node.id}", headers=headers)

    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_enrolling_with_a_bad_token_is_refused(client) -> None:
    """The enroll endpoints are reachable without a login, so this is the door."""
    resp = await client.post(
        "/api/nodes/enroll",
        json={"token": "nope", "hostname": "evil", "advertise_addr": "10.0.0.1", "gpus": []},
    )

    assert resp.status_code == 401
