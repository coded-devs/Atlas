"""
gemini_client.py — Shared Gemini call wrapper with model fallback.

Both atlas.py (CLI) and app.py (Streamlit) route their generate_content
calls through smart_generate(). When a model returns a 429 /
RESOURCE_EXHAUSTED rate-limit error, we transparently fall back to the
next model in MODEL_CHAIN instead of failing the whole request.

Any non-rate-limit error (bad request, auth, server error, etc.) is
re-raised unchanged so callers can handle it normally.
"""

# Models to try, in priority order. The first that isn't rate-limited wins.
MODEL_CHAIN = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
]


def _is_rate_limit_error(err: Exception) -> bool:
    """
    True only for 429 / RESOURCE_EXHAUSTED rate-limit errors.

    The google-genai SDK surfaces these as an APIError with code == 429 and
    status "RESOURCE_EXHAUSTED". We also fall back to string matching so the
    detection survives SDK changes — but we never treat an arbitrary error
    as a rate limit.
    """
    if getattr(err, "code", None) == 429:
        return True

    status = getattr(err, "status", None)
    if status and "RESOURCE_EXHAUSTED" in str(status):
        return True

    message = str(err)
    return "429" in message or "RESOURCE_EXHAUSTED" in message


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
        The last rate-limit error if every model in the chain is exhausted,
        or any non-rate-limit error immediately (unchanged).
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
            # Only 429 / RESOURCE_EXHAUSTED triggers fallback. Anything else
            # is a real failure — re-raise it untouched.
            if not _is_rate_limit_error(e):
                raise

            last_error = e
            next_model = MODEL_CHAIN[i + 1] if i + 1 < len(MODEL_CHAIN) else None

            if next_model:
                msg = f"Rate limited on {model}, switching to {next_model}..."
                print(msg)
                if on_status:
                    on_status(msg)
            else:
                msg = f"Rate limited on {model}, no more models to try."
                print(msg)
                if on_status:
                    on_status(msg)

    # Exhausted every model in the chain.
    if last_error is not None:
        raise last_error
    raise RuntimeError("smart_generate: MODEL_CHAIN is empty.")
