# Workflow Analytics Design

## Purpose

Design a workflow analytics capability that analyzes past agent session traces
and answers one practical question: how did skills and Knowledge Base (KB)
content affect the observable workflow?

The existing `services/codex-history-analyzer` service is the first
implementation layer. It focuses on one selected Codex session at a time:
history discovery, trace reconstruction, operation scoring, context-pressure
visualization, compaction-quality analysis, and lightweight period summaries.
Future workflow analytics should reuse that foundation for deeper cross-session
cohort reports rather than replace it.

The skill should produce an easy-to-read scorecard, not just raw counters. Every
major number should include a denominator, percentage, rate, or delta so the
reader can immediately see whether a result is meaningful.

## Primary Questions

- Which skills are being used, and how strong is the evidence that they were
  actually used?
- Does KB usage change token usage, session duration, search/tool volume,
  hypothesis timing, or workflow path?
- Does token usage become more efficient, or does it only increase total cost?
- Which metrics are directly observable from session traces, and which still
  need better event logging or detection patterns?

## Canonical Scorecard

The report should keep this numbered structure for session-derived workflow
analytics:

```text
0 Token Usage
1 Tool And Search Calls
2 Session Duration
3 Skill And KB Interaction
4 Hypothesis Signal
5 Workflow Path
```

Each section should compare the same system rows when data exists:

```text
No KB
Skill/Workflow Only
KB Referenced
KB Read
KB Read + Structured Workflow
```

## Single-Session Workflow Card

The same numbered structure is useful even before there is enough data for a
cross-session comparison. In single-session mode, each row should be an
observation about the selected chat, not a delta or population-level claim:

- `0 Token Usage`: token samples, context-window pressure, peaks, and drops
  around compaction events.
- `1 Tool And Search Calls`: ordered tool, MCP, and skill operations with their
  outputs linked back to the initiating action.
- `2 Session Duration`: elapsed timeline reconstructed from event timestamps
  when usable timestamps exist.
- `3 Skill And KB Interaction`: visible skill/KB mentions, reads, distinctive
  paths, or tool use inside the trace.
- `4 Hypothesis Signal`: candidate root-cause, decision, or next-step moments
  visible in assistant messages or reasoning.
- `5 Workflow Path`: the observed sequence of human turns, AI reasoning, tool
  execution, validation, compaction, interruption, and completion.

Single-session analytics can diagnose one workflow's quality and evidence
chain. They cannot claim that a skill or KB changed overall behavior unless the
same metrics are later compared across comparable cohorts.

UI integration rule: the single-session workflow card should live inside the
existing selected-chat dashboard. It should summarize the currently selected
chat above or beside the existing timeline, operation-score, trace-ledger,
context-window, and compaction panels. The new 0-5 rows should reuse the same
normalized `events`, `context`, `compactions`, `epochs`, and scoring metadata
that already drive those panels. They should not introduce a separate report
page, a second navigation model, or another raw-trace viewer.

The existing detailed panels remain the drill-down for the 0-5 rows:

- Token row drills into the context-window and compaction views.
- Tool/search row drills into the weighted timeline and trace ledger.
- Duration row drills into the same ordered event timeline.
- Skill/KB row drills into matched evidence events and linked tool/resource
  operations.
- Hypothesis row drills into the first detected candidate decision or root-cause
  event.
- Workflow-path row drills into the stage sequence derived from the same event
  list.

## Current Period Summary Layer

The service now also exposes small cross-session period views. These are not a
full KB cohort-analysis system yet; they are aggregate summaries over the same
normalized session events used by the single-session page.

The left navigation should expose exactly these period entry points above the
project list:

- `This week`
- `Last week`
- `Last 2 weeks`

These period pages should load only after the user clicks one of the period
options. Selecting a project or session should return the user to the normal
single-session view.

The period summary page should keep the same 0-5 row names and meanings as the
single-session workflow card:

