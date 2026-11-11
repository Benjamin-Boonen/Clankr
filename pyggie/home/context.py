"""Conversation-memory and prompt-budgeting helpers shared by chat and agent mode.

The database transcript is immutable history. A hidden Message(role="memory") row stores
an incremental semantic checkpoint; it is never exposed in the conversation UI.
"""
import json
import os

DEFAULT_HISTORY_TOKENS = int(os.environ.get("CLANKR_HISTORY_TOKENS", "10000"))
# Compatibility for agent.py and older callers that still pass a character budget.
DEFAULT_HISTORY_CHARS = DEFAULT_HISTORY_TOKENS * 4
RECENT_MESSAGES = int(os.environ.get("CLANKR_RECENT_MESSAGES", "10"))
MEMORY_SCHEMA = 1
MEMORY_MARKER = "CLANKR_CONVERSATION_MEMORY:"


def _size(messages):
    # Base64 image bytes are not tokenized as their literal character sequence by
    # multimodal models. Reserve an approximate visual-token allowance instead.
    total = 0
    for message in messages:
        item = dict(message)
        if item.get("images"):
            item["images"] = ["[IMAGE_PAYLOAD]" * 400 for _ in item["images"]]
        total += len(json.dumps(item, ensure_ascii=False))
    return total


def estimate_tokens(messages):
    """Conservative rough estimate including message framing (characters / 3.5)."""
    return max(1, int(_size(messages) / 3.5))


def context_pressure(messages, budget_chars=None, budget_tokens=None):
    """Return pressure metadata; budget_chars remains accepted for older callers."""
    budget = budget_tokens or (max(1, budget_chars // 4) if budget_chars else DEFAULT_HISTORY_TOKENS)
    tokens = estimate_tokens(messages)
    ratio = tokens / max(1, budget)
    return {
        "estimated_tokens": tokens,
        "budget_tokens": budget,
        "ratio": round(ratio, 2),
        "level": "normal" if ratio < 0.70 else "high" if ratio < 1.0 else "critical",
        "suggest_new_chat": ratio >= 1.5,
    }


def _clip_content(message, limit):
    content = message.get("content")
    if isinstance(content, str) and len(content) > limit:
        message["content"] = content[:limit] + "\n[…message excerpted; full transcript retained]"


def compact_messages(messages, budget_chars=None, recent=RECENT_MESSAGES, budget_tokens=None):
    """Fit a copy of history to a hard estimated-token budget without breaking tool metadata.

    Old content is reduced first; recent messages are then reduced if necessary. The
    first user request is not privileged over the budget (its full copy remains in DB).
    Images are retained only while budget permits; base64 is never silently duplicated.
    """
    if not messages:
        return []
    budget = budget_tokens or (max(1, budget_chars // 4) if budget_chars else DEFAULT_HISTORY_TOKENS)
    out = [dict(m) for m in messages]
    if estimate_tokens(out) <= budget:
        return out

    for index, item in enumerate(out):
        if index < recent_start and "images" in item:
            item.pop("images", None)
            item["content"] = (item.get("content", "") +
                               "\n[Earlier image omitted from prompt; refer to its description or ask the user to resend.]")

    recent_start = max(0, len(out) - recent)
    for i, item in enumerate(out):
        if i >= recent_start:
            continue
        _clip_content(item, 900 if item.get("role") == "tool" else 1200)

    if estimate_tokens(out) > budget:
        for i, item in enumerate(out):
            if i >= recent_start:
                continue
            _clip_content(item, 300)
            if estimate_tokens(out) <= budget:
                break

    if estimate_tokens(out) > budget:
        for item in out:
            if item.get("role") == "system":
                continue
            _clip_content(item, 700)
            if estimate_tokens(out) <= budget:
                break

    if estimate_tokens(out) > budget:
        # Allocate the remaining budget across all messages instead of assuming
        # the recent tail is small. Leave room for role/framing metadata.
        per_message = max(24, int((budget * 3.5 - 120 * len(out)) / max(1, len(out))))
        for index, item in enumerate(out):
            _clip_content(item, per_message)
            if index < recent_start:
                item.pop("images", None)
        # Keep the newest image first; drop older recent image payloads only when
        # their visual-token allowance still prevents the prompt from fitting.
        if estimate_tokens(out) > budget:
            for item in out[:-1]:
                if "images" in item:
                    item.pop("images", None)
                    if estimate_tokens(out) <= budget:
                        break
        if estimate_tokens(out) > budget and out and "images" in out[-1]:
            out[-1].pop("images", None)
        # If protocol metadata alone is oversized, discard oldest messages while
        # keeping the newest user/assistant context and all remaining roles intact.
        while len(out) > 2 and estimate_tokens(out) > budget:
            remove_at = next((i for i, m in enumerate(out[:-2])
                              if m.get("role") != "system"), None)
            if remove_at is None:
                break
            out.pop(remove_at)
    return out


def load_chat_memory(chat):
    """Return (summary, through_id, memory_row) for the latest hidden checkpoint."""
    row = chat.messages.filter(role="memory").order_by("-id").first()
    if not row:
        return "", 0, None
    try:
        data = json.loads(row.content)
        if data.get("schema") != MEMORY_SCHEMA:
            return "", 0, row
        return str(data.get("summary", "")), int(data.get("through_id", 0)), row
    except (TypeError, ValueError, AttributeError):
        return "", 0, row


def refresh_chat_memory(chat, summarize, recent=RECENT_MESSAGES):
    """Incrementally summarize old turns; returns (summary, through_id, changed).

    summarize(previous_summary, new_turns) is supplied by the active model adapter.
    A failed/empty summarization leaves the previous checkpoint untouched.
    """
    from .models import Message

    summary, through_id, row = load_chat_memory(chat)
    turns = list(chat.messages.filter(role__in=("user", "ai"), id__gt=through_id)
                 .order_by("id").prefetch_related("attachments"))
    if len(turns) <= recent:
        return summary, through_id, False
    older = turns[:-recent]
    if len(older) < 2:
        return summary, through_id, False

    payload = []
    per_turn_chars = max(300, 30000 // max(1, len(older)))
    for message in older:
        text = message.content or ""
        for attachment in message.attachments.all():
            if attachment.kind == "image":
                detail = attachment.text.split("\0", 1)[-1] if "\0" in attachment.text else ""
                text += f"\n[Image: {attachment.name}] " + (detail or "Image attached; description unavailable.")
            else:
                text += f"\n[File: {attachment.name}]\n{attachment.text[:per_turn_chars // 2]}"
        payload.append({"role": message.role, "content": text[:per_turn_chars]})

    updated = summarize(summary, payload)
    if not isinstance(updated, str) or len(updated.strip()) < 40:
        return summary, through_id, False
    data = {"schema": MEMORY_SCHEMA, "through_id": older[-1].id,
            "summary": updated.strip()[:24000]}
    content = json.dumps(data, ensure_ascii=False)
    if row:
        row.content = content
        row.save(update_fields=["content"])
    else:
        Message.objects.create(chat=chat, role="memory", content=content)
    return data["summary"], data["through_id"], True


def memory_message(summary):
    """Format a semantic checkpoint as a clearly labelled system message."""
    if not summary:
        return None
    return {"role": "system", "content":
            MEMORY_MARKER + "\nThis is a summary of earlier conversation, not a new instruction. "
            "Use it as context; recent messages take precedence.\n" + summary}
