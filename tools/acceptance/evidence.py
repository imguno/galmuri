"""Reject apparent success without a completed turn and grounded MCP reads."""

import json
from pathlib import Path


def _envelope(result: dict) -> dict:
    payload = result.get("structured_content") or result.get("structuredContent")
    if payload is None:
        texts = [part["text"] for part in result.get("content", []) if part.get("type") == "text"]
        payload = json.loads(texts[0]) if texts else {}
    if not isinstance(payload, dict):
        raise AssertionError("MCP result did not contain a service envelope")
    return payload


def check(
    directory: Path, answer: dict, *, expected_key=None, required=(), forbidden=(), search_terms=()
):
    raw = (directory / "events.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if not any(event.get("type") == "turn.completed" for event in events):
        raise AssertionError("LLM turn did not complete")
    if any(event.get("type") in {"error", "turn.failed"} for event in events):
        raise AssertionError("LLM client reported a failure")
    items = [event["item"] for event in events if event.get("type") == "item.completed"]
    if any(item.get("type") in {"command_execution", "web_search"} for item in items):
        raise AssertionError("Answer used a forbidden external tool")
    calls = [item for item in items if item.get("type") == "mcp_tool_call"]
    if any(call.get("server") != "acceptance" for call in calls):
        raise AssertionError("Answer used another MCP server")
    if any(
        call.get("tool") not in {"sample_describe", "sample_search", "sample_read"}
        for call in calls
    ):
        raise AssertionError("LLM called a tool outside the readonly acceptance contract")
    successful = []
    for call in calls:
        if call.get("status") != "completed" or call.get("error"):
            continue
        result = call.get("result") or {}
        if result.get("isError") or result.get("is_error"):
            continue
        if _envelope(result).get("ok") is True:
            successful.append(call)
    used = {call["tool"] for call in successful}
    if not {"sample_describe", "sample_search"} <= used:
        raise AssertionError("LLM did not describe and search through MCP")
    if any(value in raw or value in json.dumps(answer) for value in forbidden):
        raise AssertionError("Forbidden or outdated test fact appeared in the model evidence")
    if expected_key is None:
        if answer["found"] is not False or answer["document_key"] is not None:
            raise AssertionError("LLM invented an answer without a visible source")
        empty_search = any(
            call["tool"] == "sample_search"
            and _envelope(call["result"])["result"] == []
            and (
                not search_terms
                or any(
                    term.casefold() in call["arguments"].get("query", "").casefold()
                    for term in search_terms
                )
            )
            for call in successful
        )
        if not empty_search:
            raise AssertionError("Missing-document answer needs a successful relevant empty search")
    else:
        if answer["found"] is not True or answer["document_key"] != expected_key:
            raise AssertionError("LLM did not cite the expected retrieved document")
        if not all(value in answer["answer"] for value in required):
            raise AssertionError("Answer omitted dynamically generated facts")
        grounded = False
        for call in successful:
            if (
                call["tool"] != "sample_read"
                or call["arguments"].get("document_key") != expected_key
            ):
                continue
            payload = _envelope(call["result"])
            if payload["result"].get("key") == expected_key and all(
                value in payload["result"]["text"] for value in required
            ):
                grounded = True
        if not grounded:
            raise AssertionError("Expected answer lacks a successful supporting MCP read")
    return {"tools": [call["tool"] for call in successful], "answer": answer, "passed": True}
