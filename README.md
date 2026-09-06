# Session Analyzer

`services/codex-history-analyzer` is a read-only Python service for reconstructing
agent traces and producing the design document's 0–5 workflow scorecard. It reads
JSON, JSONL, NDJSON, and text traces, merges fragments by session ID, and writes
only explicitly requested report artifacts outside the session input root.

## Run

```bash
cd /home/lem/workspace/session_analyzer/services/codex-history-analyzer
PYTHONPATH=src python -m codex_history_analyzer.cli analyze \
  --sessions-root "$CODEX_HISTORY_HOME" \
  --output /tmp/workflow-report.json

PYTHONPATH=src python -m codex_history_analyzer.cli serve \
  --sessions-root "$CODEX_HISTORY_HOME"
```

The dashboard binds to `127.0.0.1:8765` by default. A non-loopback `--host`
requires `--username` and `--password`; use TLS termination before exposing it
outside the machine. The period endpoints load only when selected in the UI.

Detection patterns are in
[`patterns.json`](services/codex-history-analyzer/config/patterns.json). They are
auditable and configurable without changing service code.