- `0 Token Usage`
- `1 Tool And Search Calls`
- `2 Agent Time`
- `3 Knowledge Source Usage`
- `4 First Hypothesis / Decision`
- `5 Workflow Path`

The current comparison view should focus on `This week` versus `Last week`.
Its primary layout should show `Last week`, `This week`, and `Difference`
together for each row, rather than only showing the subtraction result. The
comparison page may be longer and more spacious than the session page so the
viewer can inspect session mix, tool usage, skill usage, runtime metadata, and
repo changes without compressed cards.

Implemented comparison context includes:

- Session counts and sessions unique to each period.
- Token totals and model-level token usage.
- Tool/search bucket differences.
- Knowledge-source and concrete skill-read differences.
- Agent timing, tool wait, and first-tool delay deltas.
- Hypothesis/decision signal deltas.
- Workflow stage and project-mix differences.
- Runtime metadata differences, including CLI version, originator, source,
  thread source, and model provider when available.
- Skill catalog differences from installed skill names.
- Relevant `skills/` and `services/codex-history-analyzer/` Git commits for
  each period.
- Current working-tree differences in those same skill/service paths.

This comparison explains what changed between two weeks, but it still cannot
prove a skill or KB caused an outcome improvement without a stronger cohort
design and comparable task families.

## Data Sources

The workflow analytics implementation must be read-only by design. It must not
mutate sessions, skill folders, CRs, review databases, KB files, source
artifacts, or other systems being measured. Normalization outputs and derived
metrics must be written only to explicit report output artifacts or local
analysis caches outside the input roots.

Expected inputs:

- Agent session traces under a configurable sessions root, including Codex
  `sessions/` and `archived_sessions/`.
- Optional session index metadata, such as chat titles and project paths.
- Browser-imported JSON, JSONL, NDJSON, or plain-text traces for local review.
- Parser or adapter configuration needed to normalize supported session formats.
- Optional pattern configuration for detecting skill/KB references, search-like
  tool calls, hypothesis-like phrases, and workflow stages from session events.

Session traces are the source of truth for this skill. The core metrics should
come directly from session events:

- Token usage.
- Tool and search-like call counts.
- Session duration.
- Whether the session read or referenced skill/KB content.
- Whether the session produced a hypothesis-like phrase.
- Approximate workflow path.

The current active session should be excluded by default from aggregate reports
so report numbers do not change while the report is being generated. The
dashboard may still allow an explicit single-session inspection when the user
selects that chat.

Local scoring caches are allowed when they are clearly derived artifacts, kept
outside the input session roots, and safe to delete. They must not be treated as
source-of-truth data.

## Existing Codex History Analyzer Capabilities

`services/codex-history-analyzer` already provides these capabilities and should
be treated as the baseline for the single-session layer:

- Read-only discovery of Codex JSONL history from `CODEX_HISTORY_HOME`.
- Inclusion of both `sessions/` and `archived_sessions/`.
- Project and chat selection grouped by session `cwd`, with names enriched from
  session-index metadata when available.
- Normalized event reconstruction from Codex records.
- Tool-call to tool-output correlation, including incomplete or unknown-output
  calls that remain visible instead of being silently dropped.
- Deterministic operation scoring from explicit success/failure evidence,
  validation signals, repeated failures, human corrections, human confirmations,
  and task-completion events.
- Optional QGenie scoring for AI events, with bounded requests, persistent cache,
- Optional QGenie semantic review as a separate layer. The current direction is
  block-level review rather than replacing deterministic event scores.
- Positive, negative, and signed-overall score aggregation by operation category.
- Weighted decision timeline, list-mode timeline, and score-aware trace ledger
  with owner and score filters.
- Expandable trace-ledger rows with full title, description, score reason,
  score breakdown, evidence, context, and raw event JSON.
- Token/context-pressure samples from `token_count` events.
- Token usage split by model when a session switches models, with separate
  input, output, read-cache, write-cache, reasoning, total, and percent columns.
