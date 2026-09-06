# Session Analyzer / 会话分析器

`services/codex-history-analyzer` is a read-only Python service for reconstructing
agent traces and producing the design document's 0–5 workflow scorecard. It reads
JSON, JSONL, NDJSON, and text traces, merges fragments by session ID, and writes
only explicitly requested report artifacts outside the session input root.

`services/codex-history-analyzer` 是一个只读 Python 服务，用于重建智能体轨迹，
并生成设计文档定义的 0–5 分工作流评分卡。它可读取 JSON、JSONL、NDJSON 和文本
轨迹，按会话 ID 合并片段，并且只会在会话输入根目录之外写入明确指定的报告产物。

## Run / 运行

From the repository root, run:

在仓库根目录执行：

```bash
cd services/codex-history-analyzer
PYTHONPATH=src python -m codex_history_analyzer.cli analyze \
  --sessions-root "$CODEX_HISTORY_HOME" \
  --output ./workflow-report.json

PYTHONPATH=src python -m codex_history_analyzer.cli serve \
  --sessions-root "$CODEX_HISTORY_HOME"
```

The dashboard binds to `127.0.0.1:8765` by default. A non-loopback `--host`
requires `--username` and `--password`; use TLS termination before exposing it
outside the machine. The period endpoints load only when selected in the UI.

仪表盘默认绑定到 `127.0.0.1:8765`。使用非回环地址的 `--host` 时，必须提供
`--username` 和 `--password`；在将服务暴露到本机外之前，请使用 TLS 终止代理。
各周期端点仅会在用户界面中被选中时加载。

Detection patterns are in
[`patterns.json`](services/codex-history-analyzer/config/patterns.json). They are
auditable and configurable without changing service code.

检测模式位于
[`patterns.json`](services/codex-history-analyzer/config/patterns.json)。这些模式可审计、
可配置，且无需修改服务代码。
