# AGENTS.md

This file defines the default development workflow for this repository. The goal is to reduce repeated discussion, reduce rework, and keep changes consistent with the current project structure.

If this file disagrees with the scripts, workflows, or actual code in the repository, trust what is actually executable, and fix the documentation as part of the related change so the rules stop drifting.

## 1. Hard rules

- Respect the existing directory boundaries:
  - Backend logic belongs in `src/`, `data_provider/`, `api/`, `bot/`
  - Web frontend changes belong in `apps/dsa-web/`
  - Desktop changes belong in `apps/dsa-desktop/`
  - Deployment and pipeline changes belong in `scripts/`, `.github/workflows/`, `docker/`
- Commit, push, open the PR, and merge it without asking once the relevant local validation passes, all required CI checks are green, and the PR has no conflicts or blocking review; then delete the working branch. Stop and ask on failing tests or CI, long-pending checks, merge conflicts, unexpected files or secrets in the diff, or destructive operations outside the working branch. Never bypass required checks or branch protection, never merge on red, pending, or unknown checks, never force-push, and always ask before `git tag`.
- Write commit messages in English, and do not add `Co-Authored-By`.
- Never hardcode secrets, accounts, paths, model names, ports, or environment-specific branching.
- Prefer reusing existing modules, configuration entrypoints, scripts, and tests over adding parallel implementations.
- Stability outranks opportunistic improvement. Refactors, abstractions, and infrastructure migrations that the current task does not directly require should be left alone.
- When adding a configuration option, update `.env.example` and the related documentation in the same change.
- When user-visible capability, CLI/API behaviour, deployment, notification behaviour, or report structure changes, update the related documentation and `docs/CHANGELOG.md`.
- When changing report formatting, report rendering, or the Web UI, the PR description must include screenshots of the affected reports or pages. Prefer before/after comparisons when the change is a visual diff; if a screenshot is impossible, say why and give equivalent visual evidence.
- Screenshots from issue/PR discussion, review screenshots, one-off acceptance screenshots, and other temporary visual evidence must not be committed as repository files. Put them in the PR description, PR comments, GitHub attachments, Actions artifacts, or an externally accessible evidence link. Long-lived product diagrams are the exception, but their filenames and meaning must not depend on a specific issue or PR number.
- The `[Unreleased]` section of `docs/CHANGELOG.md` uses a **flat format**: one entry per line, formatted as `- [type] description`, where type is one of `feat`/`improve`/`fix`/`docs`/`test`/`chore`. **Do not add `### category headings` inside `[Unreleased]`**, so that concurrent PRs produce minimal merge conflicts. At release time a maintainer consolidates entries into the formal categorized format. Entries written before 2026-09-19 use the historical Chinese type tokens; leave them as they are.
- `README.md` is only for project positioning, a high-level capability overview, quick start, main entrypoints, and sponsorship/partnership information. Do not update the README unless the change is homepage-level, so it does not keep growing.
- Finer-grained module behaviour, page interactions, topic-specific configuration, troubleshooting, field contracts, implementation semantics, and edge cases belong in the matching `docs/*.md` or topic document, not the README.
- Explanatory text in source comments and docstrings must be **English, and English only**. When translating an existing comment, replace it outright: do not keep a bilingual pair, and do not add new non-English explanatory text.
- Exception (required for localization): **quoted literals** inside comments and docstrings are kept verbatim and not translated. This covers localized labels and report copy (for example `未纳入新闻面证据`, `强烈买入`), language-map keys and values, example inputs (for example `沪深3000`, `*ST美丽`, `五 粮 液`), stock and sector names, identifiers, and field names. In short: prose in English, quoted literals as-is. Where a docstring's whole subject is the localized values themselves (modules such as `src/report_language.py` and `src/schemas/decision_action.py`), those non-English values may be kept.
- Runtime copy is English-only: logs, exception and error messages, notification content, report text and UI copy are English, and `REPORT_LANGUAGE` accepts only `en`. The Chinese and Korean report languages are retired; their remaining code and translation tables are being removed, so do not add new zh/ko copy or extend them. One deliberate exception stays until replaced on purpose: the Chinese text left in the agent analysis prompts (`AGENT_SYSTEM_PROMPT`, `LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT` in `src/agent/executor.py`), the multi-agent prompts and some agent tool-output labels (translated only after an eval). The analyzer and chat prompts, the default trading policy and every field of `strategies/*.yaml`, `instructions` included, are English (audit A6/A7; guarded by `tests/test_english_model_prompts.py` and `tests/test_strategy_aliases_guard.py`).

