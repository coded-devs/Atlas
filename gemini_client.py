"""
gemini_client.py — Shared Gemini call wrapper with model fallback.

Both atlas.py (CLI) and app.py (Streamlit) route their generate_content
calls through smart_generate(). When a model returns a retry-able error
(429 RESOURCE_EXHAUSTED rate limit, 503 UNAVAILABLE, or 404 model-not-found
for an ID this account doesn't have), we transparently fall back to the next
model in MODEL_CHAIN instead of failing the whole request.

Any non-retry-able error (bad request, auth, etc.) is re-raised unchanged
so callers can handle it normally.

Spreading load across the chain gives us roughly 3000+ requests per day
across all models on the free tier.
"""

# Models to try, in priority order. The first that isn't rate-limited wins.
MODEL_CHAIN = [
    "gemini-2.5-flash",       # best quality, 20 RPD free
    "gemini-2.0-flash",       # good quality, 20 RPD free
    "gemini-1.5-flash",       # older but reliable, 1500 RPD free
    "gemini-1.5-flash-8b",    # lightweight, 1500 RPD free
    "gemini-2.0-flash-lite",  # lightweight, 1500 RPD free
]


def _is_rate_limit_error(err: Exception) -> bool:
    """
    True for transient capacity errors worth retrying on another model:
    429 / RESOURCE_EXHAUSTED (rate limit) and 503 / UNAVAILABLE (overloaded).

    The google-genai SDK surfaces these as an APIError with a numeric code
    and a status string. We also fall back to string matching so the
    detection survives SDK changes — but we never treat an arbitrary error
    as retry-able.
    """
    if getattr(err, "code", None) in (429, 503):
        return True

    status = getattr(err, "status", None)
    if status and ("RESOURCE_EXHAUSTED" in str(status) or "UNAVAILABLE" in str(status)):
        return True

    message = str(err)
    return any(s in message for s in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE"))


def _is_model_not_found_error(err: Exception) -> bool:
    """
    True for 404 / NOT_FOUND errors — a model ID that doesn't exist on this
    account. We skip gracefully to the next model rather than crashing, since
    model availability varies by account.
    """
    if getattr(err, "code", None) == 404:
        return True

    status = getattr(err, "status", None)
    if status and "NOT_FOUND" in str(status):
        return True

    message = str(err)
    return "404" in message or "NOT_FOUND" in message


def smart_generate(client, contents, config, on_status=None):
    """
    Call client.models.generate_content(), trying each model in MODEL_CHAIN
    until one succeeds or all are exhausted.

    Args:
        client:   a google.genai Client.
        contents: the conversation contents to send.
        config:   a GenerateContentConfig (system prompt + tools).
        on_status: optional callback(str). When provided (e.g. the Streamlit
                   status container's .write), it receives which model is in
                   use and any fallback messages, so the user can see the
                   fallback happen. Fallback messages are always printed too.

    Returns:
        The generate_content response from the first model that works.

    Raises:
        The last retry-able error if every model in the chain is exhausted,
        or any non-retry-able error immediately (unchanged).
    """
    last_error = None

    for i, model in enumerate(MODEL_CHAIN):
        if on_status:
            on_status(f"Using model: `{model}`")

        try:
            return client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
        except Exception as e:
            # Retry-able: 429/503 (capacity) or 404 (model missing on this
            # account). Anything else is a real failure — re-raise untouched.
            rate_limited = _is_rate_limit_error(e)
            not_found = _is_model_not_found_error(e)
            if not (rate_limited or not_found):
                raise

            last_error = e
            next_model = MODEL_CHAIN[i + 1] if i + 1 < len(MODEL_CHAIN) else None
            reason = "Rate limited on" if rate_limited else "Model not available:"

            if next_model:
                msg = f"{reason} {model}, switching to {next_model}..."
            else:
                msg = f"{reason} {model}, no more models to try."
            print(msg)
            if on_status:
                on_status(msg)

    # Exhausted every model in the chain.
    if last_error is not None:
        raise last_error
    raise RuntimeError("smart_generate: MODEL_CHAIN is empty.")
