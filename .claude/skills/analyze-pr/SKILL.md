# Analyze PR

Analyze a GitHub pull request and assess whether it is necessary, whether its description is complete, its verification evidence, its main risks, and whether it can be merged as is.

**Repository**: https://github.com/your-org/your-repo/pulls

## Usage

```text
/analyze-pr <pr_number>
```

## Instructions

Write the analysis in concise English, and follow `AGENTS.md` in the repository root and `.github/PULL_REQUEST_TEMPLATE.md` first.

### Step 1: Sync to the latest code baseline

Before analyzing a PR, refresh the remote state and move the local checkout safely to the latest baseline where possible:

```bash
git status --short
git fetch --all --prune
# Only when the working tree is clean and the current branch can fast-forward:
git pull --ff-only
```

- Run and accept the result of `git pull --ff-only` only when the working tree is clean and the current branch has an upstream it can fast-forward to.
- With local changes, a conflict state, risky untracked files, no upstream branch, or no fast-forward available, do not run `stash` or `reset`, force-switch branches, or overwrite local state; analyze against the fetched `origin/main`, the PR head, or the GitHub diff instead.
- Record the sync result in the output document's `Validation Evidence`: the local HEAD, the remote baseline used, and why the local working tree was not updated (if it was not).

### Step 2: Fetch the PR basics

```bash
gh pr view <pr_number> --repo your-org/your-repo
gh pr view <pr_number> --repo your-org/your-repo --comments
gh pr checks <pr_number> --repo your-org/your-repo
gh pr diff <pr_number> --repo your-org/your-repo
```

When CI is failing, read the failure log first rather than immediately re-running every check locally:

```bash
gh run view <run_id> --log-failed
```

### Step 3: Check the title and description completeness

Check the PR title against the non-blocking recommendation in `AGENTS.md` first:

- The format should be `<type>: <what changed>`, for example `fix: restore lost market-review analysis history`
- Preferred types are `fix`/`feat`/`refactor`/`docs`/`chore`/`test`/`ci`
- It should not contain a `[codex]`, `codex`, `autocode`, `copilot`, or other tool/agent source prefix
- The title should describe the actual change. If the title does not match the diff, note it under description completeness, but do not use it on its own as a review process blocker.

Against `.github/PULL_REQUEST_TEMPLATE.md`, confirm the PR covers:

- `PR Type`
- `Background And Problem`
- `Scope Of Change`
- `Issue Link`
- `Verification Commands And Results`
- `Visual Evidence` (screenshots or equivalent visual evidence are required only when the PR changes the report format, report rendering, or the Web UI)
- `Compatibility And Risk`
- `Rollback Plan`

If the PR touches third-party model / API compatibility semantics, fixed request parameter values, OpenAI-compatible routing, a YAML alias, fallback behavior, or runtime configuration save / cleanup / migration logic, also check that the description states explicitly:

- The official source link or announcement
- The currently pinned dependency / runtime compatibility window (for example the LiteLLM version window)
- Which call paths were verified
- Whether existing configuration is silently rewritten, cleared, migrated, or left alone
- The minimal rollback path (usually reverting the PR)

If the PR changes the report format, report rendering, or the Web UI, also check that `Visual Evidence` attaches screenshots of the affected reports or pages; prefer a before/after comparison when the change is a visual diff. If a screenshot is impossible, the description should say why and give equivalent visual evidence.

### Step 4: Prefer CI and diff evidence

- Judge the problem from `gh pr checks`, the PR diff, the existing tests, and the workflow logs first
- Add a local minimal verification only when CI does not cover the changed surface, the CI result cannot characterize the problem, or a key regression risk needs verifying
- Do not switch the current branch or run `gh pr checkout` by default

When a local verification is genuinely needed, pick the closest check for the changed surface, for example:

- Backend: `./scripts/ci_gate.sh` or `python -m py_compile <changed_python_files>`
- Frontend: `cd apps/dsa-web && npm ci && npm run lint && npm run build`
- Desktop: build the web app first, then Electron

### Step 5: Assess correctness and risk

Focus on:

- Whether it solves a clearly stated problem without carrying unrelated changes
- Whether it breaks API / schema / Web / Desktop compatibility
- Whether it breaks fallbacks, degradation paths, the notification path, or the release process
- Whether there is an obvious logic error, a swallowed exception, a security problem, or a configuration semantics change that the documentation does not reflect

### Step 6: Produce the review document

Save it to `.claude/reviews/prs/pr-<number>.md`

## Output Document Format

```markdown
# PR #<number> Analysis

**Date**: YYYY-MM-DD
**Status**: Pending Review

## Findings

- [severity] file:line - description of the problem

## Summary

- Necessity:
- Has a matching issue:
- PR type:
- PR title:
- Description completeness:
- Verification:
- Main risks:
- Can be merged as is:

## Validation Evidence

- Code sync baseline:
- CI conclusion:
- Additional local verification (if any):

## Compatibility And Risk

- API / Web / Desktop:
- Configuration / Docker / GitHub Actions:
- Fallback / notifications / report structure:
- Third-party dependencies / official constraint sources:
- Runtime compatibility window / call paths covered:
- Risk of migrating or silently rewriting existing configuration:

## Draft Review Comment

<the suggested comment>
```

## Allowed Auto-Actions (No Confirmation Needed)

- Fetching the PR metadata, diff, comments, and CI status
- Running `git fetch --all --prune`, and `git pull --ff-only` when the working tree is clean and can fast-forward
- Reading the relevant code, templates, workflows, and documentation
- Running a minimal local verification when needed
- Producing the review document

## Actions Requiring Confirmation

Ask the user before doing any of these:

1. Posting a comment
2. Approving the PR
3. Requesting changes
4. Merging the PR
5. Closing the PR