## 1.1 PR title convention (advisory, non-blocking)

- Prefer `<type>: <what changed>` as the PR title, for example `fix: restore lost market-review analysis history`. Preferred types are `fix`/`feat`/`refactor`/`docs`/`chore`/`test`/`ci`.
- The title should describe the actual change. Avoid `[codex]`, `codex`, `autocode`, `copilot`, or other tool/agent source prefixes.
- This convention exists for collaborative readability and consistency. It must not be used on its own as a review process blocker.

## 1.2 Contribution quality bar

- This repository does not accept PRs that substitute stacked code volume, an enlarged diff surface, or patch-style responses to review for real design convergence.
- Contribution quality is judged on whether it solves a clearly stated problem, minimizes blast radius, keeps existing contracts consistent, and covers the real risk paths. It is not judged on added lines, file count, feature marketing, or "looking complete".
- Please do not treat this repository as a low-cost sandbox, a resume showcase, or a contribution-farming target. Every PR must demonstrate that the author understands the current system contracts and has done basic self-review, integration, and verification.
- Using AI assistance is not itself a problem. The problem is submitting AI-generated code that has had no human semantic review, no verification, and no convergence. Such PRs are treated as low-quality submissions.
- After review feedback, appending a local patch only at the spot that was called out is not acceptable. The author must re-examine every entrypoint, configuration, test, document, workflow, and user-visible path touched by the same business semantics.
- If a PR keeps producing the same class of problem after multiple review rounds — contract drift, repeated fallbacks, tests that bypass the real risk layer, a PR body that does not match the actual diff — the maintainer may ask for it to be closed and redone rather than continuing point-by-point review.

## 2. AI collaboration asset governance

- `AGENTS.md` is the single source of truth for AI collaboration rules in this repository.
- `CLAUDE.md` must be a symlink pointing to `AGENTS.md`, for compatibility with the Claude ecosystem.
- `.github/copilot-instructions.md` and `.github/instructions/*.instructions.md` are mirrors or layered supplements for GitHub Copilot / Coding Agent. If they conflict with this file, `AGENTS.md` wins.
- Repository collaboration skills live in `.claude/skills/`, and analysis output lives in `.claude/reviews/`. The former may be committed; the latter is treated as a local artifact by default.
- The root `SKILL.md` and `docs/openclaw-skill-integration.md` are product or external-integration documentation, not a source of truth for repository collaboration rules.
- If an `.agents/skills/` directory or any other agent-specific directory is added later, define the single source of truth first and then sync by script or mirror. Maintaining multiple copies of the same content by hand over time is forbidden.
- When changing AI collaboration governance assets, run:

```bash
python scripts/check_ai_assets.py
```

## 3. Repository at a glance

- Project positioning: an intelligent stock analysis system for the US and Canadian markets, in English. Mainland China, Hong Kong, Japan, Korea and Taiwan are not supported (see `docs/market-support.md`).
- Main flow: fetch data -> technical analysis / news retrieval -> LLM analysis -> generate report -> push notification.
- Key entrypoints:
  - `main.py`: main entrypoint for analysis runs
  - `server.py`: FastAPI service entrypoint
  - `apps/dsa-web/`: Web frontend
  - `apps/dsa-desktop/`: Electron desktop app
  - `.github/workflows/`: CI, releases, daily jobs
