"""Unit-test trace verification; these fixtures are not live LLM execution evidence."""

import json

import pytest

from tools.acceptance.evidence import check


def trace(tmp_path, *, include_read=True, private_text="", failed=False):
    items = []
    for name in ["sample_describe", "sample_search"] + (["sample_read"] if include_read else []):
        items.append(
            {
                "type": "item.completed",
                "item": {
                    "type": "mcp_tool_call",
                    "server": "acceptance",
                    "tool": name,
                    "status": "completed",
                    "error": None,
                    "arguments": {"document_key": "test.md"},
                    "result": {
                        "structured_content": {
                            "ok": True,
                            "result": {
                                "key": "test.md",
                                "text": "Locker-X CODE-123 " + private_text,
                            },
                        }
                    },
                },
            }
        )
    events = items + [{"type": "turn.failed" if failed else "turn.completed"}]
    (tmp_path / "events.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events), encoding="utf-8"
    )


def test_trace_requires_real_supporting_read_not_only_correct_final_text(tmp_path):
    answer = {"found": True, "document_key": "test.md", "answer": "Locker-X CODE-123"}
    trace(tmp_path, include_read=False)
    with pytest.raises(AssertionError, match="supporting MCP read"):
        check(tmp_path, answer, expected_key="test.md", required=("CODE-123",))
    trace(tmp_path)
    assert check(tmp_path, answer, expected_key="test.md", required=("CODE-123",))["passed"]


def test_negative_answer_cannot_hide_private_data_leaked_in_tool_results(tmp_path):
    trace(tmp_path, private_text="PRIVATE-FACT")
    answer = {"found": False, "document_key": None, "answer": "찾을 수 없습니다."}
    with pytest.raises(AssertionError, match="Forbidden"):
        check(tmp_path, answer, forbidden=("PRIVATE-FACT",))


def test_failed_llm_turn_cannot_be_counted_as_success(tmp_path):
    trace(tmp_path, failed=True)
    answer = {"found": True, "document_key": "test.md", "answer": "CODE-123"}
    with pytest.raises(AssertionError, match="did not complete"):
        check(tmp_path, answer, expected_key="test.md", required=("CODE-123",))


def test_failed_service_envelopes_cannot_prove_document_absence(tmp_path):
    trace(tmp_path, include_read=False)
    path = tmp_path / "events.jsonl"
    events = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    for event in events[:-1]:
        event["item"]["result"] = {
            "isError": True,
            "structured_content": {"ok": False, "error": {"code": "internal_error"}},
        }
    path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
    answer = {"found": False, "document_key": None, "answer": "없습니다."}
    with pytest.raises(AssertionError, match="describe and search"):
        check(tmp_path, answer)


def test_absence_requires_successful_empty_search_for_the_requested_topic(tmp_path):
    trace(tmp_path, include_read=False)
    path = tmp_path / "events.jsonl"
    events = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    search = events[1]["item"]
    search["arguments"] = {"query": "maintenance"}
    search["result"]["structured_content"]["result"] = []
    path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
    answer = {"found": False, "document_key": None, "answer": "없습니다."}
    assert check(tmp_path, answer, search_terms=("maintenance",))["passed"]
    with pytest.raises(AssertionError, match="relevant empty search"):
        check(tmp_path, answer, search_terms=("observatory",))
