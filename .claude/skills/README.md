# Repository Claude Skills

This directory holds repository-level collaboration skills and is a versioned repository asset.

- Source of truth for the rules: `AGENTS.md` in the repository root
- Compatibility entrypoint: `CLAUDE.md` in the root (it should be a symlink to `AGENTS.md`)
- The skills in this directory must stay consistent with `AGENTS.md`
- `.claude/reviews/` holds local analysis artifacts and is not a source of truth for the rules

If another agent directory has to be supported later (such as `.agents/skills/` or `.github/skills/`), define the single source of truth first and then sync by script or mirror, rather than maintaining several copies of the same content by hand over time.
