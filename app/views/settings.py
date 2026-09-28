"""Settings: API key, default model, monthly cost cap (user journey J0)."""

import streamlit as st

from app import state
from core import config
from core.llm import ClaudeLLM, LLMError


def render() -> None:
    st.title("Settings")
    settings = state.load_settings()

    st.subheader("Anthropic API key")
    st.caption("Stored only in the local `.env` file, which is never committed.")
    current = state.api_key()
    st.write(f"Current key: `…{current[-4:]}`" if current else "No key saved.")
    key = st.text_input("New API key", type="password", placeholder="sk-ant-…")
    if st.button("Validate and save key", disabled=not key):
        try:
            ClaudeLLM(settings["model"], api_key=key).check_key()
        except LLMError as exc:
            st.error(str(exc))
        else:
            state.save_api_key(key)
            st.success("Key validated and saved.")

    st.subheader("Defaults")
    with st.form("defaults"):
        models = list(config.MODELS)
        model = st.selectbox("Model", models, index=models.index(settings["model"]),
                             format_func=lambda m: config.MODELS[m]["label"])
        cap = st.number_input("Monthly cost cap (USD, 0 = no cap)", min_value=0.0, step=5.0,
                              value=float(settings["monthly_cost_cap"]),
                              help="You'll be asked to confirm before a run that would exceed it.")
        if st.form_submit_button("Save"):
            state.save_settings({**settings, "model": model, "monthly_cost_cap": cap})
            st.success("Saved.")
