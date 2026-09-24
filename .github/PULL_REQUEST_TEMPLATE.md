<!--
Please fill in this template in English.
-->

## PR Type

- [ ] fix
- [ ] feat
- [ ] refactor
- [ ] docs
- [ ] chore
- [ ] test

## Background And Problem

Describe the problem, its impact, and what triggers it.

## Scope Of Change

List the modules and files changed in this PR.

> Note: list the full file scope according to the actual `git diff` (stating the total file count is recommended), so that documentation, backend, API, and frontend files are not omitted and the description stays consistent.

> If this PR changes collaboration or governance files such as `.github/PULL_REQUEST_TEMPLATE.md`, `.github/copilot-instructions.md`, `AGENTS.md`, `.github/instructions/*`, or `.claude/skills/**`, add "reason for change + blast radius + rollback path (revert by default)" to Summary / Compatibility / Rollback, so Scope and description do not disagree.

> Running the following and pasting the output first is recommended, so the description matches the actual diff:

```bash
BASE_REF=$(git merge-base HEAD origin/main)
git diff --stat "$BASE_REF"..HEAD
git diff --name-only "$BASE_REF"..HEAD
```

- Total files / changed lines (pasting `git diff --stat "$BASE_REF"..HEAD` is recommended):
- File list (complete, per the actual diff, itemized):
- Documentation files updated (`docs/*`):

## Issue Link

Fill in one of:
- `Fixes #<issue_number>`
- `Refs #<issue_number>`
- If there is no issue, explain the motivation and acceptance criteria

## Verification Commands And Results

Paste the commands you actually ran and their key output. Do not just write "tested".

```bash
# example
./scripts/ci_gate.sh
python -m pytest -m "not network"
```

> `Full-suite note` must agree with the current Head CI result for this PR. If a local reproduction has environment-related failures, label them clearly as "local environment difference" and give the GitHub CI conclusion and link.
> Do not carry over historical failure wording unrelated to this PR; report the actual result of this run.
> If the description still records a `./scripts/ci_gate.sh` failure from an earlier revision, update it to the current Head CI state or explain where it differs from Head CI.
> If `Full-suite note` disagrees with the current Head CI, the PR text is incomplete; update the PR description before submitting.

- Fill in the following with actual results, consistent with `Full-suite note` (any blank entry counts as missing information):
  - ai-governance: `pass` / `fail`, with a link
  - backend-gate: `pass` / `fail`, with a link
  - docker-build: `pass` / `fail` / `skipped`, with a link when it ran
  - web-gate: `pass` / `fail` / `skipped`, with a link when it ran
  - If this PR changes process-template files such as `.github/PULL_REQUEST_TEMPLATE.md`, first state why the change is necessary, its blast radius, and the rollback path (`revert this PR` by default); otherwise split it into a separate chore PR in the next revision.

Key output and conclusion:

- [Required] Current Head CI: `ai-governance:pass / backend-gate:pass / docker-build:pass / web-gate:pass` (replace with actual results) with the matching links. Docker/Web checks not run for this path should be written as `skipped`.
- If you need to keep a local failure on record, write "local environment difference + current CI pass/fail result + CI link" in the same paragraph.
- If everything passed, add the line: `Current status: all passed (pass)`, and make clear that Head CI is entirely pass.

- Pasting this line directly into the first paragraph of the PR description is recommended: `Current Head CI: ai-governance:pass / backend-gate:pass / docker-build:pass / web-gate:pass` (example only, replace with actual results).

> If the checks above conflict with the PR text, update the PR description before submitting, so review is not blocked by an inconsistent state.

## Visual Evidence (if applicable)

[Required] If this PR changes report formatting, report rendering, or the Web UI, attach screenshots of the affected report or page here; before/after comparisons are preferred where relevant. Issue/PR process screenshots, review screenshots, one-off acceptance screenshots, and temporary visual evidence belong in the PR description, PR comments, GitHub attachments, Actions artifacts, or an externally accessible link. Do not commit them as repository files.

> If a screenshot cannot be produced, state the alternative evidence in the "reason" field (for example a Playwright/e2e artifact path or a review link) together with a traceable command. Do not leave it blank. For Web settings or report rendering changes, the screenshot or alternative evidence must point clearly at the changed item.
>
> If this PR changes the Web UI, adding at least one reproducible path is recommended, for example (settings page preferred):
>
> - Playwright screenshot artifact: `apps/dsa-web/e2e/smoke.spec.ts` (`cd apps/dsa-web && npx playwright test e2e/smoke.spec.ts --grep "settings page renders title and save actions after login"`)
> - Review evidence link: an Actions artifact, a GitHub comment attachment, or an externally accessible link.

