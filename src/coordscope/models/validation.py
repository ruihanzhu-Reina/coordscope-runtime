"""Pinned provider response validation; no retained conversation state."""


def validate_pro_response(response):
    if response.model not in {"deepseek-v4-pro", "deepseek-v4-pro-0813", "deepseek-pro"}:
        raise ValueError(f"Unexpected DeepSeek Pro response model: {response.model!r}")
    usage = response.usage
    values = [getattr(usage, k, None) for k in ("prompt_tokens", "completion_tokens", "total_tokens")]
    if any(type(v) is not int or v < 0 for v in values) or values[2] != values[0] + values[1]:
        raise ValueError("DeepSeek Pro usage missing or inconsistent")
