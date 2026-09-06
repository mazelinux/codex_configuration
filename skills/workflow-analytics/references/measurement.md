# Measurement rules

The source trace is authoritative for process observations only. The service
merges fragments by session ID and deduplicates stable event IDs (or a timestamp
and payload hash fallback). It excludes the active session from aggregate views
unless explicitly included.

Evidence levels, from weakest to strongest, are `available`, `referenced`,
`opened`, `observed`, and `stage-qualified`. Inventory may show `available`, but
usage comparisons must use the last three levels. Detection rules use the schema
`pattern_type,name,match,source_hint,evidence_level,notes`; valid types are
`skill-reference`, `kb-reference`, `kb-read`, `search-call`, `hypothesis`, and
`workflow-stage`.

Use “candidate signal” for hypothesis heuristics. A comparison is exploratory
when coverage or patterns are weak, directional only with comparable task types
and at least 10 sessions per cohort, and trace-backed with comparable tasks, at
least 20 sessions per cohort, and explicit event markers. None of these labels
establishes final correctness or causality.

Cached input and cache-write input are input breakouts, never additional token
buckets on top of input tokens. Prefer `n/a` to an invented efficiency rate when
the relevant session signal is absent.
