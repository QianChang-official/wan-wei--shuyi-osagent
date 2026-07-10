# Dependency Governance

This repository uses alerting and CI for dependency risk detection, but dependency
upgrade pull requests are created and reviewed by humans. Automated version-update
pull requests and automated security-update pull requests are intentionally
disabled to avoid unreviewed major-version churn and excessive CI/reviewer load.

## Detection That Remains Enabled

- GitHub dependency graph and Dependabot vulnerability alerts
- `pip-audit` for backend runtime and development requirements
- `npm audit --audit-level=high` for the frontend lockfile
- pull-request dependency review for newly introduced vulnerable dependencies
- CodeQL for Python and JavaScript/TypeScript
- Trivy scanning of the built container image
- GitHub secret scanning and push protection

Disabling automated pull requests does not disable these alerts or checks.

## Upgrade Policy

1. Review vulnerability alerts and scheduled audit results before routine upgrades.
2. Create one human-owned pull request per ecosystem and compatibility boundary.
3. Prefer the smallest supported upgrade that resolves the risk or maintenance need.
4. Treat runtime, framework, compiler, build-tool, router, and GitHub Action major
   versions as migrations; review release notes and breaking changes before editing.
5. Keep `frontend/console-vue/package-lock.json` synchronized with `package.json`.
6. Preserve the canonical Node `20.20.2` frontend build until an explicit runtime
   migration validates local builds, CI, Docker, and committed `dist` output.
7. Preserve Python 3.10 and 3.12 CI support until an explicit compatibility change
   updates documentation, containers, and the test matrix together.
8. Never auto-merge dependency changes, even when checks are green.

## Required Validation

Every dependency-upgrade pull request must document the release notes reviewed,
compatibility risks, files changed, and validation performed. At minimum run:

```powershell
.\scripts\verify.ps1 -SkipInstall -IncludeArena
```

The pull request must also pass the repository CI and Security workflows. Container
base-image or action upgrades require the hardened container smoke and security
scan. Frontend toolchain upgrades require two deterministic production builds and
no uncommitted change under `frontend/console-vue/dist`.

## Vulnerability Response

For a confirmed vulnerability, assess reachability and severity first. Patch or
upgrade on a dedicated branch, add a regression test when behavior is reachable,
and use an emergency pull request only when the normal full validation cannot meet
the remediation deadline. Record any temporarily accepted risk with an owner,
rationale, compensating controls, and review date; do not dismiss alerts merely to
make dashboards green.
