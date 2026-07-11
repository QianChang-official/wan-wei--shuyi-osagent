# Kylin Native SDK Evidence Package

This directory contains the reproducible evidence captured on 2026-07-11 from
the Kylin V11 2603 QEMU/WHPX virtual machine. It contains no passwords, API
keys, private SSH keys, VM disk images, or model binaries.

## Result summary

- Official text embedding SDK: PASS, model
  `ensemble-embd_gte-base_uint8-text`, 768 dimensions.
- Official vector-engine SDK: PASS, native upsert/search/delete.
- Non-keyword retrieval: PASS; the exact FTS query produced zero hits while
  native search ranked the intended Capsule first.
- Forget/delete: PASS; the local transaction completed before native deletion,
  replay was idempotent, lifecycle changed to `forgotten`, FTS rows became zero,
  native vector id 1 changed to `deleted`, and post-forget recall was false.
- History rebuild: PASS; native coverage changed from 0/2 with two pending to
  2/2 with zero failed.
- Warm latency: 30 native HTTP searches, p50 195.320 ms and p95 246.473 ms.
- Crash/concurrency recovery: PASS in host regression; generation fencing,
  per-attempt vector IDs, durable tombstones and the bounded sweeper cover late
  upsert, stale lease takeover, failed compensation and ticket replay windows.
- Pre-review backend snapshot: 207 passed, 1 skipped on the Windows host and
  208 passed with one dependency deprecation warning in the Kylin VM. Final
  post-review source results are regenerated before publication.

## Files

- `environment-and-probe.txt`: OS, repository candidates, installed versions,
  vendor commits, KYSEC trust, service health, and direct Bridge probe.
- `cmake-configure.txt`, `cmake-build.txt`: native Bridge compilation output.
- `sdk-install.txt`, `runtime-upgrade.txt`, `embedding-engine-upgrade.txt`,
  `abstract-models-install.txt`: original package-operation logs.
- `write-*.json`, `semantic-search.json`, `forget-delete.json`,
  `history-*.json`, `latency.json`: raw API and measurement records.
- `backend.log`: FastAPI request log from the acceptance runs.
- `normal-mode-verification.txt`, `normal-mode-api.txt`, `backend-normal.log`:
  package, Bridge, direct probe and API persistence checks after leaving
  maintenance mode and rebooting into normal mode.
- `current-source-normal-mode-build-and-probe.txt`: final normal-mode rebuild
  and direct probe from the exact Bridge source in this worktree.
- `final-current-source-acceptance.json`: pre-review source snapshot write, semantic
  preview, governed forget, native delete, idempotent replay, audit minimization
  and zero-delete-backlog acceptance result.
- `pytest-backend-final-audit-closed-host.txt` and
  `pytest-backend-final-audit-closed-vm.txt`: pre-review source snapshot backend
  suites. The post-review source manifest and rerun logs supersede them before publication.
- `kylin-native-sdk-acceptance.png`: terminal summary captured inside Kylin.
- `kylin-maintenance-mode.png`: maintenance-mode desktop watermark.
- `pytest-backend.txt`: complete backend regression output.
- `SHA256SUMS`: integrity manifest for this evidence package.

The VM database files and vector database files are intentionally excluded:
the JSON responses and command output are sufficient for review, while keeping
runtime data and user state out of the repository.
