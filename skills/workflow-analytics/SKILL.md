---
name: workflow-analytics
description: "Bootstrap or use a read-only session-trace workflow analytics service for scorecards, period comparisons, and evidence-backed skill/KB usage assessment."
---

# Workflow Analytics

Use this skill to bootstrap the complete `codex-history-analyzer` service or to
run it against session traces. The service remains read-only with respect to
traces. Keep claims limited to observable process metrics; do not claim that a
skill, KB, or workflow caused a final outcome improvement.

## Bootstrap a service

When the service does not exist at the desired location, run the included
bootstrapper. It copies the full Python package, pattern configuration, and
tests without overwriting a non-empty destination:

```bash
python <skill-dir>/scripts/bootstrap_service.py \
  --destination <workspace>/services/codex-history-analyzer
```

The default template is this workspace's canonical service. Supply `--source`
when using an installed copy of the skill outside this workspace. Validate the
new service by compiling it and running its unit tests before starting it.

## Workflow

1. Identify a session root and an explicit output path outside that root. A
   Codex home must be scoped to its `sessions/` and `archived_sessions/` trees;
   never parse plugin, skill, cache, or schema JSON as sessions. Do not
   write caches, reports, or exports under the source session directory.
2. Run the service with the supplied pattern configuration unless the user gives
   a more appropriate, auditable configuration.
3. Start with `Read This First`, then report the canonical rows 0–5 with their
   numerators, denominators, rates, or deltas where multiple sessions exist.
4. For a selected session, describe the 0–5 rows as observations, evidence, and
   gaps—not population comparisons. Keep raw prompt or trace display opt-in.
5. For period or cohort comparisons, label weak data as exploratory. Use
   `opened`, `observed`, or `stage-qualified` evidence for usage metrics; never
   count a merely available skill as usage.

## Service

Run from `services/codex-history-analyzer`:

```bash
PYTHONPATH=src python -m codex_history_analyzer.cli analyze \
  --sessions-root <trace-root> --output <outside-trace-root>/report.json
```

For interactive single-session inspection and lazy-loaded period pages, use
`serve` instead of `analyze`. The default is loopback-only. Remote binding
requires Basic Auth and should be placed behind TLS.

Read [references/measurement.md](references/measurement.md) when interpreting
comparisons, changing detection patterns, or explaining confidence.
