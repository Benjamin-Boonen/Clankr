"""Shared prompt-history budgeting for ordinary chat and agent mode.

Only the API copy is compacted; the database transcript remains untouched.
Token estimates are approximate because Ollama models can use different tokenizers.
"""
import json

DEFAULT_HISTORY_CHARS = 24000
RECENT_MESSAGES = 8
TOOL_RESULT_CHARS = 1200
OTHER_OLD_MESSAGE_CHARS = 1800


def _size(messages):
    return sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)


def estimate_tokens(messages):
    """Approximate prompt tokens including message structure (characters / 4)."""
    return max(1, _size(messages) // 4)


def context_pressure(messages, budget_chars=DEFAULT_HISTORY_CHARS):
    """Return context-pressure metadata suitable for a UI indicator."""
    size = _size(messages)
    ratio = size / max(1, budget_chars)
    return {
        "estimated_tokens": estimate_tokens(messages),
        "budget_tokens": max(1, budget_chars // 4),
        "ratio": round(ratio, 2),
        "level": "normal" if ratio < 0.70 else "high" if ratio < 1.0 else "critical",
        "suggest_new_chat": ratio >= 1.5,
    }


def compact_messages(messages, budget_chars=DEFAULT_HISTORY_CHARS, recent=RECENT_MESSAGES):
    """Shorten older prose/results while preserving roles and tool protocol ordering.

    The first user request and newest messages are retained verbatim. Tool-call
    metadata, tool names, image payloads, and message order are preserved. The
    original list and its dictionaries are never mutated.
    """
    if not messages or _size(messages) <= budget_chars:
        return messages

    first_user = next((i for i, m in enumerate(messages) if m.get("role") == "user"), None)
    recent_start = max(0, len(messages) - recent)
    out = []
    for index, message in enumerate(messages):
        item = dict(message)
        if index != first_user and index < recent_start:
            content = item.get("content")
            if isinstance(content, str) and content:
                limit = TOOL_RESULT_CHARS if item.get("role") == "tool" else OTHER_OLD_MESSAGE_CHARS
                if len(content) > limit:
                    item["content"] = content[:limit] + "\n…[older context compacted; full transcript retained]"
        out.append(item)

    # A huge old transcript may still exceed the target. Further shorten only
    # older non-user messages; never alter tool-call metadata or the recent tail.
    if _size(out) > budget_chars:
        for index, item in enumerate(out):
            if index == first_user or index >= recent_start:
                continue
            content = item.get("content")
            if isinstance(content, str) and len(content) > 400:
                item["content"] = content[:400] + "\n…[context compacted; full transcript retained]"
                if _size(out) <= budget_chars:
                    break
    return out