- Core responsibilities:
  - `src/core/`: main flow orchestration
  - `src/services/`: business service layer
  - `src/repositories/`: data access layer
  - `src/reports/`: report generation
  - `src/schemas/`: schemas / data structures
  - `data_provider/`: multi-source adapters and fallback
  - `api/`: FastAPI API
  - `bot/`: bot integrations
  - `scripts/`: local scripts
  - `.github/scripts/`: GitHub automation scripts
  - `tests/`: pytest tests
  - `docs/`: documentation

## 4. Common commands

### Running the application

```bash
python main.py
python main.py --debug
python main.py --dry-run
python main.py --stocks AAPL,MSFT,RY.TO
python main.py --market-review
python main.py --schedule
python main.py --serve
python main.py --serve-only
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

### Backend validation

```bash
pip install -r requirements.txt
pip install flake8 pytest
./scripts/ci_gate.sh
python -m pytest -m "not network"
python -m py_compile <changed_python_files>
```

### Web / Desktop

```bash
cd apps/dsa-web
npm ci
npm run lint
npm run build

cd ../dsa-desktop
npm install
npm run build
```

### PR / CI evidence

```bash
gh pr view <pr_number>
gh pr checks <pr_number>
gh run view <run_id> --log-failed
```

## 5. Default workflow

1. Identify the task type first: `fix / feat / refactor / docs / chore / test / review`
2. Read the existing implementation, configuration, tests, scripts, workflows, and documentation before changing anything.
3. Identify the change boundary: backend / API / Web / Desktop / workflow / docs / AI collaboration assets.
4. Decide whether the change lands in a high-risk area: configuration semantics, API / schema, data-source fallback, report structure, authentication, scheduling, release process, desktop startup chain.
5. Make only the minimum change directly related to the current task. Do not smuggle in unrelated refactors.
6. If documentation, scripts, or workflow descriptions disagree with each other, trust the actual code and workflows first, then decide whether to fix the documentation along the way.
7. After changing, run the checks in the validation matrix below.
8. The final delivery should state, by default:
   - What changed
   - Why it changed this way
   - What was verified
   - What was not verified
   - Risks
   - How to roll back

## 6. Validation matrix

### CI coverage principles

The repository CI currently consists mainly of:

| Check | Source | Description | Blocking |
| --- | --- | --- | --- |
| `ai-governance` | `.github/workflows/ci.yml` | Validates the relationship between `AGENTS.md` / `CLAUDE.md` / `.github` instructions / `.claude/skills` | Yes |
| `backend-gate` | `.github/workflows/ci.yml` | Runs `./scripts/ci_gate.sh` | Yes |
| `docker-build` | `.github/workflows/ci.yml` | Docker build plus a key-module import smoke test | Yes |
| `web-gate` | `.github/workflows/ci.yml` | Runs `npm run lint` + `npm run build` on frontend changes | Yes (when triggered) |
| `network-smoke` | `.github/workflows/network-smoke.yml` | `pytest -m network` (live Yahoo Finance data for US and Canada; keyed providers skip without keys) | No (scheduled, not a PR check); a failed run means a supported market's data is unreachable |
| `pr-review` | `.github/workflows/pr-review.yml` | PR static checks + AI review + auto-labelling | No, advisory |

If the PR already has the matching CI result, cite the CI conclusion directly. If CI does not cover the changed surface, or the local and CI environments differ significantly, add an explanation of the local validation and the remaining gap.

### By change surface

- Python backend changes:
  - Applies to: `main.py`, `src/`, `data_provider/`, `api/`, `bot/`, `tests/`
  - Preferred: `./scripts/ci_gate.sh`
  - Minimum: `python -m py_compile <changed_python_files>`
  - If the change affects the API, task orchestration, report generation, notification sending, data-source fallback, authentication, or scheduling, state in the delivery notes whether those paths were covered.

- Web frontend changes:
  - Applies to: `apps/dsa-web/`
  - Default: `cd apps/dsa-web && npm ci && npm run lint && npm run build`
  - If the change touches API integration, routing, state management, Markdown/chart rendering, or authentication state, state the coupled surfaces and the uncovered risk explicitly.

- Desktop changes:
  - Applies to: `apps/dsa-desktop/`, `scripts/run-desktop.ps1`, `scripts/build-desktop*.ps1`, `scripts/build-*.sh`, `docs/desktop-package.md`
  - Default: build Web first, then the desktop app
  - If platform limits prevented full verification, state explicitly whether the Web build output, the Electron build, and the release workflow impact were verified.

- API / schema / authentication changes:
  - Applies to: `api/**`, `src/schemas/**`, `src/services/**`, `apps/dsa-web/**`, `apps/dsa-desktop/**`
  - Cover at least the matching backend validation plus a build check for the affected clients.
  - If the change touches login, cookies, sessions, polling state, added or removed fields, or enum changes, the compatibility impact must be written out explicitly.

- Documentation and governance file changes:
  - Applies to: `README.md`, `docs/**`, `AGENTS.md`, `.github/copilot-instructions.md`, `.github/instructions/**`, `.claude/skills/**`
  - Code tests are not mandatory.
  - Confirm that commands, configuration options, filenames, and workflow names match the actual repository.
  - When changing AI collaboration governance assets, run `python scripts/check_ai_assets.py`.

- Workflow / script / Docker changes:
  - Applies to: `.github/**`, `scripts/**`, `docker/**`
  - Run the local validation closest to the changed surface.
  - State which pipeline, release path, or deployment path is affected.
  - If Docker or GitHub Actions validation was not run, state the reason and the potential risk.

- Network or third-party dependency changes:
  - Run the offline or deterministic checks first.
  - Confirm that timeout, retry, fallback, error copy, and degradation paths still hold.
  - If online validation was not run, the reason must be written out explicitly.

## 7. Stability guardrails

- Configuration and runtime entrypoints:
  - When changing `.env` semantics, defaults, CLI arguments, service startup, or scheduling semantics, evaluate the impact on local runs, Docker, GitHub Actions, the API, Web, and Desktop together.
  - New configuration should aim to "run without being configured, and improve capability when configured". Avoid stacking switches and mutually exclusive modes.

- Data sources and fallback:
  - When changing `data_provider/`, pay attention to source priority, failure degradation, field normalization, caching, and timeout strategy.
  - A single data-source failure must not drag down the whole analysis flow, unless the requirement explicitly asks for fail-fast.

- API / Web / Desktop compatibility:
  - When changing the API, schema, authentication, or report payload, check backend, Web, and Desktop compatibility together.
  - Prefer adding fields, keeping old fields, or providing a compatibility layer, so existing clients are not broken silently.

- Reports / prompts / notifications:
  - When changing report structure, prompts, extractors, notification templates, or the bot chain, check that upstream inputs and downstream consumers are still compatible.
  - A single notification channel failure must not drag down the main analysis flow, unless the requirement explicitly asks for fail-fast.
  - When changing `EXTRACT_PROMPT` in `src/services/image_stock_extractor.py`, attach the complete updated prompt in the PR description.

- Workflows / releases / packaging:
  - When changing auto-tagging, releases, Docker publishing, the daily analysis job, or desktop packaging, evaluate trigger conditions, artifact paths, permission boundaries, and the rollback path.
  - Auto-tagging stays opt-in by default: only a commit title containing `#patch`, `#minor`, or `#major` triggers a version bump, unless the requirement explicitly asks to change the release strategy.

## 8. Issue / PR / Skill workflow

- The repository already ships the following skills; prefer reusing them:
  - `.claude/skills/analyze-issue/SKILL.md`
  - `.claude/skills/analyze-pr/SKILL.md`
  - `.claude/skills/fix-issue/SKILL.md`
- If the task is clearly issue analysis, PR review, or issue fixing, follow the matching skill and save the output to `.claude/reviews/`.
- The commands, templates, validation order, and delivery structure inside a skill must stay consistent with `AGENTS.md`.
- Before creating or updating a PR, reviewing a PR, or analysing an issue, sync to the latest code baseline first: check the working tree state and run `git fetch --all --prune`; if the working tree is clean and the current branch can fast-forward, run `git pull --ff-only`. If there are local changes, a conflict state, untracked risky files, or history that cannot fast-forward, do not force a branch switch, stash, reset, or overwrite local state. PR review and issue analysis may instead work from the fetched remote refs / PR head, recording in the analysis document why the local worktree was not updated, the current local HEAD, and the remote baseline used. PR creation and updates should first state the difference between the current branch and the target baseline, and where necessary ask the user to confirm a rebase, a merge, or continuing on the current branch.
- Skills read CI / workflow evidence first by default, and only then decide whether to add local validation.
- Apart from the safe fast-forward sync described above for PR creation/update and PR review/issue analysis, skills must not run `git pull`, `git push`, `git tag`, `gh pr create`, or any other operation that changes remote or current branch state by default. Those operations require user confirmation.
- Default PR review order:
  1. Necessity
  2. Relevance
  3. Title suggestion (`<type>: <what changed>`, with no tool/agent prefix; not a hard blocker)
  4. Description completeness (against `.github/PULL_REQUEST_TEMPLATE.md`)
  5. Verification evidence
  6. Implementation correctness
  7. Merge decision
- For `fix` PRs, the following must be stated: the original problem, the root cause, the fix, and the regression risk.
- Merge-blocking conditions:
  - Correctness or security problems
  - A blocking CI check that did not pass
  - A PR description that substantively contradicts the actual change
  - A missing rollback plan
  - Repeated, unconverged contract drift, patch stacking, or distorted verification evidence

## 8.1 Handling review feedback, and the ban on patch stacking

When you handle review feedback, you must not append a local patch only where the reviewer pointed and then claim "all fixed". You must first re-understand the business contract the reviewer identified, then check every entrypoint, configuration, test, document, workflow, and user-visible path covered by the same semantics.

After receiving review feedback, work in this order:

1. List each original problem the reviewer identified.
2. Explain the root cause. Describing "which lines changed" is not enough.
3. Find every related path affected by the same semantics, for example runtime, API/Web, CLI, diagnostics, workflow, docs, tests.
4. Fix the complete contract, not just the currently failing test or the commented line.
5. Add regression tests covering the reviewer's counterexample and the final entrypoint verification, or state clearly why it cannot be verified.
6. Update the PR body so scope, verification results, compatibility, risk, and the rollback plan match the current head.

If you cannot achieve that convergence, do not keep stacking patches and do not claim ready for merge. Say instead that the PR needs to be split, closed and redone, or that you need maintainer confirmation of a new minimal scope.

The following are treated as low-quality PRs:

- Using a broad fallback, silent degradation, or `return False/None/[]` to paper over an unclear contract.
- Tests that mock out the real risk layer and only prove that a local implementation passes.
- Claiming the problem is closed because CI passed, without covering the counterexample the reviewer raised.
- A PR body inconsistent with the actual diff, verification results, or compatibility risk.
- Continuing to append scattered patches after review instead of re-converging the complete semantics.
- The same business semantics behaving inconsistently across runtime, Web/API, docs, workflow, and tests.

A passing CI run only means the automated checks passed. It does not replace human semantic convergence, and on its own it does not prove the reviewer's counterexample is closed.

## 9. Delivery and release

- Default delivery structure:
  - `What changed`
  - `Why it changed this way`
  - `What was verified`
  - `What was not verified`
  - `Risks`
  - `How to roll back`
- For a `docs` task it is acceptable to write `Docs only, tests not run`, but you still need to state whether commands and filenames were checked.
- Auto-tagging does not trigger by default. Only a commit title containing `#patch`, `#minor`, or `#major` triggers a version bump.
- Manual tags must be annotated tags.
- User-visible changes should be merged through a PR, with labels and verification notes completed.
