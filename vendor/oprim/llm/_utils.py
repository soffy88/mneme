from __future__ import annotations

_VALID_ROLES = {"user", "assistant", "system", "tool"}

def _validate_messages(messages: list[dict]) -> list[str]:
    errors = []
    if not messages:
        errors.append("messages list is empty")
        return errors
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            errors.append(f"messages[{i}] is not a dict")
            continue
        role = msg.get("role", "")
        if role not in _VALID_ROLES:
            errors.append(f"messages[{i}].role '{role}' not in {_VALID_ROLES}")
        if "content" not in msg:
            errors.append(f"messages[{i}] missing 'content'")
    return errors

def _extract_usage(response: dict) -> dict[str, int]:
    usage = response.get("usage", {})
    return {
        "input_tokens": usage.get("input_tokens") or usage.get("prompt_tokens") or 0,
        "output_tokens": usage.get("output_tokens") or usage.get("completion_tokens") or 0,
    }

def _extract_text(response: dict) -> str:
    content = response.get("content", [])
    if isinstance(content, str): return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return ""

def _extract_tool_calls(response: dict) -> list[dict]:
    content = response.get("content", [])
    if not isinstance(content, list): return []
    return [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
