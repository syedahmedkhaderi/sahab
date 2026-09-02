# Sahab — Operations Runbook

Day-2 operations, incident response, and the acceptance checks.

## Health checks

```bash
docker compose -f infra/docker-compose.yml ps                 # all services up?
docker compose -f infra/docker-compose.yml logs -f backend    # API logs
docker compose -f infra/docker-compose.yml logs -f worker     # metering/scheduler ticks
curl -fsS http://localhost/api/health                          # backend liveness
nvidia-smi                                                     # host GPU view
```

Grafana: `http://<host>:3001` (or behind Traefik). Dashboards: GPU utilization per device, active sessions, queue depth, credits burned/hr, host health.

## Common operations

### Grant credits
Admin console → Users → Grant, or `POST /api/admin/users/{id}/credits`. Writes a positive ledger entry; balance cache updates.

### Force-stop a session
Admin console → Sessions → Stop, or `POST /api/admin/sessions/{id}/stop`. Releases the GPU lease, writes the final debit, triggers the queue check.

### Add / rotate an image
Build + smoke-test (`scripts/build_images.sh`), then enable via admin. Disable a bad image with `enabled=false` — it stays for history but can't be launched.

### Re-seed GPU inventory (after hardware change)
Re-run the join command on that machine — it re-reports its GPUs and the
inventory is reconciled. A card that stops being reported is marked `disabled`
rather than deleted, because lease history refers to it.

### Take a GPU server out of service
Admin console → VMs → drain (the pause icon). Running sessions finish; nothing
new is placed there. Once it is empty, remove it. Never delete a machine with
live sessions — the console refuses, and forcing it would strand their leases.

### A GPU server has died
The worker notices within a minute and marks it `unreachable`. After the grace
period (`NODE_UNREACHABLE_GRACE_SECONDS`, 5 minutes) its sessions are failed,
their leases released, and its GPUs taken out of the pool. Nothing to do by
hand. When it comes back the node returns to `ready` and its GPUs rejoin the
pool, except any still holding an open lease.

## Incident playbooks

| Symptom | Likely cause | Action |
|---|---|---|
| Session stuck in `starting` | Hub spawn timeout / image pull | Check hub logs; `failed` must release the lease — verify GPU returned to `free` in `gpu_inventory`. |
| GPU shows `leased` but no session | Crash between lease and spawn | Reconcile: close orphan lease, set GPU `free`, re-run queue drain. |
| Credits not deducting | Worker not ticking | `docker compose logs worker`; alert "metering worker not ticking" should fire. Restart worker. |
| GPU pinned at 100% with no notebook activity | Possible mining / runaway job | Cross-ref DCGM busy vs kernel activity; warn user; admin force-stop per AUP. |
| A machine stays `pending` after the join command ran | The script failed before enrolling | Read the install log (Admin → VMs, SSH path) or the script's output on the machine. Re-run the command; it is idempotent. |
| A machine reaches `enrolling` but never `ready` | The manager cannot reach its Docker API on 2376 | The 502 from `/api/nodes/enroll/complete` names the address it tried. Check the firewall between the machines, then `journalctl -u docker` on the node. |
| Workspaces fail on a new machine with an image error | It cannot pull from the private registry | Check `/etc/docker/certs.d/<registry>/ca.crt` exists on that machine, and that the registry answers on port 5000 from it. |
| A user asks where their notebooks went | Storage is session-scoped by design | Files live only for the session; there is no recovery. This is stated on the launch form, in the workspace, and on the stop confirmation. |

## Known dead code

`/verify` (`frontend/app/verify/page.tsx`) calls `POST /api/auth/verify`, which
no router serves. Nothing sends a verification email either — signup is gated by
admin approval (`REQUIRE_ADMIN_APPROVAL`), not by email confirmation — so the
page is unreachable except by typing the URL, and can only ever show an error.
Either build email verification or delete the page; leaving it is the worst of
the three.
| User can't log into workspace | OAuth/cookie/domain mismatch | Confirm single parent domain; check `OAUTH_CLIENT_*` and hub authenticator config. |
| All GPUs busy, third user waiting | Expected | User is queued (visible position) or took CPU now; auto-promoted when a GPU frees. |

## Acceptance criteria (blueprint §22) — run before declaring a phase done

- **Concurrency:** two simultaneous GPU sessions pin distinct L4s; a third queues or falls back to CPU and is auto-promoted on free. Hammer `POST /api/sessions` — no double-allocation.
- **Metering accuracy:** hold a GPU a known duration; debited credits match within one minute; auto-stop at zero balance.
- **Persistence:** restart the whole stack; user files and balances intact.
- **Security:** user container cannot reach Postgres, the hub admin port, or another user's container; no Docker socket inside user containers; quotas/limits enforced.
- **Idle/time limits:** idle session culled (45 min default); session over max duration (240 min default) stopped.
- **Auth:** only allowed-domain emails can sign up; admin endpoints reject non-admins.

## Backups

Nightly `pg_dump` of the `sahab` database (credits + ledger are irreplaceable). Snapshot per-user volumes per your retention policy.

## Alerts to wire (Prometheus/Grafana)

GPU stuck at 100% with no session activity; GPU temp/power thresholds; disk filling; a session exceeding its time limit; metering worker not ticking.
