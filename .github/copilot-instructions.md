# Repository Instructions

Canonical source: [`AGENTS.md`](../AGENTS.md).

If any instruction in this file conflicts with `AGENTS.md`, follow `AGENTS.md`.

## Core Rules

- Respect directory boundaries:
  - Backend: `src/`, `data_provider/`, `api/`, `bot/`
  - Web: `apps/dsa-web/`
  - Desktop: `apps/dsa-desktop/`
  - Deployment/workflows: `scripts/`, `.github/workflows/`, `docker/`
- Commit, push, open the PR, and merge it without asking once the relevant local validation passes, all required CI checks are green, and the PR has no conflicts or blocking review; then delete the working branch. Stop and ask on failing tests or CI, long-pending checks, merge conflicts, unexpected files or secrets in the diff, or destructive operations outside the working branch. Never bypass required checks or branch protection, never merge on red, pending, or unknown checks, never force-push, and always ask before `git tag`.
- Before creating/updating PRs, PR review, or issue analysis, refresh the latest code baseline with `git fetch --all --prune`; if the worktree is clean and the current branch can fast-forward, run `git pull --ff-only`. If local changes, conflicts, missing upstream, or non-fast-forward history make that unsafe, do not stash/reset/overwrite local state; analyze against fetched remote refs or record the baseline gap before proceeding.
- PR titles should use `<type>: <change summary>` such as `fix: restore lost market-review analysis history`; use `fix`/`feat`/`refactor`/`docs`/`chore`/`test`/`ci` where possible, and avoid `[codex]`, `codex`, `autocode`, `copilot`, or other tool/agent source prefixes. Treat this as process guidance and do not use title format mismatches as a hard review blocker.
- Do not hardcode secrets, accounts, ports, model names, absolute environment-specific paths, or environment-specific branches.
- Reuse existing modules, configuration entrypoints, scripts, and tests instead of adding parallel implementations.
- For user-visible behavior changes, CLI/API changes, deployment changes, notification changes, or report-structure changes, update the relevant docs and `docs/CHANGELOG.md`.
- In `docs/CHANGELOG.md`, the `[Unreleased]` section uses a **flat format**: one line per entry formatted as `- [type] description`, where type is one of `feat`/`improve`/`fix`/`docs`/`test`/`chore`. **Do not add `### category headers` inside `[Unreleased]`** to minimize merge conflicts in concurrent PRs. A maintainer will reorganize into the full categorized format at release time. Entries written before 2026-09-19 use the historical Chinese type tokens; leave them as they are.
- Explanatory text in source comments and docstrings must be **English, and English only**. When translating an existing comment, replace it outright: do not keep a bilingual pair, and do not add new non-English explanatory text.
- Exception (required for localization): **quoted literals** inside comments and docstrings are kept verbatim and not translated — localized labels and report copy, language-map keys and values, example inputs, stock and sector names, identifiers, and field names. In short: prose in English, quoted literals as-is.
- Runtime copy is English-only: logs, exception and error messages, notification content, report text and UI copy are English, and `REPORT_LANGUAGE` accepts only `en`. The Chinese and Korean report languages are retired and their code is being removed; do not add new zh/ko copy. Exceptions until replaced on purpose: the Chinese text inside LLM prompts and strategy instructions, and the Chinese aliases and display names in `strategies/*.yaml`.
- Use `README.md` only for project positioning, high-level capabilities, quick start, main entrypoints, and sponsorship/cooperation information; avoid updating README unless the change is homepage-level.
- Put detailed module behavior, page interaction, topic configuration, troubleshooting, field contracts, implementation semantics, and edge cases in the appropriate `docs/*.md` file instead of README.
- When config semantics change, sync `.env.example` and assess impact on local runs, Docker, GitHub Actions, API, Web, and Desktop.

## Validation

- Backend changes: prefer `./scripts/ci_gate.sh`; at minimum run `python -m py_compile` on changed Python files and the closest deterministic tests.
- Web changes: run `cd apps/dsa-web && npm ci && npm run lint && npm run build`.
- Desktop changes: build web first, then desktop if feasible.
- Review work should prioritize CI evidence (`gh pr checks`, workflow logs) before re-running local validation.
- AI governance changes: run `python scripts/check_ai_assets.py`.

## AI Asset Governance

- `AGENTS.md` is the single source of truth for repository AI collaboration rules.
- `CLAUDE.md` must remain a symlink to `AGENTS.md`.
- Use `.github/instructions/*.instructions.md` for path-specific guidance.
- Current repository collaboration skills live in `.claude/skills/`; keep them aligned with `AGENTS.md`.
