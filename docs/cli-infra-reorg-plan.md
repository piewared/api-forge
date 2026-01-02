# CLI/Infra Re-Org Plan

## Goals
- Preserve behavior while improving readability, testability, and maintainability.
- Favor dependency injection and single-responsibility functions.
- Reduce duplication across CLI commands and deployment workflows.
- Keep CLI as source of truth; infra/docker is canonical container source.
- Keep Helm files generated at deploy time from docker sources.

## Scope
- In scope: `src/cli/**`, `infra/**`.
- Out of scope: application runtime outside CLI, config loader, runtime services, API code.

## Constraints
- No network access required.
- Use CLI for orchestration; infra scripts are helpers where needed.
- Keep backward-compatible commands where feasible.

## Baseline Tests (added before changes)
- Unit tests under `tests/unit/cli` to lock in existing behavior for:
  - Connection string parsing/merging in `src/cli/commands/db_utils.py`.
  - Compose command construction helpers (to be introduced) and/or existing command utilities.
  - Error handling wrappers in `src/cli/shared/console.py`.

## Phases

### Phase 1: Hygiene and Dependency Cleanup
**Intent:** Eliminate dead code and tighten imports without behavior change.
- Remove dead module: `src/cli/shared/helpers.py` (commented-out stub).
- Fix import cycle: `src/cli/deployment/status_display.py` should import `CLIConsole` from `src/cli/shared/console.py`.
- Normalize dev cleanup script: rewrite `infra/docker/dev/cleanup_dev.sh` into a single script.
- De-duplicate unused scripts: drop `infra/scripts/entrypoint.sh` if not referenced.

**Verification:** run `tests/unit/cli`.

### Phase 2: CLI Context & DI
**Intent:** Centralize runtime dependencies for better testability.
- Introduce `src/cli/context.py` with a `CLIContext` (console, project_root, shell commands, k8s controller).
- Add Typer callback in `src/cli/__init__.py` to attach context.
- Remove module-level globals in `src/cli/commands/k8s.py` and `src/cli/commands/k8s_db.py`; pull from context.

**Verification:** run `tests/unit/cli`.

### Phase 3: Compose Runner + Command Slimming
**Intent:** Replace ad-hoc subprocess calls with shared helpers.
- Add `src/cli/shared/compose.py` (or `src/cli/deployment/compose.py`) with helper methods for compose invocations.
- Refactor `src/cli/commands/dev.py` and `src/cli/commands/prod.py` to use the compose helper.
- Normalize service maps in one place.

**Verification:** run `tests/unit/cli`.

### Phase 4: DB Workflow Consolidation
**Intent:** DRY up prod/k8s DB commands.
- Add `src/cli/commands/db/` package:
  - `runtime.py` (protocol/adapter interface)
  - `runtime_compose.py`
  - `runtime_k8s.py`
  - `workflows.py` (shared flows: create/init/verify/sync/backup/reset/status/migrate)
- Convert `src/cli/commands/prod_db.py` and `src/cli/commands/k8s_db.py` into thin CLI wrappers.

**Verification:** run `tests/unit/cli`.

### Phase 5: Deployer Base Consolidation
**Intent:** Remove duplication across deployers.
- Move shared data subdir list to `src/cli/deployment/constants.py`.
- Factor container restart logic into `BaseDeployer`.
- Expose public helper for ensuring data directories (avoid private access).

**Verification:** run `tests/unit/cli`.

### Phase 6: Infra Consistency
**Intent:** Ensure single source of truth for deployment artifacts.
- Keep docker sources canonical; ensure `ConfigSynchronizer` only copies from `infra/docker/prod`.
- Remove unused duplicate `verify-init.sh` in `infra/docker/prod/postgres/admin-scripts` or replace with wrapper.
- Fix import order in `infra/docker/dev/keycloak/setup_script.py`.
- Align `infra/docker/dev/setup_dev.sh` to call CLI (or mark as legacy).

**Verification:** run `tests/unit/cli`.

### Phase 7: Entity CLI Split
**Intent:** Shorten and decouple long CLI modules.
- Split `src/cli/commands/entity.py` into `src/cli/commands/entity/` package.
- Add small helper to safely insert/remove router registrations.

**Verification:** run `tests/unit/cli`.

## Milestones & Rollback
- Each phase is independently shippable.
- If a phase breaks tests, revert only the phase’s changes and re-approach with smaller steps.

## Test Command
- `uv run pytest tests/unit/cli`