- Tool/search buckets for local text search, web search, CodeIndex retrieval,
  Doc RAG retrieval, issue/CR/Gerrit search, other MCP retrieval, other
  retrieval, temporary or inline scripts, validation/build/test, edit/write/deploy,
  and other tool calls.
- Knowledge-source buckets for skill reads, memory reads, Doc RAG queries,
  CodeIndex queries, local documentation reads, and other KB/MCP sources.
- Agent-time metrics from completed turn boundaries, with wall span, tool wait,
  non-tool active time, first-tool delay, open turns, and timestamp fallback.
- Context compaction detection, epoch splitting, compression-efficiency
  calculation, and optional QGenie compaction-quality scoring.
- Compaction-quality dimensions for goals/requirements, decisions/constraints,
  validated achievements, open work, exact identifiers, and factual consistency.
- Retained, missing, and distorted fact lists for each analyzed compaction.
- Browser JSON export for the selected project/chat analysis.
- Browser import of JSON, JSONL, NDJSON, and plain-text traces.
- Period summaries for `This week`, `Last week`, and `Last 2 weeks`.
- A `This week` versus `Last week` comparison page that includes session mix,
  scorecard deltas, tool/knowledge/model/environment deltas, and skill/service
  repo-change context.
- Linux and Windows installation flows, loopback default binding, explicit remote
  binding, optional Basic Auth, health check endpoint, and user-service startup.

## Core Data Model

The implementation should keep the internal model small and explicit:

| Object | Purpose |
|---|---|
| `trace_adapter` | Parser that converts one agent trace format into normalized session events |
| `session_fragment` | One raw trace file, used for parse health and audit links |
| `session` | Merged task/session view used for metrics |
| `project_index` | Project/chat grouping derived from `cwd`, session IDs, and optional title metadata |
| `event` | Normalized timeline item with time, actor kind, type, title, context, source, score, confidence, and scorer |
| `action_group` | Linked reasoning/message, tool call, and tool result used to evaluate one operation |
| `operation_score` | Positive, negative, and signed evidence score plus reason, evidence quote, confidence, and scorer |
| `context_sample` | Token and context-window sample, optionally marked as related to a compaction |
| `context_epoch` | Range between the start of a session and each compaction boundary, or between compactions |
| `compaction_result` | Retention, continuity, compression, effectiveness, retained/missing/distorted facts, and confidence for one compaction |
| `qgenie_block_review` | Optional semantic review for one session block, with block range, covered event counts, local score, QGenie score, reasons, workflow observation, recommendation, representative events, confidence, and scorer |
| `skill_signal` | Skill name, evidence level, and evidence source |
| `workflow_signal` | Search calls, tool calls, hypothesis markers, and stage transitions |
| `kb_cohort` | KB usage inferred from session evidence |
| `metric_result` | Numerator, denominator, rate, delta, confidence, and short read |

Keep raw logs and prompts out of normal aggregate reports. The single-session
dashboard may expose full trace detail because its purpose is audit and
diagnosis, but deployments must treat that UI as sensitive.

## Skill-Use Evidence Levels

The skill should avoid counting every mention as real usage. Each session should
be classified using evidence levels:

| Level | Meaning | Use in Metrics |
|---|---|---|
| Available | Skill appeared in an environment list | Inventory only |
| Referenced | User or assistant mentioned a skill or KB item | Weak usage signal |
| Opened | A skill or KB file/resource was read during the session | Usage signal |
| Observed | Skill scripts, paths, tools, or distinctive workflow were used | Strong usage |
| Stage-qualified | Enough timestamped events exist to score workflow stage metrics | Metric denominator |

Usage comparisons should use `opened`, `observed`, or `stage-qualified`
evidence, not `available` or casual mentions.

## Metric Definitions

Metric language depends on scope:

- Single-session mode reports observations, timelines, scores, and evidence
  gaps for one chat.
- Cross-session mode reports denominators, rates, cohort deltas, and confidence
  labels.

### 0 Token Usage

Token usage should measure efficiency, not only cost.

Report:

