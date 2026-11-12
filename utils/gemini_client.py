"""Shared Gemini client helpers.

Both Challenge 1 (travel recommendation narrative) and Challenge 2 (receipt
OCR) talk to the same Gemini model through the same `google-genai` client.
This module centralizes API-key lookup and the structured-JSON request
pattern so both features stay in sync and only configure the model once.
"""

from __future__ import annotations

from typing import Any

from google import genai

from utils.app_secrets import get_secret

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"


def get_gemini_api_key() -> str:
    """Support both Google and Gemini key names in Streamlit secrets."""
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        value = get_secret(name)
        if value and not value.startswith("your_"):
            return value
    return ""


def gemini_configured() -> bool:
    return bool(get_gemini_api_key())


def get_gemini_model() -> str:
    return get_secret("GEMINI_MODEL", DEFAULT_GEMINI_MODEL) or DEFAULT_GEMINI_MODEL


def get_gemini_client() -> genai.Client:
    """Build a Gemini client, raising a clear error when no key is configured."""
    api_key = get_gemini_api_key()
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY or GEMINI_API_KEY is not configured in Streamlit secrets."
        )
    return genai.Client(api_key=api_key)


def run_structured_interaction(
    *,
    contents: list[dict[str, Any]],
    json_schema: dict[str, Any],
    model: str | None = None,
) -> str:
    """Send a multi-part prompt to Gemini and return the raw JSON response text.

    `contents` follows the `interactions.create` input format: a list of
    `{"type": "text", "text": ...}` and/or `{"type": "image"|"document",
    "data": base64, "mime_type": ...}` parts.
    """
    client = get_gemini_client()
    interaction = client.interactions.create(
        model=model or get_gemini_model(),
        input=contents,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": json_schema,
        },
        stream=False,
        store=False,
    )
    output_text = getattr(interaction, "output_text", None)
    if not isinstance(output_text, str):
        raise TypeError("Gemini did not return a standard text response.")
    if not output_text:
        raise ValueError("Gemini returned an empty response.")
    return output_text
