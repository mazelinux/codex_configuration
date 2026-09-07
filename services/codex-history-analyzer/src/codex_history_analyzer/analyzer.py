from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable

EVIDENCE_ORDER = {"none": 0, "available": 1, "referenced": 2, "opened": 3, "observed": 4, "stage-qualified": 5}
SEARCH_NAMES = ("rg", "grep", "find", "ag", "search", "query", "codeindex", "doc rag", "gerrit", "issue")
VALIDATION_NAMES = ("test", "pytest", "validate", "build", "lint", "typecheck")
EDIT_NAMES = ("write", "edit", "patch", "apply_patch", "deploy")


def _nested(value: Any, *names: str, default: Any = None) -> Any:
    if not isinstance(value, dict):
        return default
    for name in names:
        if name in value and value[name] is not None:
            return value[name]
    for child in (value.get("payload"), value.get("data"), value.get("message"), value.get("item"), value.get("info")):
        if isinstance(child, dict):
            found = _nested(child, *names, default=None)
            if found is not None:
                return found
    return default


def _when(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Unix seconds and milliseconds are both common in imports.
        return datetime.fromtimestamp(value / 1000 if value > 10_000_000_000 else value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _compact(value: Any, limit: int = 600) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _text_content(value: Any) -> str:
    """Extract human-readable text from Codex's typed content arrays."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(part for item in value if (part := _text_content(item)))
    if isinstance(value, dict):
        # Typed text blocks should never appear as JSON blobs in the ledger.
        for key in ("text", "content", "output", "result", "input", "arguments", "summary"):
            if key in value:
                result = _text_content(value[key])
                if result:
                    return result
        return ""
    return str(value)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Pattern:
    pattern_type: str
    name: str
    match: str
    source_hint: str = ""
    evidence_level: str = "referenced"
    notes: str = ""


class PatternSet:
    """Auditable configurable classifiers; unrecognized trace data remains visible."""

    def __init__(self, patterns: Iterable[Pattern]):
        self.patterns = list(patterns)
        self._compiled = [(p, re.compile(p.match, re.I)) for p in self.patterns]

    @classmethod
    def default(cls) -> "PatternSet":
        path = Path(__file__).parents[2] / "config" / "patterns.json"
        return cls.from_file(path)

    @classmethod
    def from_file(cls, path: str | Path) -> "PatternSet":
        rows = json.loads(Path(path).read_text(encoding="utf-8"))
        allowed = {"skill-reference", "kb-reference", "kb-read", "search-call", "hypothesis", "workflow-stage"}
        levels = set(EVIDENCE_ORDER) - {"none"}
        patterns = []
        for row in rows:
            if row["pattern_type"] not in allowed or row["evidence_level"] not in levels:
                raise ValueError(f"Invalid analytics pattern: {row}")
            patterns.append(Pattern(**row))
        return cls(patterns)

    def matches(self, text: str, kind: str = "") -> list[Pattern]:
        aliases = {"tool": "tool" in kind, "assistant": "ai" in kind, "message": "message" in kind}
        return [p for p, rx in self._compiled if (not p.source_hint or aliases.get(p.source_hint, p.source_hint in kind)) and rx.search(text)]


class Analyzer:
    """Builds derived analytics in memory. It never writes beneath input roots."""

    def __init__(self, sessions_root: str | Path, patterns: PatternSet | None = None, active_session_id: str | None = None):
        self.root = Path(sessions_root).expanduser().resolve()
        self.patterns = patterns or PatternSet.default()
        self.active_session_id = active_session_id or os.getenv("CODEX_SESSION_ID")
        if not self.root.exists() or not self.root.is_dir():
            raise ValueError(f"Sessions root is not a directory: {self.root}")
        self.parse_health: list[dict[str, Any]] = []

    def discover(self) -> list[Path]:
        """Find traces only in Codex session trees, or in an explicit import root."""
        # A Codex home contains plugins, skills, caches, and other JSON that are
        # not traces. If it exposes canonical session subdirectories, those are
        # the complete input scope. An arbitrary root without those directories
        # is treated as an explicit browser-import/local-review trace root.
        children = [self.root / name for name in ("sessions", "archived_sessions")]
        roots = [path for path in children if path.is_dir()] or [self.root]
        files = []
        for trace_root in roots:
            for path in trace_root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in {".json", ".jsonl", ".ndjson", ".txt"}:
                    continue
                if any(part in {"cache", "reports", ".git", "node_modules"} for part in path.parts):
                    continue
                if path.name.lower().replace("-", "_") in {"session_index.json", "sessions_index.json"}:
                    continue
                files.append(path)
        return sorted(files)

    def _records(self, path: Path) -> list[Any]:
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".txt":
            return [{"type": "imported_text", "content": line} for line in text.splitlines() if line.strip()]
        if path.suffix.lower() == ".json":
            value = json.loads(text)
            return value if isinstance(value, list) else value.get("events", value.get("records", [value]))
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def _normalize(self, raw: Any, fragment: Path, seq: int, session_id: str) -> dict[str, Any]:
        raw = raw if isinstance(raw, dict) else {"content": raw}
        outer_type = str(raw.get("type", raw.get("event_type", raw.get("kind", "unknown")))).lower()
        payload_type = _nested(raw.get("payload", {}) if isinstance(raw.get("payload"), dict) else {}, "type", "event_type", "kind", default=None)
        # Codex wraps actual response item types in records such as `response_item`.
        raw_type = str(payload_type if outer_type in {"response_item", "event_msg", "event", "record"} and payload_type else outer_type).lower()
        role = str(_nested(raw, "role", "author", default="")).lower()
        tool = str(_nested(raw, "tool_name", "tool", "name", "command", "function_name", default=""))
        call_id = str(_nested(raw, "call_id", "tool_call_id", "id", default=""))
        timestamp = _when(_nested(raw, "timestamp", "time", "created_at", "ts", default=None))
        content = _nested(raw, "content", "text", "output", "result", "arguments", "input", default="")
        text = _compact(_text_content(content))
        combined = f"{raw_type} {role} {tool} {text}"
        completed_item_type = str(_nested(_nested(raw, "item", default={}), "type", default="")).lower()
        if raw_type == "item_completed":
            # Codex emits this in addition to the response item. It is a
            # lifecycle acknowledgement, not a completed agent turn.
            kind, actor = "lifecycle", "system"
        elif completed_item_type == "usermessage":
            kind, actor = "message", "human"
        elif completed_item_type == "agentmessage":
            kind, actor = "message", "ai"
        elif completed_item_type in {"functioncall", "toolcall"}:
            kind, actor = "tool_call", "tool"
        elif completed_item_type in {"functioncalloutput", "tooloutput"}:
            kind, actor = "tool_output", "tool"
        elif "compact" in raw_type or "summar" in raw_type:
            kind, actor = "compaction", "system"
        elif "token" in raw_type or any(k in raw for k in ("token_count", "total_tokens", "usage")):
            kind, actor = "token_count", "system"
        elif "output" in raw_type or "result" in raw_type or raw_type in {"tool_result", "function_result"}:
            kind, actor = "tool_output", "tool"
        elif "call" in raw_type or "function" in raw_type or tool:
            kind, actor = "tool_call", "tool"
        elif role in {"user", "human"}:
            kind, actor = "message", "human"
        elif role in {"assistant", "agent", "ai"}:
            kind, actor = "message", "ai"
        elif "complete" in raw_type or "finish" in raw_type:
            kind, actor = "completion", "system"
        else:
            kind, actor = "system", "system"
        title = tool or (text[:110] if text else raw_type)
        event_id = str(_nested(raw, "event_id", "uuid", default=""))
        unique = event_id or hashlib.sha1(f"{timestamp}|{kind}|{tool}|{text}".encode()).hexdigest()[:16]
        return {"id": unique, "session_id": session_id, "fragment": str(fragment), "seq": seq, "time": timestamp.isoformat() if timestamp else None,
                "kind": kind, "actor": actor, "tool": tool, "call_id": call_id, "title": title, "context": text,
                "raw_type": raw_type, "raw": raw, "score": self._score(combined, kind, actor)}

    @staticmethod
    def _score(text: str, kind: str, actor: str) -> dict[str, Any]:
        if actor != "ai" and kind not in {"tool_call", "tool_output"}:
            return {"positive": 0, "negative": 0, "overall": 0, "reason": "Evidence/context event", "confidence": "low", "scorer": "deterministic"}
        positive = 1 if re.search(r"\b(pass(?:ed)?|success|fixed|validated|complete[d]?)\b", text, re.I) else 0
        negative = -1 if re.search(r"\b(fail(?:ed|ure)?|error|cannot|regression|retry|not_installed)\b", text, re.I) else 0
        reason = "Trace-visible success/failure evidence" if positive or negative else "No explicit outcome evidence"
        return {"positive": positive, "negative": negative, "overall": positive + negative, "reason": reason,
                "confidence": "medium" if positive or negative else "low", "scorer": "deterministic"}

    def sessions(self, include_active: bool = False) -> list[dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        index = self._session_index()
        self.parse_health = []
        for path in self.discover():
            try:
                records = self._records(path)
                if not isinstance(records, list):
                    raise ValueError("Top-level trace must be a list or contain events/records")
                first = records[0] if records else {}
                sid = str(_nested(first if isinstance(first, dict) else {}, "session_id", "thread_id", "conversation_id", default=path.stem))
                group = groups.setdefault(sid, {"id": sid, "fragments": [], "events": [], "cwd": "", "title": "", "metadata": {}, "source_states": set()})
                group["fragments"].append(str(path))
                group["source_states"].add("archived" if (self.root / "archived_sessions") in path.parents else "active")
                for record_index, raw in enumerate(records):
                    event = self._normalize(raw, path, record_index, sid)
                    group["events"].append(event)
                    if not group["cwd"]:
                        group["cwd"] = str(_nested(raw if isinstance(raw, dict) else {}, "cwd", "project_path", default=""))
                    if not group["title"]:
                        group["title"] = str(_nested(raw if isinstance(raw, dict) else {}, "title", "chat_title", default=""))
                self.parse_health.append({"fragment": str(path), "status": "ok", "records": len(records)})
            except Exception as exc:  # retain health, do not silently omit source failure
                self.parse_health.append({"fragment": str(path), "status": "error", "error": str(exc), "records": 0})
        result = []
        for session in groups.values():
            if self.active_session_id and session["id"] == self.active_session_id and not include_active:
                continue
            seen: set[str] = set()
            events = [e for e in session["events"] if not (e["id"] in seen or seen.add(e["id"]))]
            events.sort(key=lambda e: (e["time"] is None, e["time"] or "", e["seq"]))
            self._link_tools(events)
            session["events"] = events
            indexed = index.get(session["id"], {})
            session["title"] = session["title"] or indexed.get("title") or self._conversation_title(events) or session["id"][:12]
            session["cwd"] = session["cwd"] or indexed.get("cwd", "")
            session["project"] = session["cwd"] or "Unknown project"
            # A partial archival move may temporarily leave fragments in both
            # trees; keep that trace visible in Active until it is fully moved.
            session["state"] = "archived" if session["source_states"] == {"archived"} else "active"
            session["summary"] = self._session_summary(session)
            result.append(session)
        return sorted(result, key=lambda s: s["summary"]["end"] or "", reverse=True)

    @staticmethod
    def _conversation_title(events: list[dict[str, Any]]) -> str:
        """Use the first user turn when Codex session-index title metadata is absent."""
        injected_prefixes = ("<recommended_plugins>", "<environment_context>", "<app-context>", "<skills_instructions>")
        first = next((event["context"] for event in events if event["kind"] == "message" and event["actor"] == "human" and event["context"] and not event["context"].lstrip().startswith(injected_prefixes)), "")
        first = re.sub(r"\s+", " ", first).strip()
        return first[:56] + ("…" if len(first) > 56 else "")

    def _session_index(self) -> dict[str, dict[str, str]]:
        """Best-effort title/project enrichment; index entries are not trace events."""
        found: dict[str, dict[str, str]] = {}
        for path in self.root.rglob("*.json"):
            if path.name.lower().replace("-", "_") not in {"session_index.json", "sessions_index.json"}:
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                rows = value.values() if isinstance(value, dict) else value
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    sid = str(_nested(row, "session_id", "thread_id", "id", default=""))
                    if sid:
                        found[sid] = {"title": str(_nested(row, "title", "chat_title", default="")), "cwd": str(_nested(row, "cwd", "project_path", default=""))}
            except (OSError, json.JSONDecodeError):
                continue
        return found

    @staticmethod
    def _link_tools(events: list[dict[str, Any]]) -> None:
        """Correlate outputs without hiding incomplete calls or unlinked output."""
        calls: dict[str, dict[str, Any]] = {}
        pending: list[dict[str, Any]] = []
        for event in events:
            if event["kind"] == "tool_call":
                event["linked_output_ids"] = []
                if event["call_id"]:
                    calls[event["call_id"]] = event
                pending.append(event)
            elif event["kind"] == "tool_output":
                match = calls.get(event["call_id"]) if event["call_id"] else (pending[-1] if pending else None)
                event["linked_call_id"] = match["id"] if match else None
                if match:
                    match["linked_output_ids"].append(event["id"])

    def _session_summary(self, session: dict[str, Any]) -> dict[str, Any]:
        ev = session["events"]
        timed = [_when(e["time"]) for e in ev if e["time"]]
        start, end = (min(timed), max(timed)) if timed else (None, None)
        tools = [e for e in ev if e["kind"] == "tool_call"]
        searches = [e for e in tools if any(n in f"{e['tool']} {e['context']}".lower() for n in SEARCH_NAMES)]
        turn_durations = [duration / 1000 for event in ev if event["kind"] == "completion" if (duration := _number(_nested(event["raw"], "duration_ms", default=None))) is not None]
        completed_turns = len(turn_durations)
        signals = self._signals(ev)
        tokens = self._tokens(ev)
        tool_buckets = Counter(self._tool_bucket(event) for event in tools)
        tool_examples: dict[str, Counter[str]] = defaultdict(Counter)
        for event in tools:
            tool_examples[self._tool_bucket(event)][self._command_example(event)] += 1
        tool_wait = sum(self._tool_wait_seconds(event) for event in ev if event["kind"] == "tool_output")
        duration = (end - start).total_seconds() if start and end else None
        knowledge_buckets, hypothesis_count, knowledge_evidence = self._evidence_buckets(ev)
        return {"start": start.isoformat() if start else None, "end": end.isoformat() if end else None,
                "duration_seconds": duration,
                "tool_calls": len(tools), "search_calls": len(searches), "completed_turns": completed_turns,
                "tool_buckets": dict(tool_buckets), "tool_bucket_examples": {bucket: dict(examples) for bucket, examples in tool_examples.items()},
                "temporary_script_runs": self._temporary_script_runs(ev), "tool_wait_seconds": tool_wait or None,
                "agent_turn_seconds": sum(turn_durations) if turn_durations else None,
                "timestamp_count": len(timed), "knowledge_buckets": dict(knowledge_buckets), "hypothesis_count": hypothesis_count,
                "knowledge_evidence": knowledge_evidence, "event_count": len(ev), "tokens": tokens, **signals}

    @staticmethod
    def _tool_text(event: dict[str, Any]) -> str:
        """Extract the executed command when a tool call wraps one."""
        raw = event.get("raw", {})
        command = _nested(raw, "cmd", "command", default=None)
        if isinstance(command, str) and command.strip():
            return command
        text = f"{event['tool']} {event['context']}"
        match = re.search(r"[\"'](?:cmd|command)[\"']\s*:\s*[\"']([^\"']+)", text)
        return match.group(1) if match else text

    @staticmethod
    def _tool_bucket(event: dict[str, Any]) -> str:
        text = Analyzer._tool_text(event).lower()
        # Structured patch calls can contain source snippets mentioning search
        # commands, so recognize the mutation wrapper before classifying text.
        if "*** begin patch" in text or "apply_patch" in text:
            return "Edit / write / deploy"
        if re.match(r"^(?:[a-z_][a-z0-9_]*=[^\s]+\s+)*(?:rg|grep|find|ag)(?:\s|$)", text):
            return "Local text search"
        if "web" in text and "search" in text:
            return "Web search"
        if any(name in text for name in VALIDATION_NAMES):
            return "Test / build / validation"
        if any(name in text for name in EDIT_NAMES):
            return "Edit / write / deploy"
        if any(name in text for name in SEARCH_NAMES):
            return "Other retrieval"
        return "Other tool calls"

    @staticmethod
    def _command_example(event: dict[str, Any]) -> str:
        """Give each bucket an auditable command label without exposing raw text."""
        text = Analyzer._tool_text(event).lower()
        for label, expression in (
            ("rg", r"\brg\b"), ("grep", r"\bgrep\b"), ("find", r"\bfind\b"),
            ("pytest", r"\bpytest\b"), ("npm", r"\bnpm\b"), ("python", r"\bpython(?:3)?\b"),
            ("apply_patch", r"\bapply_patch\b"), ("sed", r"\bsed\b"), ("cat", r"\bcat\b"),
            ("web search", r"\bweb\w*search\b"),
        ):
            if re.search(expression, text):
                return label
        return event["tool"] or "unclassified tool"

    @staticmethod
    def _temporary_script_runs(events: list[dict[str, Any]]) -> int:
        """Count observable write-then-run temporary scripts, conservatively."""
        created: set[str] = set()
        executed: set[str] = set()
        path_rx = re.compile(r"/(?:tmp|var/tmp)/[\w.-]+\.(?:py|sh|bash|js|ts|rb|pl)\b", re.I)
        write_rx = re.compile(r"(?:\bcat\s*>{1,2}|\btee\s+|write_file|write_text|open\([^)]*,\s*['\"]w|apply_patch)", re.I)
        for event in events:
            if event["kind"] != "tool_call":
                continue
            text = Analyzer._tool_text(event)
            paths = set(path_rx.findall(text))
            if write_rx.search(text):
                created.update(paths)
            for path in paths & created:
                if re.search(r"\b(?:python(?:3)?|bash|sh|node|ruby|perl)\s+['\"]?" + re.escape(path), text, re.I):
                    executed.add(path)
        return len(executed)

    @staticmethod
    def _tool_wait_seconds(event: dict[str, Any]) -> float:
        match = re.search(r"(?:wall[ _]time(?:_seconds)?[\": ]+)([0-9.]+)", event["context"], re.I)
        return float(match.group(1)) if match else 0.0

    def _evidence_buckets(self, events: list[dict[str, Any]]) -> tuple[Counter[str], int, list[dict[str, Any]]]:
        buckets: Counter[str] = Counter()
        hypotheses = 0
        evidence: list[dict[str, Any]] = []
        buckets["Skill reads"] = 0
        buckets["KB reads"] = 0
        for event in events:
            text = f"{event['title']} {event['context']}"
            matches = self.patterns.matches(text, event["kind"] + " " + event["actor"])
            if event["kind"] == "tool_call" and self._is_skill_read(text):
                buckets["Skill reads"] += 1
                evidence.append({"event_id": event["id"], "time": event["time"], "type": "skill-read", "name": "Skill read", "level": "opened", "context": event["context"]})
            if event["kind"] == "tool_call" and self._is_kb_read(text):
                buckets["KB reads"] += 1
                evidence.append({"event_id": event["id"], "time": event["time"], "type": "kb-read", "name": "KB read", "level": "opened", "context": event["context"]})
            for pattern in matches:
                if pattern.pattern_type == "hypothesis": hypotheses += 1
        return buckets, hypotheses, evidence

    def _tokens(self, events: list[dict[str, Any]]) -> dict[str, float | None]:
        keys = {"input": ("input_tokens", "input_token_count"), "output": ("output_tokens", "output_token_count"),
                "cached_input": ("cached_input_tokens", "cache_read_input_tokens"), "cache_write_input": ("cache_write_input_tokens",),
                "reasoning": ("reasoning_tokens", "reasoning_output_tokens"), "total": ("total_tokens", "token_count", "total_token_count")}
        values: dict[str, float] = defaultdict(float)
        samples = []
        for e in events:
            if e["kind"] != "token_count":
                continue
            raw = e["raw"]
            # Codex event_msg/token_count stores cumulative values in
            # payload.info.total_token_usage rather than directly on the event.
            usage = _nested(raw, "total_token_usage", "token_usage", "usage", default=raw)
            found = {}
            for label, names in keys.items():
                value = _nested(usage, *names, default=None)
                numeric = _number(value)
                if numeric is not None:
                    found[label] = numeric
            context_window = _number(_nested(raw, "model_context_window", "context_window", "context_tokens", default=None))
            if context_window is not None:
                found["context_window"] = context_window
            if found:
                samples.append(found)
        if not samples:
            return {k: None for k in (*keys, "context_peak", "context_min")}
        # Token events are normally cumulative. Use the largest observation per field.
        for sample in samples:
            for key, value in sample.items():
                values[key] = max(values[key], value)
        if not values["total"]:
            values["total"] = values["input"] + values["output"] + values["reasoning"]
        contexts = [x for sample in samples for x in (sample.get("context_window"), sample.get("context_tokens")) if x is not None]
        return {**{k: values.get(k) for k in keys}, "context_peak": max(contexts) if contexts else None, "context_min": min(contexts) if contexts else None}

    def context_progress(self, session: dict[str, Any]) -> dict[str, Any]:
        """Return timestamped context-pressure samples for one session.

        Codex's ``total_token_usage`` is cumulative over a session, so it must
        not be divided by the context window.  The chart instead uses the
        token count of the latest request (``last_token_usage.input_tokens``)
        when a trace does not expose an explicit current-context field.
        """
        samples: list[dict[str, Any]] = []
        for event in session["events"]:
            if event["kind"] != "token_count" or not event["time"]:
                continue
            raw = event["raw"]
            context_window = _number(_nested(raw, "model_context_window", "context_window", default=None))
            explicit_context = _number(_nested(raw, "current_context_tokens", "context_token_count", "context_tokens", default=None))
            last_usage = _nested(raw, "last_token_usage", default={})
            last_input = _number(_nested(last_usage, "input_tokens", "input_token_count", default=None))
            used = explicit_context if explicit_context is not None else last_input
            if context_window is None or context_window <= 0 or used is None:
                continue
            samples.append({
                "time": event["time"],
                "context_tokens": used,
                "context_window": context_window,
                "percent": used / context_window * 100,
                "source": "reported context" if explicit_context is not None else "last request input",
            })
        compactions: list[dict[str, Any]] = []
        for event_index, event in enumerate(session["events"]):
            if event["kind"] != "compaction" or not event["time"]:
                continue
            event_time = _when(event["time"])
            before = next((sample for sample in reversed(samples) if _when(sample["time"]) and _when(sample["time"]) <= event_time), None)
            after = next((sample for sample in samples if _when(sample["time"]) and _when(sample["time"]) >= event_time), None)
            window_number = _number(_nested(event["raw"], "window_number", default=None))
            relief = ((before["context_tokens"] - after["context_tokens"]) / before["context_tokens"] * 100
                      if before and after and before["context_tokens"] > 0 else None)
            history = _nested(event["raw"], "replacement_history", default=[])
            history = history if isinstance(history, list) else []
            encrypted_summary = any(isinstance(item, dict) and item.get("encrypted_content") for item in history)
            continuity = self._compaction_continuity(session["events"], event_index)
            compactions.append({
                "event_id": event["id"],
                "time": event["time"],
                "window_number": int(window_number) if window_number is not None else None,
                # These are adjacent observable samples, not estimates of the
                # hidden compaction payload itself.
                "before_sample": before,
                "after_sample": after,
                "relief_percent": relief,
                "replacement_history_count": len(history),
                "encrypted_summary": encrypted_summary,
                "continuity": continuity,
            })
        latest = samples[-1] if samples else None
        reliefs = [entry["relief_percent"] for entry in compactions if entry.get("relief_percent") is not None]
        return {"samples": samples, "compactions": compactions, "summary": {
            "context_window": latest["context_window"] if latest else None,
            "latest_percent": latest["percent"] if latest else None,
            "headroom_percent": max(0, 100 - latest["percent"]) if latest else None,
            "peak_percent": max((sample["percent"] for sample in samples), default=None),
            "mean_compaction_relief_percent": sum(reliefs) / len(reliefs) if reliefs else None,
        }}

    @staticmethod
    def _compaction_continuity(events: list[dict[str, Any]], index: int) -> dict[str, Any]:
        """Derive only trace-visible continuity signals around one compaction."""
        narrative = lambda event: event["actor"] in {"ai", "human"} and bool(event["context"])
        before = next((event for event in reversed(events[:index]) if narrative(event)), None)
        after_events = [event for event in events[index + 1:index + 80] if narrative(event)]
        after = after_events[0] if after_events else None
        before_terms = Analyzer._semantic_terms(before["context"]) if before else set()
        after_terms = Analyzer._semantic_terms(after["context"]) if after else set()
        shared = before_terms & after_terms
        union = before_terms | after_terms
        overlap = len(shared) / len(union) * 100 if union else None
        window_text = " ".join(event["context"] for event in after_events[:12]).lower()
        missing_rx = re.compile(r"(?:missing|lost|forgot(?:ten)?|need.{0,30}context|missing.{0,20}context|丢失.{0,12}上下文|忘记.{0,12}上下文|缺少.{0,12}上下文|重新提供.{0,12}上下文)", re.I)
        distorted_rx = re.compile(r"(?:(?:context|compaction|compression|上下文|压缩).{0,60}(?:wrong|incorrect|misunderstood|distort|错误|不对|误解|失真)|(?:wrong|incorrect|misunderstood|distort|错误|不对|误解|失真).{0,60}(?:context|compaction|compression|上下文|压缩))", re.I)
        return {
            "retained_observed": bool(shared),
            "continuity_percent": overlap,
            "shared_terms": sorted(shared)[:8],
            "before_excerpt": before["context"][:220] if before else None,
            "after_excerpt": after["context"][:220] if after else None,
            "missing_signal": bool(missing_rx.search(window_text)),
            "distortion_signal": bool(distorted_rx.search(window_text)),
            "post_narrative_events": len(after_events),
        }

    @staticmethod
    def _semantic_terms(text: str) -> set[str]:
        words = {word.lower() for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text)}
        for segment in re.findall(r"[\u4e00-\u9fff]{2,}", text):
            words.update(segment[offset:offset + 2] for offset in range(len(segment) - 1))
        return words

    def _signals(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        evidence, names, hypothesis_at, stages = "none", set(), None, []
        skill_read, kb_read = False, False
        for event in events:
            text = f"{event['title']} {event['context']}"
            matches = self.patterns.matches(text, event["kind"] + " " + event["actor"])
            for p in matches:
                if EVIDENCE_ORDER[p.evidence_level] > EVIDENCE_ORDER[evidence]: evidence = p.evidence_level
                if p.pattern_type in {"skill-reference", "kb-reference", "kb-read"}: names.add(p.name)
                if p.pattern_type == "hypothesis" and hypothesis_at is None: hypothesis_at = event["time"]
            if event["kind"] == "tool_call" and self._is_skill_read(text):
                skill_read, evidence = True, max((evidence, "opened"), key=lambda level: EVIDENCE_ORDER[level])
                names.add("Skill read")
            if event["kind"] == "tool_call" and self._is_kb_read(text):
                kb_read, evidence = True, max((evidence, "opened"), key=lambda level: EVIDENCE_ORDER[level])
                names.add("KB read")
            stage = self._stage(event, bool(matches))
            if stage and (not stages or stages[-1] != stage): stages.append(stage)
        kb = "kb-read-plus-structured-workflow" if kb_read and stages else "kb-read" if kb_read else "skill-workflow-only" if skill_read else "no-kb"
        return {"evidence_level": evidence, "knowledge_names": sorted(names), "kb_cohort": kb, "hypothesis_at": hypothesis_at, "workflow_path": stages}

    @staticmethod
    def _is_skill_read(text: str) -> bool:
        return Analyzer._is_read_operation(text) and bool(re.search(r"(?:SKILL\.md|[\\/]skills?[\\/])", text, re.I))

    @staticmethod
    def _is_kb_read(text: str) -> bool:
        explicit_kb = bool(re.search(r"(?:knowledge[-_ ]base|knowledge_base|[\\/]kb[\\/]|doc[_ -]?rag)", text, re.I))
        return explicit_kb and ("doc_rag" in text.lower() or "doc rag" in text.lower() or Analyzer._is_read_operation(text))

    @staticmethod
    def _is_read_operation(text: str) -> bool:
        lowered = text.lower()
        # Do not count references embedded in a patch or another mutation as a read.
        if any(marker in lowered for marker in ("apply_patch", "write_file", "edit_file", "patch =")):
            return False
        return bool(re.search(r"(?:\bread_file\b|\bcat\s|\bsed\s+-n|\bopen\b|\bget_file\b|\bfetch\b)", lowered))

    @staticmethod
    def _stage(event: dict[str, Any], matched: bool) -> str | None:
        text = f"{event['tool']} {event['title']} {event['context']}".lower()
        if event["actor"] == "human": return "intake"
        if event["kind"] == "compaction": return "compaction"
        if event["kind"] == "completion": return "summary"
        if any(marker in text for marker in ("root cause", "hypothesis", "likely cause", "根因", "根本原因", "可能原因")): return "hypothesis"
        if event["kind"] == "tool_call":
            if any(n in text for n in SEARCH_NAMES): return "search"
            if any(n in text for n in VALIDATION_NAMES): return "validation"
            if any(n in text for n in EDIT_NAMES): return "edit"
            if "read" in text or "cat " in text: return "context lookup"
            return "tool execution"
        return None

    def workflow_card(self, session: dict[str, Any]) -> list[dict[str, Any]]:
        s, ev = session["summary"], session["events"]
        token = s["tokens"]
        compactions = [e for e in ev if e["kind"] == "compaction"]
        first_tool = next((e for e in ev if e["kind"] == "tool_call"), None)
        start, first = _when(s["start"]), _when(first_tool["time"]) if first_tool else None
        return [
            {"row": 0, "name": "Token Usage", "observation": {"total_tokens": token["total"], "input_tokens": token["input"], "output_tokens": token["output"], "cached_input_tokens": token["cached_input"], "cache_read_share": token["cached_input"] / token["input"] if token["cached_input"] is not None and token["input"] else None, "cache_write_input_tokens": token["cache_write_input"], "reasoning_tokens": token["reasoning"], "token_samples": sum(e["kind"] == "token_count" for e in ev), "context_peak": token["context_peak"], "compactions": len(compactions)}},
            {"row": 1, "name": "Tool And Search Calls", "observation": {"tool_calls": s["tool_calls"], "search_calls": s["search_calls"], "linked_outputs": sum(e["kind"] == "tool_output" for e in ev), "tool_buckets": s["tool_buckets"], "tool_bucket_examples": s["tool_bucket_examples"], "temporary_script_runs": s["temporary_script_runs"]}},
            {"row": 2, "name": "Agent Time", "observation": {"elapsed_seconds": s["duration_seconds"], "agent_turn_seconds": s["agent_turn_seconds"], "tool_wait_seconds": s["tool_wait_seconds"], "first_tool_delay_seconds": (first - start).total_seconds() if first and start else None, "completed_turns": s["completed_turns"], "timestamp_count": s["timestamp_count"], "timestamp_coverage": bool(start and _when(s["end"]))}},
            {"row": 3, "name": "Knowledge Source Usage", "observation": {"evidence_level": s["evidence_level"], "signals": s["knowledge_names"], "cohort": s["kb_cohort"], "knowledge_buckets": s["knowledge_buckets"], "knowledge_evidence": s["knowledge_evidence"]}},
            {"row": 4, "name": "First Hypothesis / Decision", "observation": {"candidate_detected": bool(s["hypothesis_at"]), "first_candidate_at": s["hypothesis_at"], "first_candidate_seconds": (_when(s["hypothesis_at"]) - start).total_seconds() if s["hypothesis_at"] and start else None, "hypothesis_signals": s["hypothesis_count"], "scope": "heuristic session-derived candidate; not correctness"}},
            {"row": 5, "name": "Workflow Path", "observation": {"stages": s["workflow_path"], "path_length": len(s["workflow_path"]), "event_count": s["event_count"], "scope": "approximate unless explicit stage markers exist"}},
        ]

    def period(self, sessions: list[dict[str, Any]], name: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        ranges = {"this-week": (now - timedelta(days=now.weekday()), now), "last-week": (now - timedelta(days=now.weekday() + 7), now - timedelta(days=now.weekday())), "last-2-weeks": (now - timedelta(days=14), now)}
        if name not in ranges: raise ValueError("period must be this-week, last-week, or last-2-weeks")
        left, right = ranges[name]
        selected = [s for s in sessions if (stamp := _when(s["summary"]["start"])) and left <= stamp <= right]
        total = len(selected)
        with_tokens = [s for s in selected if s["summary"]["tokens"]["total"] is not None]
        with_time = [s for s in selected if s["summary"]["duration_seconds"] is not None]
        hypothesis = [s for s in selected if s["summary"]["hypothesis_at"]]
        def total_metric(field: str) -> int: return sum(s["summary"][field] for s in selected)
        token_total = sum(s["summary"]["tokens"]["total"] or 0 for s in selected)
        counter = Counter(stage for s in selected for stage in s["summary"]["workflow_path"])
        knowledge = Counter(s["summary"]["evidence_level"] for s in selected)
        return {"period": name, "start": left.isoformat(), "end": right.isoformat(), "session_count": total,
                "read_this_first": self._read_first(total, len(with_tokens), len(with_time), len(hypothesis)),
                "scorecard": [
                    {"row": 0, "name": "Token Usage", "total": token_total, "token_bearing_sessions": self._rate(len(with_tokens), total), "tokens_per_token_bearing_session": token_total / len(with_tokens) if with_tokens else None},
                    {"row": 1, "name": "Tool And Search Calls", "tool_calls": total_metric("tool_calls"), "search_calls": total_metric("search_calls"), "tools_per_session": total_metric("tool_calls") / total if total else None},
                    {"row": 2, "name": "Agent Time", "timestamped_sessions": self._rate(len(with_time), total), "median_elapsed_seconds": median(s["summary"]["duration_seconds"] for s in with_time) if with_time else None},
                    {"row": 3, "name": "Knowledge Source Usage", "evidence_levels": dict(knowledge), "sessions_with_opened_or_stronger": self._rate(sum(EVIDENCE_ORDER[s["summary"]["evidence_level"]] >= EVIDENCE_ORDER["opened"] for s in selected), total)},
                    {"row": 4, "name": "First Hypothesis / Decision", "coverage": self._rate(len(hypothesis), total), "scope": "heuristic candidate signal"},
                    {"row": 5, "name": "Workflow Path", "stage_coverage": dict(counter), "mean_path_length": sum(len(s["summary"]["workflow_path"]) for s in selected) / total if total else None},
                ], "sessions": [{"id": s["id"], "title": s["title"], "project": s["project"], "cohort": s["summary"]["kb_cohort"]} for s in selected]}

    @staticmethod
    def _rate(n: int, d: int) -> dict[str, Any]:
        return {"numerator": n, "denominator": d, "rate": n / d if d else None}

    @staticmethod
    def _read_first(total: int, token: int, timed: int, hypothesis: int) -> list[str]:
        if not total: return ["No timestamped sessions fall in this period.", "Data gap: collect stable session timestamps before comparing periods."]
        return [f"{total} sessions are in scope; this is a process-metric summary, not a causal outcome claim.", f"{token}/{total} sessions expose token samples; {timed}/{total} expose usable elapsed time.", f"{hypothesis}/{total} have a heuristic hypothesis/decision candidate; tune patterns before treating this as strong evidence."]

    def comparison(self, sessions: list[dict[str, Any]]) -> dict[str, Any]:
        old, new = self.period(sessions, "last-week"), self.period(sessions, "this-week")
        rows = []
        for left, right in zip(old["scorecard"], new["scorecard"]):
            numeric = {}
            for key in set(left) & set(right):
                if isinstance(left[key], (int, float)) and isinstance(right[key], (int, float)):
                    numeric[key] = {"last_week": left[key], "this_week": right[key], "difference": right[key] - left[key]}
            rows.append({"row": left["row"], "name": left["name"], "values": numeric})
        return {"last_week": old, "this_week": new, "comparison": rows,
                "caution": "Side-by-side trace differences are not evidence that a skill or KB caused an outcome improvement."}

    def report(self, sessions: list[dict[str, Any]]) -> dict[str, Any]:
        return {"source_root": str(self.root), "read_only": True, "parse_health": self.parse_health,
                "inventory": {"sessions": len(sessions), "fragments": sum(len(s["fragments"]) for s in sessions), "projects": len({s["project"] for s in sessions})},
                "periods": {p: self.period(sessions, p) for p in ("this-week", "last-week", "last-2-weeks")}, "comparison": self.comparison(sessions)}