- Total tokens.
- Token-bearing sessions and percent of all sessions.
- Tokens per token-bearing session.
- Tokens per completed turn.
- Tokens per search-like call.
- Input, cached input, output, and reasoning tokens when available.
- Cached-input share.
- Context-window peak, minimum, and compaction-related drops when token-count
  events expose the model window.
- Delta versus `No KB` for every KB cohort.

Accounting rule: `cached_input_tokens` and `cache_write_input_tokens` are input
breakdowns, not additional buckets to add on top of `input_tokens`. Display them
separately and compute cache share against input tokens.

Interpretation rule: higher token usage is not automatically bad. A KB workflow
can be useful if it spends more tokens but reaches a hypothesis faster, reduces
search/tool load, or produces a clearer workflow path.

### 1 Tool And Search Calls

Tool and search call metrics should measure how much work the session performed
and how efficiently the agent moved through available evidence.

In single-session mode, tool calls should be shown as linked action groups:
reasoning or assistant message, tool invocation, tool output, inferred outcome,
and score rationale. Unknown or missing outputs remain visible with neutral or
low-confidence evidence.

Count search-like work separately:

- `grep`
- `rg`
- `find`
- Code index queries
- Doc RAG queries
- Issue-tracker searches when identifiable in the session trace
- Web or MCP searches when identifiable

The single-session UI should show these as separate retrieval buckets instead
of one opaque search total:

- Local text search: `rg`, `grep`, `find`, or equivalent local file search.
- Web search.
- CodeIndex retrieval.
- Doc RAG retrieval.
- Issue, CR, or Gerrit search.
- Other MCP retrieval.

Non-retrieval tool calls should remain visible in adjacent buckets such as
skill, validation/build/test, edit/write/deploy, and other tool calls.

Report:

- Total tool calls.
- Tool calls per session.
- Tool calls per completed turn.
- Search-like calls per session.
- Search-like calls per completed turn.
- Search-like calls per minute.
- Tokens per search-like call.
- Delta versus `No KB`.
- Search calls saved or added per 100 sessions.

Interpretation rule: fewer searches only count as a workflow-efficiency signal.
They should not be described as better final quality unless that signal is
visible inside the session.

### 2 Session Duration

Session duration should measure elapsed workflow time from session events.

Report:

- Sessions with usable start/end timestamps and percent of all sessions.
- Median session duration.
- Duration per completed turn.
- Duration to first tool call.
- Delta versus `No KB`.

If a trace cannot distinguish wall-clock time from active work time, the report
should label the duration as elapsed time.

### 3 Skill And KB Interaction

Skill and KB interaction should be inferred from session-visible evidence.

Report:

- Sessions with skill/KB references and percent of all sessions.
- Sessions with skill/KB reads and percent of all sessions.
- Highest evidence level reached per session.
- Skill/KB names or short IDs when visible in the session.
- Delta versus `No KB`.

The report should not inspect or score KB contents directly. It should only
measure whether the session read, referenced, or followed skill/KB material.

### 4 Hypothesis Signal

Hypothesis signal measures whether and when the session reached a plausible
debug direction.

Report:

- Sessions with a detected hypothesis-like phrase.
- Median minutes to first hypothesis-like phrase.
- Coverage: sessions with a detected hypothesis divided by total sessions.
- Delta versus `No KB`.

The first implementation can use heuristic detection for phrases such as root
cause, hypothesis, likely owner, recommended next step, RCA candidate, or
validation plan. The report should label this as a session-derived candidate
signal, not a correctness metric.

### 5 Workflow Path

Workflow path should summarize the major stages visible in the session.

Report:

- Common stage sequences, such as intake, context lookup, search, hypothesis,
  code inspection, edit, validation, and summary.
- Stage coverage and missing-stage counts.
- Repeated loops, such as search-to-search or edit-to-fixup cycles.
- Approximate path length per session.
- Delta versus `No KB`.

The report should treat workflow paths as approximate unless the session trace
contains explicit stage markers.

## Supporting Views

