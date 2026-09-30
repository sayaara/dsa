# The multi-strategy investment recommendation contract: baseline semantics, Phase 1 convergence, Phase 2/3/4 boundaries

This page is the topic document for Issue #1964, "multi-strategy investment recommendations". It records the **semantic convergence boundary** for two or more strategy/skill opinions inside the system: the valid evidence set, isolation of invalid opinions, camp grouping, consensus level, and cross-consumer consistency. The baseline owns the contract boundary and the inventory of current behavior. Phase 1 implements, inside the baseline contract only, the partitioning of the valid evidence set, deterministic `strategy_synthesis` composition, DecisionAgent prompt convergence, consistency across the three renderers, and E2E counter-example coverage. Phase 1.5 adds controlled collaborative reasoning v0 (mediator_v0) on top of the Phase 1 contract, recording only conflict agenda items, strategy responses, softened revisions, and the reason for a confidence discount. Phase 1.6 adds an injectable LLM mediator v1 (llm_mediator_v1), which allows only schema-valid structured revisions and falls back to v0 when anything is missing, malformed, or out of bounds. Phase 1.7 adds strategy self-review v2 (self_review_v2), which lets only the strategies involved in a conflict review themselves against a fixed schema and rolls the whole round back to the baseline if any participant steps out of bounds. Phase 1.8 adds revision projection v3 (revision_projection), which only previews the synthesized signal, confidence, and conflict state after adopting the softened revisions and never overwrites the authoritative `final_signal`. Phase 1.9 adds configurable multi-round collaborative reasoning v4 (multi_round_v4), which continues structured revision up to `max_rounds` and keeps a `round_history`, returning to the previous verified result whenever a round steps out of bounds. Phase 2 adds concurrent scheduling of 2-4 strategies and stage scheduling, under the Phase 1/1.5/1.6/1.7/1.8/1.9 contract only. Phase 3 adds full frontend multi-language presentation on top of Phase 2 only. Phase 4 adds the real Skill Outcome weight feedback loop within the same `CONTRACT_VERSION = "1.0"`. Every baseline constraint applies permanently to every later phase, and Phase N must never silently weaken a boundary the baseline has already fixed.

## The skill opinion sample boundary (Issue #1904 P2 PR1)

`AgentRuntimeFacts.skill_opinions` projects only the low-sensitivity fields of an individual SkillAgent: `skill_id`, the canonical `signal`, `confidence`, and the opinion time. `skill_consensus` / `strategy_consensus`, the DecisionAgent, the base agents, and invalid opinions must never enter that set. When one run produces several valid opinions for the same `skill_id`, only the last is kept. On first parse, a SkillAgent must reject a confidence that is non-numeric, non-finite, or outside `[0, 1]`; AgentOpinion keeps the input-validity flag for RuntimeFacts to check defensively, and clamping an invalid input and then using it as a valid sample is forbidden.

After analysis history is saved successfully, the pipeline writes the `skill_opinion_samples` sidecar best-effort. The parent-history existence check and the sample insert must live in the same atomic SQLite write transaction, and history deletion reuses that same write transaction and locked retry, so no orphan sample can be left behind whichever of the insert and the delete runs first. The idempotency key is `(analysis_history_id, skill_id, sample_schema_version)`, and a repeated run must not overwrite the immutable sample saved the first time. A failed write records only a low-sensitivity error type and must never fail the report, the history record, or the main DecisionSignal flow.

The current `sample_schema_version=skill-opinion-sample-v1`. `skill_version` and `horizon` are kept only as empty compatibility slots: the existing skill definitions and SkillAgent output have no trustworthy version or horizon contract, so this stage must not guess or fabricate them from the LLM `raw_data`. PR1 creates no outcome, provides no skill performance statistics, does not implement `get_skill_summary()`, and does not change `AgentMemory` or `SkillAggregator` weights.

## The Skill Opinion Outcome boundary (Issue #1904 P2)

`skill_opinion_outcomes` represents one immutable `skill_opinion_sample`'s independent retrospective result for one `horizon` under one `engine_version`, with the unique key `(skill_opinion_sample_id, horizon, engine_version)`. The initial horizons allow only `1d`, `3d`, `5d`, and `10d`. Each run's `limit` caps the number of pending `sample × horizon` outcome keys, not the number of samples. An explicitly empty horizons list, a blank skill/stock filter, and an out-of-range limit must all fail closed and must never degrade into a full run.

Each outcome uses only its own sample's canonical `signal` and must not read the final agent decision, `skill_consensus`, or another skill's signal. `strong_buy` / `buy` are evaluated as bullish and `strong_sell` / `sell` as bearish; a directional return must be strictly greater than zero to count as a `hit`, and a zero return is a `miss`. Once the price window is complete, `hold` is saved as `observational` and produces no directional correctness.

The historical analysis date comes from `enhanced_context.date`, falling back to the history record's creation date only when that is missing. Backtest and Outcome share stock identity resolution, supported legacy market-snapshot reconstruction, and the authoritative starting-session determination: a `market_phase_summary.effective_daily_bar_date` that is market-consistent and valid is preferred; when that field is missing, the start is derived only if the phase and the trading calendar can prove it, and otherwise the process fails closed rather than picking an arbitrary earlier local daily bar. Outcome accepts only an `expected_start_date` that passes that determination. For compatibility with existing history, Backtest may replay read-only through an explicit `backtest_start_date` when the exact local bar for a non-session `effective_daily_bar_date` already exists; that fallback is not an authoritative Outcome sample, does not trigger an invalid-date refill, and does not enter Skill Outcome statistics or weight calibration. The shared window resolver prefers a complete window at the given start, and the start and the forward bars must come from the same stored code shape, never stitched across candidates.

For Outcome, when the authoritative starting session is determined but its starting bar is not yet written, or the future local daily bars are insufficient, the result is saved as a retryable `pending`. Candidate keys are scheduled fairly by last attempt time (or by sample creation time when there is no outcome yet); each retry refreshes `pending.updated_at` and moves the key to the back of the queue, so a steady stream of new missing keys cannot starve old retries and retries cannot block new samples in reverse. Permanently invalid metadata — a corrupt `effective_daily_bar_date` or one later than the analysis date, a conflict between the stock's market and the snapshot's market, or a start that a trustworthy phase and trading calendar cannot prove — is saved as the terminal state `unable` and must never masquerade as `missing_start_bar` and retry forever. Under one engine version only `pending` may be updated; `evaluated`, `observational`, and `unable` are all immutable, and a rule change must raise the engine version. History deletion explicitly cleans up outcome -> sample -> history inside the same write transaction and must not rely on the SQLite foreign-key pragma.