> Alternative evidence template (recommended for settings-page changes):
> - Command: `cd apps/dsa-web && npx playwright test e2e/smoke.spec.ts --grep "settings page"`
> - Artifact path: `apps/dsa-web/test-results/**/smoke-settings-page-*.png`
> - Note: the changed system settings item (field, label, help text) must be visible in the screenshot

- Screenshot links (required for Web UI / report changes; if not provided, give alternative evidence under "reason if not applicable" below):
- Suggested settings-page naming: `smoke-settings-page-zh` / `smoke-settings-page-en`
- Before & After (if any):
- Settings field change notes: the screenshot or artifact must clearly include the `MARKET_REVIEW_REGION` field and its help-text block (Chinese and English).
- Reason if not applicable (required when no screenshot is attached, including reproducible evidence and the command):
  - Playwright command (when there is no screenshot): `cd apps/dsa-web && npx playwright test e2e/smoke.spec.ts --grep "settings page"`
  - Artifact path (when there is no screenshot): `apps/dsa-web/test-results/**/smoke-settings-page-*.png`
  - Note: the screenshot or artifact must show the changed settings field text and help information.

> If this PR changes Web settings fields (field, label, or help text), the screenshot or alternative evidence must locate the matching settings area and be traceable to the changed item. This field is required.

> If this PR changes the Web UI or report rendering and a screenshot cannot be produced, the reason field must give reproducible alternative evidence (for example a Playwright artifact path plus the command) and must not be left blank.

## Compatibility And Risk

Describe compatibility impact and potential risks. Write `None` if not applicable.

- If this PR changes third-party model/API compatibility semantics, request parameters, routing prefixes, or provider fallback, include an **official source link or announcement** and clarify whether the rule is a long-term constraint, a current runtime constraint, or a temporary compatibility workaround.
  Add the affected external API/service, the regression scope, and the rollback path below.
- If this PR does not touch third-party models/APIs, provider/model/base URL, or runtime config save/cleanup/migration logic, confirm with the following wording in this section (no need to expand further):
  `This PR does not change provider/model/base URL or runtime config cleanup/migration semantics; existing configuration is unchanged; rollback is to revert this commit.`
- If this PR changes `.github/PULL_REQUEST_TEMPLATE.md` or other PR process template files, state here that it only affects contribution governance templates and does not change runtime behavior, that rollback is by revert, and whether it affects any automated submission flow.
- If this PR depends on a specific runtime or a pinned dependency window (for example a LiteLLM version range, OpenAI-compatible routing, or YAML alias behavior), state the compatibility window you verified and which code paths were covered.
- If this PR touches runtime config save, cleanup, migration, or backfill logic, explicitly describe whether existing config is rewritten, cleared, migrated, or left intact, and how users can restore the previous behavior.
- If this PR **does not touch** provider/model/base URL or runtime config save/cleanup/migration logic (this item is a declaration only), state explicitly: `This PR does not change provider/model/base URL or runtime config cleanup/migration semantics; existing configuration is unchanged; rollback is to revert this commit.`

## Rollback Plan

Provide at least one actionable rollback step. Required.

- For a compatibility fix, state the **minimal rollback path** (for example `revert this PR`) and whether any additional config rollback or data migration is required.

## EXTRACT_PROMPT Change (if applicable)

If this PR changes `EXTRACT_PROMPT` in `src/services/image_stock_extractor.py`, paste the full updated prompt here:

<details>
<summary>Expand: Full EXTRACT_PROMPT</summary>

```
(paste full prompt here)
```

</details>

## Checklist

- [ ] This PR has a clear motivation and value
- [ ] Reproducible verification commands and results are included
- [ ] Compatibility and risk have been assessed
- [ ] A rollback plan is provided
- [ ] If report formatting or the Web UI changed, affected report/page screenshots are linked in the PR body or comments, and one-off acceptance screenshots are not committed as repository files
- [ ] If Web settings fields changed (field, label, or help text), settings-page screenshots are attached; where a screenshot is unavailable, alternative visual evidence is provided (command + artifact path) pointing at the changed item
- [ ] If user-visible changes are included, the relevant docs and `docs/CHANGELOG.md` are updated; `README.md` is updated only for homepage-level changes, with details kept in `docs/*.md`