The existing service includes two supporting views that are not yet represented
as first-class rows in the canonical cross-session scorecard.

### Operation Score

Operation score summarizes trace-visible quality for major AI actions. The
current implementation uses deterministic evidence for the main UI. Optional
QGenie review is displayed as a separate semantic layer and should not overwrite
the local timeline, operation score, workflow card, or trace ledger.

Required behavior:

- Score AI actions on a bounded negative-to-positive scale.
- Preserve `score`, `score_reason`, `score_evidence`, `confidence`, and
  `scorer`.
- Aggregate positive and negative contributions separately, then compute
  `overall = positive + negative`.
- Keep human and system events as evidence/context rather than scoring them as
  AI work.
- Treat missing evidence as neutral, not as an implicit failure.
- Keep deterministic event scores stable when QGenie is run, so users can
  compare local trace evidence against semantic review without losing the
  original scoring basis.

Cross-session reports may aggregate operation scores by cohort, task family, or
workflow stage, but they should not convert the score into a claim of final
real-world correctness unless the session trace contains that evidence.

### QGenie Block Semantic Review

QGenie semantic review should be explicit and token-conscious. The current
single-session UI should not automatically call QGenie when a session is opened.
Instead, it should show a single action button for QGenie review. Clicking the
button reviews only the next unreviewed block and stores the result in a
resumable cache. Additional clicks continue from cached progress.

The current block approach is:

- Split the session into chronological blocks, defaulting to about 250 events
  per block.
- Build a compact block summary instead of sending every raw event to QGenie.
- Include a bounded set of representative events per block, including important
  positive/negative events, human turns, compaction/context events, and block
  boundaries.
- Ask QGenie for a block-level workflow-quality score, quality label, summary,
  positive reasons, negative reasons, workflow observation, recommended focus,
  confidence, and scorer identity.
- Cache completed block reviews as derived data.
- Return `partial` status when only some blocks are reviewed and `complete`
  when all blocks are reviewed.
- Preserve local deterministic scoring as the source of the main dashboard.

The QGenie panel should report:

- `reviewed_blocks / total_blocks`.
- Covered events and covered AI events.
- Local deterministic score within reviewed blocks.
- QGenie semantic score across reviewed blocks.
- Expandable block rows showing the block range, coverage, summary, reasons,
  workflow observation, recommendation, and representative events.
- Retry or continue behavior that processes only the next block, not the full
  session.

The static sample trace should clearly say that QGenie review only runs for real
backend JSONL sessions.

### Context Compaction

Compaction analysis measures whether a compressed context preserved what the
next epoch needed.

Report:

- Number and timestamps of compaction events.
- Token/context percentage before and after compaction when available.
- Compression efficiency.
- Context epochs and their positive, negative, overall, average, correction, and
  achievement counts.
- Retention dimensions for goals/requirements, decisions/constraints, validated
  achievements, open work, exact identifiers, and factual consistency.
- Retained, missing, and distorted facts.
- Compaction quality, continuity, and effectiveness when semantic scoring is
  configured.

Interpretation rule: token reduction alone is not compaction quality. A compacted
summary is useful only when it retains the goals, constraints, validated state,
open work, and exact identifiers needed to continue without avoidable repetition
or context-loss mistakes.

## Knowledge Base (KB) Cohorts

The report should compare sessions by KB usage:

| Cohort | Definition |
|---|---|
| `no-kb` | No session-visible skill or KB evidence |
| `skill-workflow-only` | Skill or workflow evidence exists, but no KB reference or read is visible |
| `kb-referenced` | KB material is mentioned or cited in the session |
| `kb-read` | KB material is opened, read, retrieved, or otherwise loaded during the session |
| `kb-read-plus-structured-workflow` | KB read evidence plus explicit workflow or stage evidence |

The report should warn when cohorts are not comparable because of different task
type, date range, model, platform, or session complexity.

## Measurement Rules

### Session Deduping

