"""Access Streamlit-managed app secrets with a local no-secrets fallback."""

from __future__ import annotations

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError


def get_secret(name: str, default: str = "") -> str:
    """Return a string secret, or its default when no secrets file is configured."""
    try:
        value = st.secrets.get(name, default)
    except StreamlitSecretNotFoundError:
        return default

    if not isinstance(value, str):
        raise TypeError(f"Streamlit secret {name!r} must be a string.")
    return value.strip()
