"""
gemini_client.py — Shared Gemini call wrapper with model fallback.

Both atlas.py (CLI) and app.py (Streamlit) route their generate_content
calls through smart_generate(). When a model returns a 429 /
RESOURCE_EXHAUSTED rate-limit error, we transparently fall back to the
next model in MODEL_CHAIN instead of failing the whole request.

Any non-rate-limit error (bad request, auth, server error, etc.) is
re-raised unchanged so callers can handle it normally.
"""

# Ordered by preference. Invalid/unavailable models are skipped
# automatically via 404 handling. Chain ends with high-quota
# models (1.5-flash: 1500 RPD) as safety net.
MODEL_CHAIN = [
    "gemini-3.5-flash",      # newer, 20 RPD free
    "gemini-3.1-pro",        # may not be available, will skip via 404
    "gemini-3.0-flash",      # may not be available, will skip via 404
    "gemini-2.5-flash",      # confirmed working, 20 RPD free
    "gemini-2.5-pro",        # exists but may have 0 quota
    "gemini-2.5-flash-lite", # lightweight variant
    "gemini-2.0-flash",      # confirmed working, 20 RPD free
    "gemini-1.5-flash",      # older but 1500 RPD free, reliable
    "gemini-1.5-flash-8b",   # lightweight, 1500 RPD free
]


def _should_fallback(err: Exception) -> bool:
    """
    True for 429 / RESOURCE_EXHAUSTED rate-limit errors, 503 / UNAVAILABLE
    overload errors, and 404 / NOT_FOUND missing model errors.

    The google-genai SDK surfaces these as an APIError with code == 429 and
    status "RESOURCE_EXHAUSTED". We also fall back to string matching so the
    detection survives SDK changes — but we never treat an arbitrary error
    as a rate limit.
    """
    code = getattr(err, "code", None)
    if code in (429, 503, 404):
        return True

    status = getattr(err, "status", None)
    if status and any(x in str(status) for x in ["RESOURCE_EXHAUSTED", "UNAVAILABLE", "NOT_FOUND"]):
        return True

    message = str(err)
    return any(x in message for x in ["429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "404", "NOT_FOUND"])


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
            # Only certain errors trigger fallback. Anything else
            # is a real failure — re-raise it untouched.
            if not _should_fallback(e):
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