Use the merged `session` as the default scoring unit. If multiple trace files
share the same session or thread ID, merge them before computing skill usage,
KB cohort, token usage, tool/search usage, duration, hypothesis signals, and
workflow paths.

Deduping rules:

- Count files separately only for parse health.
- Use the latest or maximum cumulative token count once per merged session.
- Deduplicate tool and command events by event ID when available, otherwise by
  timestamp plus payload hash.
- Preserve the number of source fragments so odd sessions can be audited later.

### Confidence Levels

Each cohort comparison should carry a confidence label:

| Confidence | Minimum Bar | Allowed Language |
|---|---|---|
| Exploratory | Some data exists, but sample size or detection patterns are weak | "looks like", "candidate signal" |
| Directional | Comparable task type and at least 10 sessions in the cohort | "likely trend" |
| Trace-backed | Comparable task type, at least 20 sessions per compared cohort, and explicit event markers for the compared metric | "measured session-trace difference" |

Do not say a skill or KB caused a final outcome improvement from session traces
alone. The report can describe measured session-trace differences, such as
faster hypothesis timing or fewer search calls, when the evidence supports them.

### Process Metrics Versus Outcome Claims

Separate session-derived process metrics from final outcome claims in the
report.

| Type | Metrics | Interpretation |
|---|---|---|
| Process | Tokens, duration, search calls, tool calls, KB reads, hypothesis markers, workflow path | Shows observable workflow behavior |
| Outcome | Final correctness, real-world fix quality, downstream acceptance | Out of scope unless it is explicitly visible in the session trace |

The main verdict should stay within what the session trace can support. For
example, `faster but heavier` is a valid read when a KB cohort reaches
hypotheses sooner but uses more tokens.

### Cost Per Session Signal

When enough trace evidence exists, add signal-normalized efficiency metrics:

- Tokens per hypothesis-bearing session.
- Tokens per KB-read session.
- Tool calls per hypothesis-bearing session.
- Search calls per hypothesis-bearing session.
- Minutes per hypothesis-bearing session.
- Minutes per KB-read session.

If the relevant session signal is not detectable, show these as `n/a` instead of
estimating.

## Detection Configuration

The implementation should support configurable patterns for session-derived
classification so the workflow can evolve without changing code.

The current service has hard-coded deterministic recognizers for explicit
success/failure, validation-like operations, mutation-like operations, human
corrections, and human confirmations. Those recognizers are acceptable for the
single-session baseline, but cohort analytics should move them into explicit
configuration so metric definitions can be audited and adjusted without code
changes.

Minimum pattern fields:

```text
pattern_type,name,match,source_hint,evidence_level,notes
```

Allowed `pattern_type` values:

```text
skill-reference,kb-reference,kb-read,search-call,hypothesis,workflow-stage
```

Allowed `evidence_level` values:

```text
available,referenced,opened,observed,stage-qualified
```

The report should show pattern coverage and unknown event types so missing
instrumentation can be fixed.

## Report Format

The report should start with a short `Read This First` section that states:

- What looks meaningful.
- What is weak or heuristic.
- What data gap blocks stronger conclusions.
- The highest-value next instrumentation or detection-pattern fix.

Then include:

- Inventory summary.
- Canonical numbered scorecard.
- Single-session workflow card embedded in the existing selected-chat dashboard.
- Operation-score summary and trace ledger for session audit.
- Optional QGenie block semantic review, manually triggered and shown as a
  separate layer.
- Context-window and compaction-quality views when compaction evidence exists.
- Period summary pages for `This week`, `Last week`, and `Last 2 weeks`.
- `This week` versus `Last week` comparison with side-by-side values and
  difference columns.
- Token/tool/search efficiency table versus `No KB`.
- Skill and KB ranking by strength of session evidence.
- Workflow path summary.
- Action list.
- Optional session appendix.
- Confidence label for each cohort comparison.
- Cost per session signal when enough trace evidence exists.

Example style:

```text
Static KB reached a hypothesis in 3.8 min versus 8.2 min for No KB.
That is 53.3% faster, but Static KB also used 110.2% more tokens per
token-bearing session, so the current read is faster but heavier.
```

