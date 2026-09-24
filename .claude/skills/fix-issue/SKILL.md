# Fix Issue

Implement a fix based on the issue analysis, and supply the verification, risk, and rollback notes the repository rules require.

**Repository**: https://github.com/ZhuLinsen/daily_stock_analysis

## Usage

```text
/fix-issue <issue_number>
```

## Prerequisites

Run `/analyze-issue <issue_number>` first where possible, to confirm the problem is real and its boundary is clear.

## Instructions

### Step 1: Confirm the analysis baseline

Check whether `.claude/reviews/issues/issue-<number>.md` exists. If it does not, do the issue analysis first, or add a minimal analysis conclusion as part of this fix.

### Step 2: Sync to the latest code baseline and choose a safe way to work

Before fixing, or before creating or updating a PR, pull the latest per `AGENTS.md`:

```bash
git status --short
git fetch --all --prune
# Only when the working tree is clean and the current branch can fast-forward:
git pull --ff-only
```

- By default, make the minimal relevant change on the current working tree
- Run and accept the result of `git pull --ff-only` only when the working tree is clean and the current branch has an upstream it can fast-forward to
- With local changes, a conflict state, risky untracked files, no upstream branch, or no fast-forward available, do not run `stash` or `reset`, force-switch branches, or overwrite local state; record the local HEAD, the remote baseline used, and why the local working tree could not be updated
- If a PR will be created or updated afterwards, state the difference between the current branch and the target baseline first; ask the user to confirm a rebase, a merge, or continuing on the current branch when that matters
- Do not switch branches or rewrite the user's current working state by default
- Perform the minimal necessary branch operation only when the user explicitly asks for a branch

### Step 3: Implement the fix

- Locate the relevant files from the issue's conclusion
- Prefer reusing existing modules, configuration entrypoints, scripts, and tests
- Keep the default behavior backward compatible and avoid breaking fallback / fail-open paths
- If the fix touches user-visible behavior, configuration semantics, the CLI/API, deployment, notifications, or the report structure, update the related documentation, `docs/CHANGELOG.md`, and `.env.example` in the same change
- When adding an entry to `docs/CHANGELOG.md`, append one line to the `[Unreleased]` section in the form `- [type] description`, where `type` is one of `feat`/`improve`/`fix`/`docs`/`test`/`chore` chosen to match the change; use `fix` only for a bug fix; **do not** add a `### category heading` inside `[Unreleased]`
- `README.md` carries only homepage-level information: project positioning, core capabilities, quick start, main entrypoints, and sponsorship/partnership. Do not update the README unless it is necessary, so it does not keep growing
- Finer module behavior, page interactions, topic-specific configuration, troubleshooting notes, field contracts, implementation semantics, and edge cases belong in the matching `docs/*.md`

### Step 4: Verify against the changed surface

Run the closest check from the `AGENTS.md` verification matrix:

- Backend, preferred: `./scripts/ci_gate.sh`
- Backend, minimum: `python -m py_compile <changed_python_files>`
- Frontend: `cd apps/dsa-web && npm ci && npm run lint && npm run build`
- Desktop: build the web app first, then the desktop app

If full verification is impossible, record the gap, the reason, and the potential risk.

### Step 5: Update the issue analysis document

Add the following to `.claude/reviews/issues/issue-<number>.md`:

```markdown
## Fix Implementation

**Date**: YYYY-MM-DD

### Changes Made

- Files and change points:

### Validation

- Ran:
- Did not run:

### Risks

- Risks:

### Rollback

- How to roll back:
```

### Step 6: Follow-up actions that need confirmation

If the user asks for a PR, a PR title, or a PR description, the title should follow `AGENTS.md`:

- Use the `<type>: <what changed>` format, for example `fix: restore lost market-review analysis history`
- Prefer the types `fix`/`feat`/`refactor`/`docs`/`chore`/`test`/`ci`
- The title should describe only the actual change; do not add a `[codex]`, `codex`, `autocode`, `copilot`, or other tool/agent source prefix
- The convention exists for collaboration consistency and must not be treated on its own as a process blocker

Do the following only after the user confirms explicitly:

- Creating a branch
- `git commit`
- `git push`
- Creating a PR
- Replying on the issue or closing it

## Allowed Auto-Actions (No Confirmation Needed)

- Reading and analyzing code
- Running `git fetch --all --prune`, and `git pull --ff-only` when the working tree is clean and can fast-forward
- Applying the minimal fix directly relevant to the current task
- Running non-destructive local verification
- Updating the local issue analysis document

## Actions Requiring Confirmation

1. Switching or creating a branch
2. `git commit`
3. `git push`
4. Creating a PR
5. Replying on or closing the issue
