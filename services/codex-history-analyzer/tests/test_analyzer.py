import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from codex_history_analyzer.analyzer import Analyzer


def write_trace(root: Path) -> None:
    root.mkdir()
    base = (datetime.now(timezone.utc) - timedelta(days=1)).replace(microsecond=0)
    at = lambda seconds: (base + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")
    rows = [
        {"session_id": "demo", "cwd": "/repo/a", "timestamp": at(0), "role": "user", "content": "Find the regression"},
        {"session_id": "demo", "timestamp": at(10), "type": "tool_call", "tool_name": "read_file", "call_id": "a", "arguments": "skills/workflow/SKILL.md"},
        {"session_id": "demo", "timestamp": at(12), "type": "tool_result", "call_id": "a", "output": "loaded"},
        {"session_id": "demo", "timestamp": at(60), "type": "tool_call", "tool_name": "rg", "call_id": "b", "arguments": "regression"},
        {"session_id": "demo", "timestamp": at(120), "role": "assistant", "content": "The likely root cause is stale configuration."},
        {"session_id": "demo", "timestamp": at(180), "type": "token_count", "total_tokens": 400, "input_tokens": 300, "output_tokens": 100},
        {"session_id": "demo", "timestamp": at(240), "type": "completion"},
    ]
    (root / "demo.jsonl").write_text("\n".join(json.dumps(r) for r in rows))


class AnalyzerTest(unittest.TestCase):
    def test_normalizes_scorecard_and_periods(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as root:
            source = Path(root) / "sessions"
            write_trace(source)
            analyzer = Analyzer(source)
            sessions = analyzer.sessions()
            self.assertEqual(len(sessions), 1)
            session = sessions[0]
            self.assertEqual(session["summary"]["tokens"]["total"], 400)
            self.assertEqual(session["summary"]["search_calls"], 1)
            self.assertIn(session["summary"]["evidence_level"], {"opened", "observed", "stage-qualified"})
            self.assertTrue(session["events"][1]["linked_output_ids"])
            self.assertEqual([r["row"] for r in analyzer.workflow_card(session)], list(range(6)))
            self.assertEqual(analyzer.period(sessions, "last-2-weeks")["session_count"], 1)

    def test_codex_home_excludes_unrelated_json(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as root:
            home = Path(root)
            write_trace(home / "sessions")
            (home / "plugins").mkdir()
            (home / "plugins" / "manifest.json").write_text('{"name": "not a session"}')
            analyzer = Analyzer(home)
            self.assertEqual(len(analyzer.discover()), 1)
            self.assertEqual(len(analyzer.sessions()), 1)

    def test_marks_archived_session_from_codex_archive_tree(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as root:
            home = Path(root)
            write_trace(home / "sessions")
            write_trace(home / "archived_sessions")
            archived = home / "archived_sessions" / "demo.jsonl"
            archived.write_text(archived.read_text().replace('"demo"', '"old"').replace('"/repo/a"', '"/repo/old"'))
            states = {session["id"]: session["state"] for session in Analyzer(home).sessions()}
            self.assertEqual(states, {"demo": "active", "old": "archived"})

    def test_project_lists_sort_each_state_newest_first(self):
        from codex_history_analyzer.cli import defaultdict_list
        sessions = [
            {"id": "old-active", "title": "Old active", "project": "/repo", "state": "active", "summary": {"end": "2026-09-01T10:00:00Z"}},
            {"id": "new-archived", "title": "New archived", "project": "/repo", "state": "archived", "summary": {"end": "2026-09-04T10:00:00Z"}},
            {"id": "new-active", "title": "New active", "project": "/repo", "state": "active", "summary": {"end": "2026-09-05T10:00:00Z"}},
            {"id": "old-archived", "title": "Old archived", "project": "/repo", "state": "archived", "summary": {"end": "2026-09-02T10:00:00Z"}},
        ]
        grouped = defaultdict_list(sessions)[0]
        self.assertEqual([row["id"] for row in grouped["active"]], ["new-active", "old-active"])
        self.assertEqual([row["id"] for row in grouped["archived"]], ["new-archived", "old-archived"])

    def test_extracts_chinese_typed_codex_message_without_lifecycle_completion(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as root:
            source = Path(root) / "sessions"
            source.mkdir()
            rows = [
                {"type": "session_meta", "payload": {"id": "cn", "session_id": "cn", "cwd": "/repo"}},
                {"type": "response_item", "timestamp": "2026-09-01T10:00:00Z", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "请分析这个中文会话"}]}},
                {"type": "event_msg", "timestamp": "2026-09-01T10:00:01Z", "payload": {"type": "item_completed", "item": {"type": "UserMessage", "content": [{"type": "text", "text": "请分析这个中文会话"}]}}},
                {"type": "response_item", "timestamp": "2026-09-01T10:01:00Z", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "可能原因是配置错误。"}]}},
            ]
            (source / "cn.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
            session = Analyzer(source).sessions()[0]
            messages = [event for event in session["events"] if event["kind"] == "message"]
            self.assertEqual(session["title"], "请分析这个中文会话")
            self.assertEqual(messages[0]["context"], "请分析这个中文会话")
            self.assertEqual(messages[1]["context"], "可能原因是配置错误。")
            self.assertEqual(session["summary"]["completed_turns"], 0)
            self.assertEqual(session["summary"]["hypothesis_at"], "2026-09-01T10:01:00+00:00")

    def test_reads_codex_nested_cumulative_token_usage(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as root:
            source = Path(root) / "sessions"
            source.mkdir()
            rows = [
                {"type": "session_meta", "payload": {"id": "tokens", "session_id": "tokens"}},
                {"type": "event_msg", "timestamp": "2026-09-01T10:00:00Z", "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 120, "cached_input_tokens": 80, "output_tokens": 12, "reasoning_output_tokens": 4, "total_tokens": 132}, "last_token_usage": {"input_tokens": 120}, "model_context_window": 258400}}},
                {"type": "response_item", "timestamp": "2026-09-01T10:00:10Z", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "I will build the Context Progress view."}]}},
                {"type": "compacted", "timestamp": "2026-09-01T10:00:30Z", "payload": {"window_number": 1}},
                {"type": "response_item", "timestamp": "2026-09-01T10:00:40Z", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "I am implementing Context Progress now."}]}},
                {"type": "event_msg", "timestamp": "2026-09-01T10:01:00Z", "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 220, "cached_input_tokens": 160, "output_tokens": 22, "reasoning_output_tokens": 8, "total_tokens": 242}, "last_token_usage": {"input_tokens": 200}, "model_context_window": 258400}}},
            ]
            (source / "tokens.jsonl").write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            analyzer = Analyzer(source)
            session = analyzer.sessions()[0]
            tokens = session["summary"]["tokens"]
            self.assertEqual(tokens["total"], 242)
            self.assertEqual(tokens["reasoning"], 8)
            self.assertEqual(tokens["context_peak"], 258400)
            self.assertAlmostEqual(analyzer.workflow_card(session)[0]["observation"]["cache_read_share"], 160 / 220)
            progress = analyzer.context_progress(session)
            self.assertEqual(len(progress["samples"]), 2)
            self.assertAlmostEqual(progress["samples"][-1]["percent"], 200 / 258400 * 100)
            self.assertEqual(progress["compactions"][0]["window_number"], 1)
            self.assertEqual(progress["compactions"][0]["before_sample"]["context_tokens"], 120)
            self.assertEqual(progress["compactions"][0]["after_sample"]["context_tokens"], 200)
            self.assertTrue(progress["compactions"][0]["continuity"]["retained_observed"])