## Output Artifacts

Current and planned output modes:

- Browser dashboard for interactive single-session inspection.
- Browser period summaries for `This week`, `Last week`, and `Last 2 weeks`.
- Browser comparison view for `This week` versus `Last week`.
- Browser JSON export for the selected project/chat analysis.
- Markdown report for humans.
- JSON report for dashboards and follow-up analysis.
- Optional CSV exports for spreadsheet review.

The default report should hide raw prompts and long log excerpts. Prompt
previews or raw evidence should require an explicit option.

Report artifacts are the only allowed writes for this skill. They must be
created under an explicit destination path and must never be treated as
source-of-truth updates to the input datasets.

## Privacy And Safety

- Treat session logs as sensitive.
- Prefer aggregate metrics and short session IDs.
- Use loopback binding by default for any dashboard that exposes raw session
  content.
- Require authentication for remote browser access, and prefer TLS termination
  in a reverse proxy because Basic Auth over plain HTTP is not encrypted.
- Do not print credentials, tokens, internal URLs with secrets, raw CR details,
  or long pasted logs.
- Keep analysis read-only; do not update source systems or evidence stores from
  an analytics run.
- Treat generated reports as derived artifacts, not canonical KB or review data.

## Acceptance Criteria

### Current Single-Session Dashboard Baseline

The `codex-history-analyzer` service should be considered usable as the
single-session foundation when it can:

- Discover Codex JSONL history under `sessions/` and `archived_sessions/`.
- Group chats by project path and expose a project/chat selector.
- Load one selected chat without mutating the source session file.
- Reconstruct normalized human, AI, tool, MCP, skill, system, compaction, and
  completion events.
- Preserve tool-call to tool-output linkage, including unknown or incomplete
  results.
- Show token/context-pressure samples when available.
- Score operations deterministically without requiring external services.
- Keep QGenie review optional and user-triggered so opening a session does not
  spend external model tokens.
- Review QGenie semantic quality by cached session blocks, processing only the
  next unreviewed block per user action.
- Preserve deterministic event scores when QGenie review is run.
- Cache semantic scoring results as derived data and support partial/resumable
  scoring.
- Render timeline, operation score, trace ledger, context-window, epoch, and
  compaction-quality views.
- Render the single-session 0-5 workflow card in the same selected-chat UI,
  using the existing detail panels as drill-downs.
- Export the selected analysis as JSON.
- Render `This week`, `Last week`, and `Last 2 weeks` summary pages from the
  same 0-5 scorecard structure.
- Render a `This week` versus `Last week` comparison that shows both period
  values plus the difference and includes skill/service repo-change context.
- Provide local and remote deployment modes, health checks, and Basic Auth for
  remote access.

### Future Cross-Session Analytics

The cross-session workflow analytics layer should be considered usable when it
can:

- Scan a sessions root and report parse success rate.
- Enforce read-only operation for all input roots and write only explicit report
  artifacts.
- Ingest agent session traces through configurable adapters.
- Exclude the active session by default.
- Merge duplicate session fragments before scoring.
- Classify skill and KB evidence as available, referenced, opened, observed, or
  stage-qualified.
- Produce the six numbered scorecard sections.
- Show percentages with denominators for every major count.
- Compare KB cohorts against `No KB` using token, duration, tool/search,
  hypothesis, and workflow-path deltas.
- Label each comparison as exploratory, directional, or trace-backed.
- Avoid requiring non-session external systems for core metrics.
- Export both Markdown and JSON.

## Open Questions

- Which event fields are stable across supported agent trace formats?
- Which phrase patterns should count as a first hypothesis for each workflow?
- Which cohorts should be compared only within the same task family?
- Should QGenie block size and representative-event limits be user-adjustable in
  the UI, or remain deployment configuration only?
- Should compaction-quality QGenie analysis also become manually triggered to
  avoid spending tokens when users only need deterministic local metrics?

