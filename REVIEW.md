# Pull Request Review Guidance

Use this file together with the repository's tests and documentation. Review only
the behavior introduced or changed by the pull request. Do not turn pre-existing
debt, speculative redesigns, or cosmetic preferences into blocking findings.

## Project Contract

This repository is an alpha research prototype and competition delivery base for
an OS Agent memory-governance platform. It contains a FastAPI application,
SQLite/FTS5 persistence, a Vue 3 console, offline evaluation fixtures, and a
hardened single-node container path. Preserve the distinction between implemented,
partial, planned, simulated, and measured capabilities.

The numbered 20-cabin product model and its Chinese domain names are intentional.
Do not recommend deleting or renaming them merely for stylistic uniformity.

## Review Scope and Severity

- Report an issue only when the changed code provides concrete evidence of a bug,
  security weakness, data-integrity risk, compatibility regression, misleading
  claim, or missing test for behavior that can fail.
- Include the triggering scenario, impact, and the smallest credible fix direction.
- Treat authentication bypasses, SSRF, SQL injection, secret disclosure, memory or
  audit corruption, unsafe restore behavior, and release-gate bypasses as blocking.
- Treat generated-output drift, cross-platform breakage, unbounded resource use,
  and unsupported delivery claims as blocking when they affect the shipped path.
- Do not block on formatting, naming, or comments unless they hide incorrect or
  unsafe behavior.

## Security Boundaries

- Mutating endpoints and sensitive reads must remain authenticated. Production
  mode must fail closed when `WANWEI_API_KEY` or its secret file is absent, weak,
  or unreadable. Never log, echo, persist, or commit API keys or credentials.
- Keep constant-time API-key comparison and the explicit public-path boundary.
  New sensitive GET endpoints need authentication coverage and negative tests.
- Treat request bodies, imported memory, model output, tool output, and forwarded
  headers as untrusted. Preserve input-size limits, rate limits, provenance,
  quarantine, confirmation, and audit behavior.
- Trust `X-Forwarded-For` only when the immediate peer belongs to the explicit
  trusted-proxy configuration. The default container command intentionally uses
  `--no-proxy-headers`.
- All outbound HTTP(S) targets must pass the central SSRF validator. Reject local,
  private, link-local, multicast, reserved, credential-bearing, and unsafe
  redirect targets. Allowlist exceptions must be exact-host and explicit.
- SQL values must use bound parameters. Any dynamic identifiers, sort fields, FTS
  queries, or `IN` lists must come from validated or code-owned values.
- Frontend changes must not introduce `v-html`, unsafe `innerHTML`, executable
  untrusted markup, or persistent browser storage for secrets.

## Persistence and Memory Integrity

- Preserve per-thread SQLite connection ownership, WAL configuration, bounded
  busy waits, explicit commits, and deterministic teardown used by isolated tests.
- A logical write that touches both a base table and an FTS table must not leave
  them inconsistent on partial failure. Review transaction and rollback behavior,
  lifecycle state transitions, and audit writes together.
- Memory lifecycle changes must preserve provenance, evidence identifiers,
  governance decisions, and the `active`/`quarantined`/`forgotten`/`rejected`
  semantics. High-impact writes must not bypass policy or confirmation gates.
- Backup creation must use SQLite's online backup semantics and integrity checks.
  Restore must verify the SHA-256 manifest, require a stopped writer, and avoid
  replacing the live database before validation succeeds.
- Queries, list endpoints, trace retention, caches, rate-limit buckets, and metrics
  labels must remain bounded. Reject user-controlled high-cardinality metric labels.

## API and Domain Compatibility

- Preserve existing response fields and status meanings unless the pull request
  explicitly documents and tests a breaking change.
- Use timezone-aware UTC timestamps and keep serialization deterministic where
  reports, audits, digests, or golden fixtures depend on it.
- Dry-run endpoints must remain non-mutating. A mock, stub, catalog, proposal,
  lightweight reproduction, or simulated latency must not be presented as real
  execution, training, production readiness, or a full official reproduction.
- Keep model-generation latency separate from OS Agent control-path latency.
  External model calls must be opt-in, bounded by timeouts, and safe against SSRF
  and secret leakage.

## Performance and Evidence

- Look for N+1 query regressions, full-table scans introduced on request paths,
  repeated per-item commits, unbounded loops, and loading entire reports or traces
  into memory. Prefer evidence from query-count or focused regression tests.
- Performance and quality claims must point to reproducible artifacts and state
  dataset size, sample count, hardware/environment, percentile method, and whether
  model generation is excluded. Local SQLite measurements are not proof of Kylin
  SDK performance, large-scale behavior, or production stability.
- Do not accept fabricated, hand-edited, or relabeled benchmark and evaluation
  results. Changed reports must be reproducible from the checked-in runner or have
  a clearly documented external test procedure.

## Frontend and Generated Distribution

- The canonical frontend build uses `npm ci`, Node `20.20.2`, TypeScript, and Vite.
  Source changes that affect the console must include the corresponding committed
  `frontend/console-vue/dist` output.
- The production build must be deterministic: two builds from the same source and
  lockfile must produce the same tree digest, and CI must end with no dist diff.
- Review loading, empty, error, authorization, and narrow-viewport states when a
  UI workflow changes. Do not let dynamic text overlap controls or make primary
  actions unreachable.

## Delivery and Operations

- Preserve Windows PowerShell and Linux/Kylin shell parity for supported scripts.
  Avoid shell-specific assumptions in shared Python and configuration paths.
- The container must remain non-root (`10001:10001`), compatible with a read-only
  root filesystem, dropped capabilities, `no-new-privileges`, and writable data
  only through the documented volume/tmpfs paths.
- Health checks, protected metrics, request IDs, graceful shutdown, backup/restore,
  and smoke tests are part of the delivery surface. Review their failure paths.
- GitHub Actions permissions must stay least-privilege. Dependency upgrades need
  lockfile changes, relevant builds/tests, and review of major-version behavior.
- Do not bypass the public-release preflight. A release remains blocked until the
  owner commits a chosen root `LICENSE` and sets `VERSION_HISTORY[0].status` to
  `released`. Review automation must not choose a license for the owner.

## Expected Validation

Choose checks in proportion to the diff, and flag missing regression coverage for
changed behavior. The complete local delivery checks are:

```powershell
.\scripts\verify.ps1 -SkipInstall -IncludeArena
```

```bash
WANWEI_SKIP_INSTALL=1 WANWEI_INCLUDE_ARENA=1 bash scripts/verify.sh
```

CI additionally covers Python 3.10 and 3.12 on Windows and Linux, the canonical
Node build, HTTP smoke tests, a locked-down container, CodeQL, dependency audit,
dependency review, and image scanning. Documentation-only changes do not need
invented runtime tests, but examples, paths, commands, and stated boundaries must
still be checked against the repository.
