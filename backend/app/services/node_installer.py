"""Run the join script on a new GPU server over SSH.

This is the admin console's "add a VM by IP" path. It deliberately does not do
anything the copy-paste path does not: it opens an SSH session and runs the exact
same one-liner an admin would paste by hand. Keeping one script means the two
ways of adding a machine cannot drift apart, and a failure here is reproducible
by hand with the command from the log.

The install takes several minutes (Docker, the NVIDIA toolkit, image pulls), so
the HTTP request starts it and returns. Output is appended to the enrollment's
log as it arrives, which is what the console polls.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.config import Settings
from app.models import EnrollmentStatus, Node, NodeEnrollment, NodeStatus
from app.services import nodes as nodes_svc
from app.services.crypto import SecretDecryptError, decrypt

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_SECONDS = 30
# Generous: a cold machine downloads Docker, the NVIDIA toolkit and a CUDA image.
INSTALL_TIMEOUT_SECONDS = 45 * 60

# Tracks the installs this process started, so a second click does not run the
# script twice on one machine at the same time.
_running: dict[str, asyncio.Task] = {}


async def start_install(
    *,
    node_id: str,
    enrollment_id: str,
    token: str,
    vpn_auth_key: str | None,
    settings: Settings,
) -> None:
    """Kick off the remote install in the background."""
    existing = _running.get(node_id)
    if existing is not None and not existing.done():
        logger.info("Install already running for node %s; not starting another", node_id)
        return

    task = asyncio.create_task(
        _run_install(
            node_id=node_id,
            enrollment_id=enrollment_id,
            token=token,
            vpn_auth_key=vpn_auth_key,
            settings=settings,
        )
    )
    _running[node_id] = task
    task.add_done_callback(lambda _t: _running.pop(node_id, None))


def build_command(token: str, settings: Settings, vpn_auth_key: str | None) -> str:
    """The command to run on the remote machine.

    Identical to what the console shows for the copy-paste path, plus the VPN
    flag when the machine is not on this network.
    """
    command = nodes_svc.join_command(token, settings)
    if vpn_auth_key:
        command += f" --vpn tailscale --vpn-key {vpn_auth_key}"
    return command


def _redact(text: str, secrets: list[str]) -> str:
    """Keep tokens and keys out of a log the console will display."""
    for secret in secrets:
        if secret and len(secret) > 6:
            text = text.replace(secret, "…redacted…")
    return text


async def _run_install(
    *,
    node_id: str,
    enrollment_id: str,
    token: str,
    vpn_auth_key: str | None,
    settings: Settings,
) -> None:
    # Imported here so the module loads (and the app starts) even if asyncssh is
    # missing from an older image — only this one feature would be unavailable.
    import asyncssh  # noqa: PLC0415

    from app.db import AsyncSessionLocal  # noqa: PLC0415

    secrets_to_redact = [token, vpn_auth_key or ""]

    async with AsyncSessionLocal() as db:
        node = await db.get(Node, node_id)
        enrollment = await db.get(NodeEnrollment, enrollment_id)
        if node is None or enrollment is None:
            logger.warning("Install aborted: node or enrollment vanished")
            return

        async def log(text: str) -> None:
            await nodes_svc.append_log(db, enrollment, _redact(text, secrets_to_redact))
            await db.commit()

        try:
            secret = decrypt(node.ssh_secret_enc or "")
        except SecretDecryptError as exc:
            await log(f"\n[fail] {exc}\n")
            enrollment.status = EnrollmentStatus.failed
            node.status = NodeStatus.pending
            await db.commit()
            return

        auth_kind = str(getattr(node.ssh_auth_kind, "value", node.ssh_auth_kind) or "password")
        connect_kwargs: dict = {
            "host": node.ssh_host,
            "port": node.ssh_port,
            "username": node.ssh_user,
            "connect_timeout": CONNECT_TIMEOUT_SECONDS,
            # The machine is new and its host key has never been seen. Recording
            # it on first contact is the same trust model as `ssh` with
            # StrictHostKeyChecking=accept-new, and is the practical choice for a
            # private LAN — noted in docs/deployment.md.
            "known_hosts": None,
        }
        if auth_kind == "key":
            try:
                connect_kwargs["client_keys"] = [asyncssh.import_private_key(secret)]
            except Exception as exc:  # noqa: BLE001 — a bad key is user input
                await log(f"\n[fail] That private key could not be read: {exc}\n")
                enrollment.status = EnrollmentStatus.failed
                node.status = NodeStatus.pending
                await db.commit()
                return
        else:
            connect_kwargs["password"] = secret

        command = build_command(token, settings, vpn_auth_key)
        # sudo -S reads the password from stdin, so this works on a machine whose
        # sudo asks for one. On a passwordless-sudo host the extra line is
        # harmless: sudo never prompts, and the line is consumed by the script.
        remote = f"sudo -S -p '' bash -lc {_shell_quote(command)}"

        await log(
            f"[{_now()}] Connecting to {node.ssh_user}@{node.ssh_host}:{node.ssh_port}\n"
            f"[{_now()}] Running: {_redact(command, secrets_to_redact)}\n"
        )

        try:
            async with asyncssh.connect(**connect_kwargs) as conn:
                await log(f"[{_now()}] Connected. This takes several minutes.\n")
                process = await conn.create_process(remote, stderr=asyncssh.STDOUT)
                if auth_kind == "password":
                    process.stdin.write(secret + "\n")

                try:
                    async with asyncio.timeout(INSTALL_TIMEOUT_SECONDS):
                        async for line in process.stdout:
                            await log(line)
                except TimeoutError:
                    process.terminate()
                    raise

                result = await process.wait()
                if result.exit_status == 0:
                    await log(f"\n[{_now()}] Install finished.\n")
                    # Status is not set to 'ready' here: /enroll/complete decides
                    # that, after proving the Docker API actually answers.
                else:
                    await log(
                        f"\n[fail] The join script exited with status "
                        f"{result.exit_status}. The output above says why.\n"
                    )
                    enrollment.status = EnrollmentStatus.failed
                    node.status = NodeStatus.pending
                    await db.commit()

        except asyncssh.PermissionDenied:
            await log(
                "\n[fail] SSH refused those credentials. Check the username and "
                "password or key.\n"
            )
            enrollment.status = EnrollmentStatus.failed
            node.status = NodeStatus.pending
            await db.commit()
        except TimeoutError:
            await log(
                f"\n[fail] The install did not finish within "
                f"{INSTALL_TIMEOUT_SECONDS // 60} minutes and was stopped.\n"
            )
            enrollment.status = EnrollmentStatus.failed
            node.status = NodeStatus.pending
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — surface whatever went wrong
            logger.exception("Remote install failed for node %s", node_id)
            await log(f"\n[fail] {type(exc).__name__}: {exc}\n")
            enrollment.status = EnrollmentStatus.failed
            node.status = NodeStatus.pending
            await db.commit()


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%H:%M:%S")


def _shell_quote(value: str) -> str:
    """Single-quote a string for a POSIX shell."""
    return "'" + value.replace("'", "'\\''") + "'"