The Outcome core stage (#2116) builds on the already-merged #2073 and provides only the Outcome evaluator, repository, and service core; at that time it included no performance statistics, sample-sufficiency check, ranking, or weight adjustment. The read-only statistics stage that followed is defined separately in the next section; that stage still adds no administrator API, schema, OpenAPI entry, or automatic trigger in the main pipeline, and it does not adjust runtime weights. If an operations entrypoint is needed later, it should be reviewed separately against its real callers and permission contract.

### Skill Opinion Outcome performance statistics

Outcome statistics are a read-only data surface, bucketed independently by `skill_id + horizon + engine_version`. No bucket may borrow another horizon of the same skill, another skill, another engine version, or the global sample to unlock its metrics. The current fixed threshold is `evaluated >= 30`; only the `hit` / `miss` produced by an individual skill opinion's own signal counts toward evaluated, while `pending`, `observational`, and `unable` keep their counts but do not count toward sample sufficiency.

Below the threshold a bucket's `sample_status` is `observational`: the counts are still returned, but `hit_rate_pct`, `miss_rate_pct`, `avg_directional_return_pct`, and `unable_rate_pct` are all `null`, and no ranking or derived weight may be emitted. Above the threshold, the hit and miss rates use `hit + miss` as the denominator, the average directional return uses evaluated rows only, and the unable rate uses the terminal records `evaluated + observational + unable` as its denominator, so a transient `pending` cannot dilute the permanent-failure ratio.

The read-only statistics stage (PR #2119) itself does not modify `BacktestService.get_skill_summary()`, `AgentMemory`, or `SkillAggregator`, and it adds no API, automatic pipeline trigger, or web presentation. Phase 4, later on this page, wires conservative runtime weights on top of that statistics contract independently. The current combined implementation still only reads already-persisted Outcomes and is not responsible for triggering the evaluator automatically.

## Terminology and boundaries

The repository currently has several data surfaces called opinion / signal / consensus / synthesis, so the baseline must disambiguate them first, to avoid describing an existing runtime structure as a future phase.

| Term | Current meaning | Main current consumers | Baseline boundary |
| --- | --- | --- | --- |
| `AgentOpinion` | The opinion data class in `src/agent/protocols.py` produced by every agent (including SkillAgent, TechnicalAgent, IntelAgent, RiskAgent, and DecisionAgent), carrying `agent_name` / `signal` / `confidence` / `reasoning` / `key_levels` / `raw_data`. | Orchestrator, Aggregator, DecisionAgent, Disagreement, Renderer | Recorded as the raw opinion carrier; the baseline adds no field and does not split `AgentOpinion` into two kinds. |
| `StrategyOpinion` | The internal normalized view in `src/agent/protocols.py`, carrying `skill_id` / `signal` / `original_signal` / `invalid_signal`; used only inside the Aggregator/Synthesizer. | `SkillAggregator`, `ConflictDetector`, `StrategySynthesizer` | Recorded as an internally computed normalized view: it never enters `ctx.opinions`, the public payload, or the DecisionAgent prompt. |
| Signal / Canonical Signal | The normalized trading-signal label. Canonical values are limited to the five lowercase strings `strong_buy` / `buy` / `hold` / `sell` / `strong_sell`. | The whole chain | Recorded as the only input form every downstream computation may accept; uppercase aliases, `"strong buy"`, and raw Signal enum values must all pass through `normalize_strategy_signal()` into canonical form before entering a computation. |
| Valid Opinion / Invalid Opinion | An opinion is valid when `is_valid_strategy_signal(signal) == True` and it is not marked `invalid_signal=True`; everything else is invalid. | Orchestrator partitioning, Aggregator, DecisionAgent | Recorded as the contract-level valid/invalid determination; the baseline defines the function and the semantics only and presumes nothing about where partitioning happens. |
| Evidence Chain | The **set of valid opinions** that enters the DecisionAgent prompt and the `strategy_synthesis` numeric computation. | DecisionAgent, Aggregator | Recorded as the decision input surface; the baseline requires the Evidence Chain to consist solely of valid opinions, with no invalid opinion mixed in. |
| Diagnostics | The holding area for invalid opinions, used only for logs, debugging, and the user-visible "另有 N 个策略解析失败" count. | Renderer display, logs | Recorded as the diagnostic surface; the baseline requires every invalid opinion to land in Diagnostics and forbids silently converting one to `hold` and mixing it into the Evidence Chain. |
| `strategy_synthesis` | The top-level `dashboard.strategy_synthesis` payload, carrying `final_signal` / `consensus_level` / `conflict_severity` / `supporting_skills` / `opposing_skills` / `summary_params`. | The Markdown, Notification, and History renderers | Recorded as the public low-sensitivity payload; the baseline declares it the **single authoritative synthesis source**, which the LLM dashboard must never overwrite. |
| `disagreement_summary` | `ctx.meta["agent_disagreement_summary"]`, a low-sensitivity cross-agent disagreement summary from `build_agent_disagreement_summary()`. | The DecisionAgent prompt, logs | Recorded as the decision-path hint surface; the baseline requires buckets to be built from valid opinions only, with no invalid opinion in `bullish_agents` / `bearish_agents` / `neutral_agents`. |
| Consensus Level | `strategy_synthesis.consensus_level`, taking the values `high` / `medium` / `low` / `insufficient`. | Renderer display, internal Aggregator determination | Recorded as the consensus enumeration; the baseline forces `insufficient` when there is at most 1 valid opinion or `sum(confidence) == 0`, and forbids emitting `high`. |

## Baseline scope and non-goals

The baseline exists so that Phases 1/2/3/4 all design their runtime changes against one semantic contract, instead of redefining "valid opinion", "consensus", and "supporting side" in every PR.

- The baseline covers the semantic convergence boundary across the seven consumers SkillAgent -> Orchestrator -> Aggregator -> Synthesizer -> DecisionAgent -> Disagreement -> Renderer.
- The baseline fixes the canonical signal enumeration, the valid/invalid determination functions, the Evidence Chain / Diagnostics separation principle, the dynamic bipartite grouping semantics, the consensus threshold gradient, the `strategy_synthesis` payload schema, the invariant list, and the counter-example matrix. Phase 1 is the first code implementation of those boundaries.
- The baseline introduces no concurrent scheduling, no full frontend multi-language presentation, and no backtest-driven weight feedback; those belong to Phases 2/3/4.
- The baseline changes no existing `AgentOpinion` field, adds no database field, changes no API response structure (`strategy_synthesis` was added in an earlier PR), and adds no configuration option.
- The baseline does not expand the contract into a general opinion registry; the `AgentOpinion` structure stays with the existing code, and this contract governs only its **semantic handling flow**.

## The baseline internal contract

### Canonical Signal and validity determination

The canonical signal is the **only scoring, weighting, and grouping input form** the baseline allows. Normalization enters through two functions in `src/agent/protocols.py`:

- `normalize_strategy_signal(signal)` returns the triple `(canonical, invalid, original)`. It accepts a `Signal` enum, strings of any case, and the `"strong buy"` / `"strong-buy"` aliases, mapping them all into the canonical set. When mapping is impossible, `invalid=True` and `canonical` degrades to `default` (`"hold"` by default) — but it **must** be passed downstream together with `invalid=True` and must never be used on its own.
- `is_valid_strategy_signal(signal)` is the **single source of truth** for validity across the baseline: any module deciding whether an opinion qualifies for the Evidence Chain must call it.

The baseline forbids maintaining a second canonical mapping table outside `_STRATEGY_SIGNAL_ALIASES`. The `strategy_signal_score(canonical)` inside ConflictDetector and Synthesizer accepts canonical values only, and looking up `op.original_signal` or a case variant is forbidden.

### Separating the Evidence Chain from Diagnostics

The baseline requires:

- **The Evidence Chain is exactly the set of valid opinions.** The DecisionAgent prompt, the `strategy_synthesis` numeric computation, and `disagreement_summary` bucket building must all read from that same Evidence Chain.
- **An invalid opinion must land in Diagnostics** (`ctx.meta["invalid_opinions"]` or an equivalent field), used only for logs, diagnostics, and the user-visible "另有 N 个策略解析失败" count.
- The two sets are **mutually exclusive and jointly exhaustive**: an opinion is either in the Evidence Chain or in Diagnostics, never in both and never in neither.
- An invalid opinion **must not** be silently converted to `hold`, keep its original `confidence`, or be mixed anonymously into the `bullish_agents` / `bearish_agents` / `neutral_agents` buckets.

The Diagnostics structure:

```python
ctx.meta["invalid_opinions"] = [
    {
        "agent_name": str,          # the original agent_name
        "raw_signal": str | None,   # the raw signal literal (not normalized)
        "confidence": float,        # the raw confidence, diagnostic only, never used in a computation
        "reason": str,              # "missing_signal" | "unrecognized_signal" | "invalid_flag"
    },
    ...
]
```

The baseline specifies only that structure, not the **code location** where partitioning happens — Phase 1 puts it in the Orchestrator.

### Dynamic bipartite grouping (Supporting / Opposing)

Given the final signal `final_signal` and the canonical score `final_score = strategy_signal_score(final_signal)`, compute `op_score = strategy_signal_score(op.signal)` for each valid opinion `op`:

- **When `final_signal == "hold"` (that is, `final_score == 3.0`)**:
  - `op_score == 3.0` -> `supporting_skills`
  - `op_score != 3.0` -> `opposing_skills` (a holding area for dissent and disagreement, so that wait-and-see and dissenting opinions are not silently dropped and the dissent context survives into the display)

- **When `final_signal` is directional (`strong_buy` / `buy` / `sell` / `strong_sell`)**:
  - Same direction (both bullish or both bearish) and `abs(op_score - final_score) ≤ 1.0` -> `supporting_skills`
  - Opposite direction and `abs(op_score - final_score) ≥ 2.0` -> `opposing_skills`
  - Everything else (`abs(diff) < 2.0` and not same-direction) -> `opposing_skills` (folded into dissent, so no third `neutral_skills` camp appears)

The baseline states explicitly that **`neutral_skills` is not a formal payload field**. Every valid opinion must fall into **exactly one** of `supporting_skills` or `opposing_skills`, and the total of the groups must equal `summary_params.opinion_count`.

### Consensus-level thresholds

The baseline fixes the consensus level as a gradient over the valid sample count:

| valid count | consensus_level | Notes |
| --- | --- | --- |
| 0 | `insufficient` | No evidence to synthesize; final_signal is forced to `hold` with `confidence=0.0` |
| 1 | `insufficient` | A single sample is not a "consensus"; `high` must not be emitted even when it matches final exactly |
| >= 2, `sum(confidence) == 0` | `insufficient` | The valid evidence has zero confidence, so no consensus can be established |
| >= 2, `sum(confidence) > 0` | Proceeds to the aligned_ratio determination | See the next table |

The aligned-ratio determination (valid >= 2 and `sum(confidence) > 0`):

| Condition | consensus_level |
| --- | --- |
| `conflict_severity == "high"` | `low` |
| `aligned_ratio ≥ 2/3` and `conflict_count == 0` (equivalently `conflict_severity == "none"`) | `high` |
| `conflict_severity == "medium"` and `aligned_ratio < 0.5` | `low` |
| Everything else | `medium` |

where `aligned = the number of valid opinions in the same direction as final_signal with a score distance ≤ 1.0` and `aligned_ratio = aligned / len(valid)`.

The baseline forbids a fallback such as `sum(...) or 1.0` that hides a zero weight behind a denominator of 1; a zero weight must go through the `insufficient` branch explicitly and let `final_signal` fall back to `hold`.

### The `strategy_synthesis` payload schema

```json
{
  "final_signal": "hold",                 // canonical signal
  "weighted_score": 3.0,                  // 4 decimal places
  "confidence": 0.72,                     // confidence after the discount
  "original_confidence": 0.80,            // weighted confidence before the discount
  "conflict_count": 0,
  "conflict_severity": "none",            // none | low | medium | high
  "conflicts": [ /* the list of dicts ConflictDetector produced */ ],
  "supporting_skills": [ /* opinion item */ ],
  "opposing_skills":   [ /* opinion item */ ],
  "consensus_level": "high",              // high | medium | low | insufficient
  "summary_key": "strategy_synthesis.no_conflicts",   // the dynamic i18n summary key, decided by consensus and conflict state
  "summary_params": {
    "opinion_count": 2,                   // the valid sample count (the Evidence Chain size)
    "total_opinion_count": 4,             // valid + invalid (the raw input total before partitioning)
    "invalid_opinion_count": 2,           // the Diagnostics length
    "final_signal": "hold",
    "consensus_level": "high",
    "conflict_severity": "none",
    "conflict_count": 0
  },
  "deliberation": {                       // optional; only material conflicts trigger it
    "status": "completed",
    "mode": "multi_round_v4",
    "rounds": 2,
    "agenda": [ /* conflict agenda item */ ],
    "responses": [ /* per-agenda participant response */ ],
    "summary": {
      "resolution_status": "partially_resolved",
      "resolved_conflict_count": 0,
      "unresolved_conflict_count": 1,
      "minority_view_preserved": true,
      "confidence_adjustment": -0.06,
      "confidence_adjustment_reason_key": "deliberation.confidence.high_partially_resolved"
    },
    "round_history": [
      {
        "round": 1,
        "source_mode": "mediator_v0",
        "status": "baseline",
        "changed_response_count": 2,
        "confidence_adjustment": -0.06
      },
      {
        "round": 2,
        "source_mode": "multi_round_v4",
        "status": "accepted",
        "changed_response_count": 1,
        "confidence_adjustment": -0.09
      }
    ]
  },
  "revision_projection": {                // optional; a preview generated only when deliberation exists
    "status": "computed",
    "mode": "preview_only",
    "source_mode": "mediator_v0",
    "projected_signal": "hold",
    "projected_weighted_score": 3.0,
    "projected_confidence": 0.6696,
    "projected_original_confidence": 0.72,
    "projected_conflict_count": 1,
    "projected_conflict_severity": "medium",
    "projected_consensus_level": "low",
    "changed_skill_count": 2,
    "changed_skills": ["trend_v1", "theme_v1"],
    "final_signal_overridden": false
  }
}
```

The opinion item structure (each element of `supporting_skills` / `opposing_skills`):

```json
{
  "skill_id": "trend_v1",
  "agent_name": "skill_trend_v1",
  "signal": "hold",              // canonical
  "confidence": 0.80,            // 4 decimal places
  "reasoning": "...",
  "score_adjustment": 0,
  "conditions_met": []
}
```

The baseline states explicitly that `strategy_synthesis` is **the single authoritative synthesis result produced by SkillAggregator's deterministic algorithm**. The Orchestrator's `_collect_strategy_synthesis()` must prefer the synthesis in `ctx.get_data("skill_consensus")` and may fall back to the `skill_consensus` opinion in `ctx.opinions` only when SkillAggregator produced nothing. **A dashboard returned by the LLM must never overwrite or modify `dashboard.strategy_synthesis`**; when `normalize_dashboard_payload` receives LLM output it should strip the LLM-side `strategy_synthesis` field, so an LLM hallucination cannot pollute the authoritative synthesis.

### Strategy Deliberation v0 (Phase 1.5)

`strategy_synthesis.deliberation` is an optional collaborative-reasoning block, generated only when a medium- or high-severity conflict, or an explicitly critical conflict type, appears. v0 uses the deterministic `mediator_v0`: it calls no LLM, lets no strategy chat freely, modifies no original opinion, and does not recompute `final_signal`. Its job is to turn conflicts into auditable agenda items and record the strategy responses, light revisions, and the reason for the synthesized confidence discount.

Trigger conditions:

- `len(valid_opinions) >= 2`
- and there is a conflict with `severity in {"medium", "high"}`, or a conflict whose type is `directional_opposition` / `high_confidence_dissent`

A v0 revision allows only:

- `unchanged`: the original opinion stands.
- `softened`: lower the confidence only, or turn `strong_buy -> buy` and `strong_sell -> sell`; `buy` / `sell` / `hold` are never reversed and may only have their confidence lowered.

v0 explicitly forbids:

- `reversed`: an opinion must never be reversed.
- Recomputing `final_signal`.
- Introducing multi-round debate, concurrent scheduling, frontend presentation, or a new configuration option.

`deliberation.summary.confidence_adjustment` is only the extra conservative discount `StrategySynthesizer` applies after the original conflict-severity discount. A partially mitigated high conflict defaults to about `-0.06` and an unmitigated one to about `-0.08`; a partially mitigated medium conflict defaults to about `-0.04` and an unmitigated one to about `-0.05`. The field must stay in the payload so a later renderer or web UI can explain why the confidence was discounted further.

### LLM Mediator v1 (Phase 1.6)

`llm_mediator_v1` is an injectable enhancement mode for `StrategyDeliberation`, not the default runtime behavior. A caller can inject an `LLMDeliberationMediator` into `StrategySynthesizer(deliberation_mediator=...)`, which first generates the v0 baseline agenda and then sends the low-sensitivity structured opinions/conflicts/baseline payload to an LLM callable. The LLM may return only a JSON object of the same schema; on plain text, bad JSON, a missing field, ID drift, or an out-of-bounds revision, it must fall back to v0 unconditionally.

The v1 schema guard:

- `agenda` must preserve v0's set of `agenda_id` values; participants must not be added, removed, or replaced.
- `responses` must cover v0's `(agenda_id, skill_id)` set; no non-participating strategy may be added.
- `revision` allows only `unchanged` / `softened`; `reversed` remains forbidden.
- A response the v0 baseline already `softened` must stay `softened`, must not be restored to its original signal, and its `revised_confidence` must not exceed the baseline's verified value.
- A response the v0 baseline left `unchanged` may stay unchanged, or be `softened` further under the same rules; the signal must not be reversed and the confidence must not be raised.
- `summary.confidence_adjustment` must not be more optimistic than the v0 baseline, and a single extra discount is floored at `-0.10`, so the LLM cannot undo the deterministic discount.

When v1 output passes validation, `deliberation.mode="llm_mediator_v1"`; otherwise the `mediator_v0` output stands. v1 still does not call strategy-agent self-review, run multi-round debate, recompute `final_signal`, or add a configuration option.

### Strategy Self-Review v2 (Phase 1.7)

`self_review_v2` is an injectable self-review mode for `StrategyDeliberation`, not the default runtime behavior. A caller can inject a `StrategySelfReviewMediator` into `StrategySynthesizer(deliberation_mediator=...)`, which first obtains the baseline deliberation (either `mediator_v0` or a validated `llm_mediator_v1`), then calls the self-review callable per baseline response by its `(agenda_id, skill_id)`. In future that callable could be executed by the real strategy agents involved in the conflict; the current contract specifies only the input/output and the degradation behavior.

The v2 self-review guard:

- Each baseline response must return its own response JSON and nothing else; it must not modify another strategy's response.
- The returned `agenda_id` / `skill_id` must match the baseline response exactly.
- `revision` still allows only `unchanged` / `softened`; `reversed` remains forbidden.
- When the baseline is already `softened`, it must not revert to `unchanged`, restore the original signal, or raise the baseline `revised_confidence`.
- When the baseline is `unchanged`, it may stay unchanged or be `softened` further under the same rules; the signal must not be reversed and the confidence must not be raised.
- When v2 recomputes the summary from the validated responses, the final `confidence_adjustment` must not be more optimistic than the input baseline.
- If any participant is missing, returns bad JSON, drifts its IDs, modifies something out of scope, or attempts `reversed`, the whole self-review round falls back to the baseline deliberation; mixing in partially valid self-reviews is forbidden.

When v2 output passes validation, `deliberation.mode="self_review_v2"`. v2 still runs a single round, adds no concurrent scheduling, does not recompute `final_signal`, does not change the original opinions, and adds no configuration option.

### Revision Projection v3 (Phase 1.8)

`strategy_synthesis.revision_projection` is an optional preview block that `StrategySynthesizer` computes only when `deliberation` exists. It reads the `responses` that already passed the v0/v1/v2 schema guard, applies the `revision="softened"` responses to a temporary `StrategyOpinion` copy, and previews the new synthesized result with a confidence-weighted score.

The v3 output boundary:

- `revision_projection.mode` is always `preview_only`.
- `source_mode` records the projection's origin: `mediator_v0` / `llm_mediator_v1` / `self_review_v2`.
- `projected_signal` / `projected_weighted_score` / `projected_confidence` describe only the preview after adopting the softened revisions.
- `projected_conflict_count` / `projected_conflict_severity` / `projected_consensus_level` are re-detected on the temporary revised copy and never rewrite the original conflicts.
- `changed_skill_count` / `changed_skills` count only the strategies that were actually softened.
- `final_signal_overridden` must always be `false`, making it explicit that v3 does not override the authoritative final signal.

v3 explicitly forbids:

- Writing `projected_signal` back to the top-level `final_signal`.
- Writing `projected_weighted_score` back to the top-level `weighted_score`.
- Writing `projected_confidence` back to the top-level `confidence`.
- Emitting an empty projection when there is no `deliberation`.
- Accepting free text, a reversed signal, or an added strategy response that never passed the v0/v1/v2 guard.

At the projection entrypoint, v3 also re-checks `original_signal`, the allowed softened signal, and the `revised_confidence` upper bound, so even a caller-injected custom result that never used the built-in mediator guard cannot apply a more aggressive response to the temporary opinion copy.

### Configurable Multi-Round Deliberation v4 (Phase 1.9)

`multi_round_v4` is an injectable multi-round enhancement mode for `StrategyDeliberation`, not the default runtime behavior. A caller can inject a `MultiRoundDeliberationMediator` into `StrategySynthesizer(deliberation_mediator=...)` and configure it through constructor arguments:

- `fallback`: the first-round baseline mediator, which may be `mediator_v0`, `llm_mediator_v1`, or `self_review_v2`.
- `max_rounds`: the total round cap, in the range `1–4`; `1` is equivalent to keeping the fallback baseline only.
- `stop_when_stable`: whether to stop early when a round changes no response; on by default.
- `round_completion(round_index, messages)`: the callable for the next round's structured revision, which may return only JSON of the same schema.

The v4 round guard:

- Each round must preserve the previous round's `agenda_id` set and `(agenda_id, skill_id)` response set; participants must not be added, removed, or replaced.
- `revision` still allows only `unchanged` / `softened`; `reversed` remains forbidden.
- A response the previous round already `softened` may not return to `unchanged`.
- A response the previous round already `softened` may not change its `revised_signal` or raise its `revised_confidence`.
- A response the previous round left `unchanged` may stay `unchanged` or be `softened` under the same rules.
- `summary.confidence_adjustment` may not be positive and may not be more optimistic than the previous round; the per-round floor is still clamped to `-0.10` by the v1 guard.
- On bad JSON, ID drift, an out-of-bounds revision, an undone softening, or a raised confidence in any round, the later rounds stop and the previous verified result is returned; if round 2 itself fails, the fallback baseline stands.

The v4 output:

- When at least one extra round of revision is accepted, `deliberation.mode="multi_round_v4"`.
- `deliberation.rounds` records the total number of rounds actually accepted.
- `deliberation.round_history` records the `round`, `source_mode`, `status`, `changed_response_count`, and `confidence_adjustment` of the baseline and of each accepted round.
- v4 still does not recompute the top-level `final_signal`, change the original opinions, or overwrite the top-level `weighted_score` or `confidence` directly; the top-level confidence only keeps reading the final `deliberation.summary.confidence_adjustment` for a conservative discount.

### The key invariants

The baseline's semantic boundary converges into nine invariants. Every Phase N implementation must satisfy all nine at once, and violating any one is a contract breach.

| ID | Invariant | Scenario | Expectation |
| --- | --- | --- | --- |
| I-1 | Evidence Chain exclusivity | Any module reading the Evidence Chain | Every entry must satisfy `is_valid_strategy_signal == True`; an invalid opinion must never appear |
| I-2 | No silent conversion | A missing or unrecognizable signal | It goes to Diagnostics and must not be converted to `hold` and mixed into the Evidence Chain or a bucket |
| I-3 | Zero evidence -> insufficient | Any valid signals but `sum(confidences) == 0`, or a valid count of 0 | `final_signal="hold"`, `weighted_confidence=0.0`, `consensus_level="insufficient"`; emitting `strong_sell` or any directional signal is forbidden |
| I-4 | Single sample -> insufficient | Exactly 1 valid opinion | `consensus_level="insufficient"`, even when it matches final exactly |
| I-5 | Hold-final consistency | `final_signal == "hold"` with >= 2 valid hold opinions | Every hold opinion must go into `supporting_skills`; the relationship between consensus_level and the `supporting_skills` count must be self-consistent (at `high`, supporting covers >= 2/3) |
| I-6 | Payload and renderer semantics agree | The value of `dashboard.strategy_synthesis` | The actual text of all three renderers (Markdown / Notification / History) must match the payload exactly, with no self-contradictory combination such as "共识度：高 + 支持策略：无" |
| I-7 | Canonical-first scoring | Scoring, weighting, conflict detection, and grouping inside Aggregator / ConflictDetector / Synthesizer | They must use the canonical lowercase value returned by `normalize_strategy_signal()`; looking up `strategy_signal_score` with a raw string such as uppercase `"BUY"` or an alias is forbidden |
| I-8 | Multi-language empty placeholder | Display when `supporting_skills` / `opposing_skills` is empty | It must go through `labels.none_label` keyed by `report_language`; hard-coding the literals `"无"`, `"None"`, or `"없음"` in code or a template is forbidden |
| I-9 | Deliberation is monotonically conservative | v1/v2/v4 revise on top of the previous layer's verified baseline, and v3 applies the projection | An existing `softened` must not be undone, the original signal must not be restored, and the baseline revised confidence and baseline confidence adjustment must not be raised; an out-of-bounds result falls back to the previous layer |

## Phase 1 semantic convergence (this PR's delivery scope)

Phase 1 is the first code implementation of the baseline contract. Phase 1 **adds no contract clause**; it only lands the boundaries the baseline already fixed into concrete code: Orchestrator partitioning, Aggregator/Synthesizer computation convergence, DecisionAgent prompt convergence, Disagreement convergence, consistency across the three renderers, and E2E counter-example coverage.

The entrypoints Phase 1 touches:

- `src/agent/protocols.py`: adds `is_valid_strategy_signal()` as the single source of truth, and `normalize_strategy_signal()` keeps the invalid state flag.
- `src/agent/skills/engine.py`: `StrategyEngine.process()` performs the single authoritative partitioning through `partition_only()`, then `process_partition()` drives aggregation and synthesis; valid opinions stay in the Evidence Chain and invalid ones are written to Diagnostics.
- `src/agent/orchestrator.py`: calls `_run_strategy_engine(ctx)` before the DecisionAgent runs; the timeout and budget-skip early-exit paths call `_apply_partition_fallback(ctx)`, which partitions without synthesizing so no invalid opinion flows back into the evidence chain.
- `src/agent/skills/aggregator.py`: `StrategyEngine` hands `valid_skill_opinions` to `SkillAggregator.calculate()`; the arithmetic uses valid opinions only, and `valid_weight_sum == 0` goes through the `insufficient` branch explicitly.
- `src/agent/skills/synthesis.py`: `ConflictDetector` / `StrategySynthesizer` compute on canonical signals; `_group_opinions()` implements §"Dynamic bipartite grouping"; `_consensus_level()` implements §"Consensus-level thresholds"; `summary_params` is completed with `invalid_opinion_count` / `total_opinion_count`.
- `src/agent/agents/decision_agent.py`: `build_user_message()` consumes `ctx.opinions` directly with no second filter, and reports the `ctx.meta["invalid_opinions"]` count honestly in the prompt.
- `src/agent/disagreement.py`: `build_agent_disagreement_summary()` consumes `ctx.opinions` directly (StrategyEngine has already partitioned and the Orchestrator has written the result back), so invalid opinions never appear in the `bullish_agents` / `bearish_agents` / `neutral_agents` buckets.
- `src/services/report_renderer.py`, `templates/report_markdown.j2`, `src/notification.py`, `src/services/history_service.py`: read `strategy_synthesis.supporting_skills` / `opposing_skills` / `consensus_level` / `summary_params.invalid_opinion_count`; an empty list is rendered through `labels.none_label`; `neutral_skills` is no longer consumed.
- `src/report_language.py`: `labels.none_label` is complete across zh/en/ko, as are the consensus and diagnostic-count strings.
- `tests/test_multi_agent.py`: adds the E2E-A..G counter-example matrix, asserting the whole chain from SkillAgent input -> StrategyEngine partitioning/aggregation -> DecisionAgent prompt -> dashboard payload -> actual renderer text.

Phase 1 changes no `AgentOpinion` field, no API response structure, no database schema, adds no configuration option, and does not change how existing skills run.

## Phase 2 concurrent scheduling

Phase 2 adds concurrent scheduling of 2-4 strategies plus stage scheduling, under the Phase 1/1.5/1.6/1.7/1.8/1.9 contract only:

- `src/agent/skills/scheduler.py::AgentSkillScheduler` runs the specialist skill agents concurrently on a thread pool. Each skill runs on its own `AgentContext` copy, and a separate `copy_context()` propagates `ContextVar` state such as the target date frozen by the main pipeline into the worker. The main thread merges the structured opinions in routing order, so several skills never write the shared `ctx.opinions` at once.
- The specialist final entrypoint selects at most 4 strategies. `AGENT_SKILL_CONCURRENCY` controls how many workers run at once, defaulting to `3` in the range `1–4`. At the default, the fourth strategy enters the next concurrency wave rather than being dropped silently by the routing layer.
- `AGENT_SKILL_AGENT_TIMEOUT_S` remains the per-skill independent timeout cap; when the pipeline's total budget is enabled, `_run_stage_agent()` still takes the smaller of the pipeline's remaining budget and the skill's own cap.
- A single skill timing out or raising takes the Diagnostics path (`reason="skill_timeout"` / `"skill_error"`) into `ctx.meta["invalid_opinions"]`, blocking neither the other skills nor the main flow.
- Phase 2 does not change the baseline Evidence Chain / Diagnostics separation principle, the camp semantics, the consensus thresholds, or the `strategy_synthesis` payload schema.
- Phase 2 does not change renderer presentation; a scheduler timeout, error, or no-opinion result, and a failed signal validation, all land in StrategyEngine's authoritative Diagnostics, and `invalid_opinion_count` / `total_opinion_count` cover those failed skills.
- `ctx.meta["skill_scheduler"]` is a runtime diagnostic only, recording the scheduling mode, the concurrency, the per-skill timeout, the scheduled count, the completed count, and the invalid count; it must never take part in the synthesized score.

## Phase 3 full frontend multi-language presentation (out of scope for this PR)

Phase 3 only adds full multi-language presentation of `strategy_synthesis` to the frontends (`apps/dsa-web/`, `apps/dsa-desktop/`) on top of Phase 2:

- The web report detail page shows `final_signal` / `consensus_level` / `supporting_skills` / `opposing_skills` / `conflicts` / `invalid_opinion_count`.
- The desktop app reuses the web presentation logic.
- The multi-language label table reuses the existing zh/en/ko labels in `src/report_language.py`; the frontend only projects them and never redefines them.
- Phase 3 does not change the baseline contract, add a payload field, or add an API endpoint.

## Phase 4 the Skill Outcome weight feedback loop

Phase 4 adjusts relative runtime weights within the same `CONTRACT_VERSION = "1.0"` using only real, attributable
individual Skill Outcomes. Weight statistics keep being bucketed strictly by
`skill_id + horizon + engine_version`; each horizon must satisfy
`evaluated >= 30` on its own, and stitching samples across horizons, skills, or engine versions to unlock a weight is forbidden.

A single sufficient bucket shrinks its hit rate with a symmetric `Beta(15, 15)` prior:

```text
n = hit + miss
posterior_hit_rate = (hit + 15) / (n + 30)
direction_score = 2 * posterior_hit_rate - 1
unable_rate = unable / (evaluated + observational + unable)
bucket_score = clamp(direction_score - 0.25 * unable_rate, -1, 1)
evidence_strength = n / (n + 30)
```

`pending` does not enter the unable-rate denominator, and `observational` / `unable` cannot make up the
evaluated threshold. The current opinions carry no trustworthy horizon, so only buckets that each already meet the threshold
are combined through an evidence-strength-weighted model average:

```text
combined_score =
    sum(bucket_score * evidence_strength)
    / sum(evidence_strength)
performance_factor = exp(ln(1.2) * combined_score)
effective_weight = opinion.confidence * performance_factor
```

`performance_factor` is confined to the multiplicatively symmetric interval `[1 / 1.2, 1.2]`. With no sufficient
bucket, a failed statistics read, a corrupt bucket, a non-finite value, or
`AGENT_SKILL_AUTOWEIGHT=false`, it must return the neutral factor `1.0`; a weighting failure must never interrupt
the analysis. The runtime no longer passes off `BacktestService`'s global or non-attributable summary as skill
performance. This stage only reads already-persisted Outcomes and adds no evaluator pipeline, API,
or scheduled trigger.

`avg_directional_return_pct` is still a read-only descriptive metric and takes no part in weighting. With a mean but
no dispersion or standard error, putting it straight into the formula would manufacture false precision; to use returns
later, a versioned risk-adjusted return contract has to come first.

Phase 4 does not change the baseline canonical signal, validity determination, consensus thresholds, or camp semantics;
a weight change affects only `weighted_score` and `confidence`, never the `consensus_level`
determination path. `AGENT_ARCH=single` does not go through `SkillAggregator` and stays compatible.

## Consumer inventory

The baseline's seven consumers must divide the work strictly as the table below says, and must never reach across to consume each other's internal data.

### SkillAgent

Each skill produces an `AgentOpinion` through `src/agent/skills/skill_agent.py`. The baseline allows a skill to emit any signal literal (uppercase, an alias, or a `Signal` enum), and allows a skill with insufficient data to emit `signal=None` or a missing field — those cases are handled by downstream partitioning, and a skill never filters itself.

### StrategyEngine / Orchestrator (partitioning and wiring)

In Phase 1 the Orchestrator calls `_run_strategy_engine(ctx)` before the DecisionAgent runs:

- `StrategyEngine.partition_only()` walks every opinion whose `agent_name` matches `is_skill_agent_name()` and keeps the canonical signal via `normalize_strategy_signal()`.
- Invalid opinions are removed from the Evidence Chain and written to `StrategyResult.invalid_records`, which the Orchestrator then assigns to `ctx.meta["invalid_opinions"]`.
- `StrategyEngine.process_partition()` hands only `valid_skill_opinions` to the Aggregator/Synthesizer; the resulting consensus opinion and `skill_consensus` are written back to the context once by `_run_strategy_engine()`.
- When a timeout or budget skip happens before the full engine runs, `_apply_partition_fallback()` reuses `partition_only()` to complete partitioning and the Diagnostics write-back only, generating no consensus.

The baseline declares `StrategyEngine.partition_only()` the **single authoritative partitioning implementation**. The Aggregator, DecisionAgent, and Disagreement no longer define their own valid/invalid rules and consume the engine's converged Evidence Chain directly; the old wrapper retained in the Orchestrator exists only for compatibility with existing internal callers and tests and is not part of the normal runtime path.

### SkillAggregator

At runtime `StrategyEngine` calls `SkillAggregator.calculate(valid_skill_opinions)`. The Aggregator converts the input into internal `StrategyOpinion` objects, uses valid opinions only in the arithmetic, and looks up `strategy_signal_score` strictly with canonical signals; even when the compatibility entrypoint receives unpartitioned input, an invalid opinion must never take part in the weighting. Three states go through the `insufficient` branch explicitly:

- `len(valid) == 0`: `final_signal="hold"`, `confidence=0.0`.
- `len(valid) == 1`: `final_signal` follows that opinion's canonical signal, but `consensus_level="insufficient"`.
- `len(valid) ≥ 2` with `sum(confidence) == 0`: `final_signal="hold"`, `confidence=0.0`.

The resulting `strategy_synthesis` is packed by `StrategyEngine` into `StrategyResult.skill_consensus_data` and then attached by the Orchestrator through `ctx.set_data("skill_consensus", {...})`; `_collect_strategy_synthesis()` reads it from there as the dashboard's authoritative synthesis source.

### DecisionAgent

`build_user_message()` reads the opinions from `ctx.opinions` into the prompt. Because the Orchestrator's partitioning already guarantees that `ctx.opinions` holds only valid opinions, the DecisionAgent **no longer** filters a second time. The prompt's "另有 N 个策略解析失败" display reads the `ctx.meta["invalid_opinions"]` length directly.

The dashboard JSON the DecisionAgent emits must not overwrite `dashboard.strategy_synthesis`; if the LLM response contains that field, `normalize_dashboard_payload()` must strip it and keep the Aggregator-side authoritative synthesis.

### Disagreement

`build_agent_disagreement_summary()` builds the `bullish_agents` / `bearish_agents` / `neutral_agents` buckets from `ctx.opinions` only. Because `ctx.opinions` already holds valid opinions only, invalid opinions never appear in the three buckets and are never silently defaulted to `hold` by `_normalize_signal()`.

The `ctx.meta["invalid_opinions"]` length is exposed separately to the DecisionAgent prompt as `disagreement_summary.diagnostics.invalid_count`, for the LLM to reference when generating the `data_limitations` text.

### The three renderers

Every renderer reads `dashboard.strategy_synthesis` for display:

- `final_signal` / `consensus_level` / `conflict_severity` / `conflict_count`.
- `supporting_skills` / `opposing_skills` (`neutral_skills` is no longer consumed).
- `summary_params.invalid_opinion_count` -> displayed per language as "另有 N 个策略无效/解析失败".

An empty-list placeholder must be rendered through `labels.none_label` (keyed by `report_language`). The final text of all three renderers must match the payload exactly, with no internal contradiction such as "共识度：高 + 支持策略：无".

History records and external callers may still carry the looser shape from before the contract landed. All three renderers must first run `normalize_strategy_synthesis_payload()` to treat a non-dict top-level value as missing and filter out non-dict strategy/conflict list items; `strategy_invalid_opinion_count()` reads the diagnostic count uniformly, converting narrowly only for a plain decimal positive-integer string and degrading any other bad value to 0. Keeping a parallel hand-written read in History, Notification, or a template is forbidden.

### Diagnostics

`ctx.meta["invalid_opinions"]` may be consumed only in these three ways:

- Logs: record `agent_name` / `raw_signal` / `reason` for troubleshooting.
- The DecisionAgent prompt: as the count behind "另有 N 个策略解析失败".
- Renderers: as the source of `summary_params.invalid_opinion_count`.

Letting the `confidence` inside Diagnostics take part in any weighting is forbidden, as is pushing `raw_signal` back into `ctx.opinions`.

## The counter-example matrix

Phase 1 must provide the E2E counter-example coverage below. E2E is defined as: in through SkillAgent input, across Orchestrator partitioning -> SkillAggregator -> DecisionAgent prompt -> the final dashboard payload -> the actual text output of all three renderers. Passing off a local unit test as E2E is forbidden.

| ID | Input | Assertions | Invariants covered |
| --- | --- | --- | --- |
| E2E-A | 1 valid `buy/0.8` + 2 invalid `moon/0.9` | (1) The DecisionAgent prompt contains no `moon` literal, no invalid `agent_name`, and no `0.9` context; (2) `ctx.meta["invalid_opinions"]` has length 2; (3) `strategy_synthesis.summary_params.opinion_count == 1` and `invalid_opinion_count == 2`; (4) `consensus_level == "insufficient"`; (5) all three renderers output "另有 2 个策略无效/解析失败" (per language); (6) the hold/0.9 that moon would have become appears in none of `disagreement_summary.bullish_agents` / `neutral_agents` / `bearish_agents` | I-1, I-2, I-4 |
| E2E-B | 2 valid `hold/0.0` | `final_signal="hold"`, `weighted_confidence=0.0`, `consensus_level="insufficient"`, and **never** `strong_sell`; every renderer shows "证据不足（观望）" (per language) | I-3 |
| E2E-C | 1 valid `buy/0.0` + 1 valid `hold/0.0` | The mixed zero-weight case: `final="hold"`, `confidence=0.0`, `consensus="insufficient"`, no `strong_sell` | I-3 |
| E2E-D | 2 valid `hold/0.8` | (1) `final_signal="hold"` and `consensus_level="high"`; (2) `supporting_skills` has length 2 and `opposing_skills` length 0; (3) the actual text of all three renderers contains both the high-consensus label and both skill names, with no "支持策略：无" paired with "共识度：高" | I-5, I-6 |
| E2E-E | 1 valid `buy/0.8` + 9 invalid | `consensus_level="insufficient"` (**never** high); all three renderers show "基于 1 个有效策略判断（另有 9 个策略无效/解析失败）" | I-4, I-6 |
| E2E-F | 2 valid opinions, one with `signal="BUY"` (uppercase) | The Aggregator's internal `weighted_score` looks the score up with the canonical `buy` (4.0) and **must not** get 0 from a failed uppercase lookup; `strategy_synthesis.final_signal` emits canonical lowercase | I-7 |
| E2E-G | Empty `supporting_skills` with `report_language="en"` | No four-renderer output contains the Chinese `"无"`; it shows `"None"` (or the matching language's `labels.none_label`) | I-8 |

## Source anchors

| Area | Anchor |
| --- | --- |
| Signal normalization and validity determination | `src/agent/protocols.py::normalize_strategy_signal`, `is_valid_strategy_signal`, `strategy_signal_score` |
| StrategyEngine partitioning and the synthesis facade | `src/agent/skills/engine.py::StrategyEngine.partition_only`, `process`, `process_partition` |
| Orchestrator wiring and early-exit partitioning | `src/agent/orchestrator.py::_run_strategy_engine`, `_apply_partition_fallback` |
| SkillAggregator | `src/agent/skills/aggregator.py::SkillAggregator.calculate`, `aggregate` (the compatibility entrypoint) |
| ConflictDetector / StrategySynthesizer | `src/agent/skills/synthesis.py::ConflictDetector`, `StrategySynthesizer` |
| The DecisionAgent prompt | `src/agent/agents/decision_agent.py::build_user_message` |
| Disagreement | `src/agent/disagreement.py::build_agent_disagreement_summary` |
| Dashboard synthesis mounting | `src/agent/orchestrator.py::_collect_strategy_synthesis` |
| Renderer - Markdown | `src/services/report_renderer.py::render`, `templates/report_markdown.j2` |
| Renderer - Notification | `src/notification.py` (the strategy synthesis line rendering) |
| Renderer - History | `src/services/history_service.py` (the strategy synthesis block in the history detail) |
| Multi-language and loose-payload hardening | `src/report_language.py::_REPORT_LABELS`, `normalize_strategy_synthesis_payload`, `strategy_invalid_opinion_count`, `localize_strategy_synthesis_summary`, `labels.none_label` |
| The E2E counter-example matrix | `tests/test_multi_agent.py::TestP1SemanticConvergence`, `TestStrategyEngineE2E` |

## Compatibility and rollback

### Deprecated behavior (after Phase 1 landed)

| Old behavior | After the contract |
| --- | --- |
| `normalize_strategy_signal` silently returning `default="hold"` for an unknown signal and mixing it into the evidence chain | An unknown signal must go to Diagnostics and must never appear in `ctx.opinions` |
| The Aggregator hiding a zero weight with `sum(...) or 1.0` | `valid_weight_sum == 0` is checked explicitly and goes through the `insufficient` branch with `final_signal="hold"` |
| A renderer hard-coding `"无"` for an empty camp | It is looked up per language through `labels.none_label` |
| The DecisionAgent filtering invalid opinions itself at the prompt layer | Partitioning happens in the Orchestrator and the DecisionAgent consumes `ctx.opinions` directly |
| `strategy_synthesis` emitting `neutral_skills` | After the contract the field does not exist and renderers no longer consume it |
| An LLM dashboard overwriting `strategy_synthesis` | The authoritative synthesis comes from the Aggregator, and the LLM-side field is stripped by `normalize_dashboard_payload` |

### Added fields

- `ctx.meta["invalid_opinions"]`: the Diagnostics holding area (structure in "Separating the Evidence Chain from Diagnostics").
- `strategy_synthesis.summary_params.invalid_opinion_count`: the Diagnostics length.
- `strategy_synthesis.summary_params.total_opinion_count`: the raw total of valid + invalid.

### Rollback options

| Method | Effect | What it cannot do |
| --- | --- | --- |
| Reverting the Phase 1 commits | Removes Orchestrator partitioning, Aggregator/Synthesizer convergence, and the renderer consistency changes | It cannot roll back only some invariants; the contract converges as a whole |
| Keeping the contract document and reverting the code | Keeps the baseline text and returns to the old behavior | Documentation value only, with no runtime benefit; not recommended |
| Rolling back Phase 2/3/4 independently | Each phase's runtime changes roll back independently | The baseline cannot be rolled back; every phase must always satisfy the baseline invariants |

The baseline adds no configuration option, so there is no env-level rollback switch. That is deliberate: a contract boundary should hold constantly in code and never be weakened through an environment variable.
