# Analyze Issue

Analyze a GitHub issue and judge whether it is real, its priority, whether it falls inside the repository's responsibility, and what action to recommend.

**Repository**: https://github.com/your-org/your-repo/issues

## Usage

```text
/analyze-issue <issue_number>
```

## Instructions

Write the analysis in concise English, and follow `AGENTS.md` in the repository root first.

### Step 1: Sync to the latest code baseline

Before analyzing an issue, refresh the remote state and move the local checkout safely to the latest baseline where possible:

```bash
git status --short
git fetch --all --prune
# Only when the working tree is clean and the current branch can fast-forward:
git pull --ff-only
```

- Run and accept the result of `git pull --ff-only` only when the working tree is clean and the current branch has an upstream it can fast-forward to.
- With local changes, a conflict state, risky untracked files, no upstream branch, or no fast-forward available, do not run `stash` or `reset`, force-switch branches, or overwrite local state; analyze against the fetched `origin/main` or the relevant remote refs instead.
- Record the sync result in the output document's `Evidence`: the local HEAD, the remote baseline used, and why the local working tree was not updated (if it was not).

### Step 2: Fetch the issue

```bash
gh issue view <issue_number> --repo your-org/your-repo
gh issue view <issue_number> --repo your-org/your-repo --comments
```

For a bug, check first whether the issue template supplied:

- Whether it was reproduced on the latest version
- The commit hash / version baseline
- The runtime environment and reproduction steps
- Logs or error messages

### Step 3: Answer the four core questions

1. Is the version stated clearly?
2. Is the problem real and verifiable?
3. Does it fall inside the repository's responsibility?
4. Is it worth handling now?

### Step 4: Check the evidence against the repository's current state

- Read the relevant code, configuration, tests, scripts, workflows, and documentation
- If the problem touches the API, data-source fallback, report generation, notification sending, authentication, the desktop app, or the release process, state the blast radius explicitly
- Decide whether it is a real bug, an environment configuration problem, a usage problem, or an external dependency problem
- If you suspect it is already fixed, check the current code rather than the issue description alone

### Step 5: Reach a conclusion

Give at least these fields:

- `Version baseline`: latest / not latest / not provided
- `Reasonable`: yes/no plus the reason
- `Is an issue`: yes/no plus the reason
- `Easy to fix`: yes/no plus the difficulties
- `Conclusion`: `valid / partly valid / invalid`
- `Category`: `bug / feature / docs / question / external`
- `Priority`: `P0 / P1 / P2 / P3`
- `Difficulty`: `easy / medium / hard`
- `Recommended action`: `fix now / schedule a fix / clarify the docs / close`

### Step 6: Produce the analysis document

Save it to `.claude/reviews/issues/issue-<number>.md`

## Output Document Format

```markdown
# Issue #<number> Analysis

**Date**: YYYY-MM-DD
**Status**: Pending Review

## Summary

- Version baseline:
- Reasonable:
- Is an issue:
- Easy to fix:
- Conclusion:
- Category:
- Priority:
- Difficulty:
- Recommended action:

## Evidence

- Code sync baseline:
- Key issue information:
- Key code / script / workflow evidence:

## Impact Scope

- Affected modules:
- Affected runtime paths (local / Docker / GitHub Actions / API / Web / Desktop):

## Root Cause / Main Reasoning

<the root cause or the main basis for the judgment>

## Proposed Handling

<the suggested fix, clarification, or way to close it>

If a follow-up PR is recommended, suggest a PR title that matches `AGENTS.md`: use `<type>: <what changed>`, and do not add a `[codex]`, `codex`, `autocode`, `copilot`, or other tool/agent source prefix. That convention is a collaboration-consistency reminder and must not be used on its own as a review process blocker.

## Risks And Rollback

- Risks:
- If fixed, how to roll back:

## Draft Reply

<the suggested reply>
```

## Allowed Auto-Actions (No Confirmation Needed)

- Fetching the issue details and comments
- Running `git fetch --all --prune`, and `git pull --ff-only` when the working tree is clean and can fast-forward
- Reading the relevant code, configuration, scripts, workflows, and documentation
- Producing the analysis document

## Actions Requiring Confirmation

Ask the user before doing any of these:

1. Adding or changing labels
2. Commenting on the issue
3. Closing the issue
4. Starting to fix the issue
