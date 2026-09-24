# ResearchArtifact: structured research output

`ResearchArtifact` is the structured version of a report, so that the dashboard, the single-stock research page, the monitoring centre, the watchlist, and Copilot can all reuse the same research conclusion.

## Goals

The first version solves three problems:

- Capture the report's conclusion as a `thesis` instead of relying on Markdown alone.
- Require every structured report to carry `invalidation_conditions`, stating explicitly when the thesis must be overturned or re-evaluated.
- Give every evidence item a `freshness` and a `quality_level`, so pages can show data recency and trustworthiness.

## Fields

Top-level structure:

- `schema_version`: fixed at `research-artifact-v1`.
- `artifact_id`: the stable artifact id. `report:<source_report_id>` is preferred; before persistence it uses `report:<stock_code>:<query_id>`, which avoids collisions when several stocks in a batch analysis share a query id. With no query id it falls back to `report:<stock_code>`.
- `source_report_id`: the history report primary key.
- `source_query_id`: the analysis task's query id.
- `created_at`: when the report was created.
- `subject`: the instrument.
- `thesis`: the structured view.
- `evidence`: the list of evidence.
- `invalidation_conditions`: invalidation conditions, at least one.
- `next_actions`: the next actions.
- `data_quality`: a summary of input quality.
- `metadata`: low-sensitivity extension fields.

## Thesis

`thesis` contains:

- `direction`: `bullish` / `bearish` / `neutral` / `unknown`.
- `summary`: the core view.
- `confidence`: confidence derived from the sentiment score.
- `score`: the raw sentiment score.
- `action` / `action_label`: the structured recommended action.
- `reasons`: supporting reasons.
- `risks`: the main risks.

## Evidence

`evidence` contains:

- `source_type`: for example `analysis_context`, `news`, `fundamental`, or `market_structure`.
- `freshness`: `fresh` / `stale` / `unknown`.
- `quality_level`: `good` / `usable` / `limited` / `poor` / `unknown`.
- `source`, `as_of`, `url`, `metadata` and other low-sensitivity extension fields.

The first-version adapter extracts evidence from `analysis_context_pack_overview.blocks`, news summaries, financial reports, dividends, and market structure.

## Invalidation

Every `ResearchArtifact` must contain at least one entry in `invalidation_conditions`.

Default sources in the first version:

- `strategy.stop_loss` produces a price invalidation condition.
- `strategy.take_profit` produces a take-profit review condition.
- Data-quality limitations produce a `data_quality` invalidation condition.
- A missing-news disclosure produces an `evidence` invalidation condition.
- When there is no explicit condition, a `manual:thesis_reassessment` fallback review condition is generated.

## Compatibility boundary

`AnalysisReport` gains an optional field:

```text
structured_report?: ResearchArtifact | null
```

Older reports may continue to omit the field; both the Web types and the backend schema treat it as optional.

This PR only defines the schema, the types, and a deterministic fallback helper. It does not yet wire the helper into report persistence or the history-detail response path; that wiring lands in a later stage of #2278.

## Implementation entry points

Backend:

- Schema: `api/v1/schemas/research_artifact.py`
- Helper: `src/services/research_artifact_service.py`
- Tests: `tests/test_research_artifact_service.py`

Web:

- Types: `apps/dsa-web/src/types/researchArtifact.ts`
- `AnalysisReport.structuredReport`: the optional consumption entry point

## Follow-up integration

1. The report generation path writes `structured_report` on persistence.
2. The single-stock research page reads `thesis`, `evidence`, and `invalidation_conditions` directly.
3. The monitoring centre turns invalidation conditions into editable rules.
4. The dashboard's What Changed view can compare the thesis and evidence of two `ResearchArtifact` records.
