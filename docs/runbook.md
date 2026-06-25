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
```bash
scripts/discover_gpus.sh --sql | docker compose --env-file .env -f infra/docker-compose.yml exec -T postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

## Incident playbooks

| Symptom | Likely cause | Action |
|---|---|---|
| Session stuck in `starting` | Hub spawn timeout / image pull | Check hub logs; `failed` must release the lease — verify GPU returned to `free` in `gpu_inventory`. |
| GPU shows `leased` but no session | Crash between lease and spawn | Reconcile: close orphan lease, set GPU `free`, re-run queue drain. |
| Credits not deducting | Worker not ticking | `docker compose logs worker`; alert "metering worker not ticking" should fire. Restart worker. |
| GPU pinned at 100% with no notebook activity | Possible mining / runaway job | Cross-ref DCGM busy vs kernel activity; warn user; admin force-stop per AUP. |
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
