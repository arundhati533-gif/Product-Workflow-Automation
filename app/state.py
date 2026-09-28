"""Shared app state: storage, settings, the LLM client and page routing."""

from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv, set_key

from core import config
from core.llm import ClaudeLLM
from core.pipeline import Pipeline
from core.storage import Storage

ENV_PATH = config.ROOT / ".env"
DEFAULT_SETTINGS = {"model": config.DEFAULT_MODEL, "monthly_cost_cap": 0.0}

load_dotenv(ENV_PATH)


@st.cache_resource
def _storage(path: str) -> Storage:
    return Storage(path)


def storage() -> Storage:
    if "storage" in st.session_state:  # tests inject an in-memory store
        return st.session_state["storage"]
    return _storage(os.environ.get("MTB_DB_PATH", str(config.DB_PATH)))


# --- Settings ------------------------------------------------------------------

def _settings_path() -> Path:
    return Path(os.environ.get("MTB_SETTINGS_PATH", config.DATA_DIR / "settings.json"))


def load_settings() -> dict:
    try:
        return DEFAULT_SETTINGS | json.loads(_settings_path().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2))


def api_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY", "")


def save_api_key(key: str) -> None:
    ENV_PATH.touch(exist_ok=True)
    set_key(str(ENV_PATH), "ANTHROPIC_API_KEY", key)
    os.environ["ANTHROPIC_API_KEY"] = key


# --- LLM and pipeline ----------------------------------------------------------

def llm():
    if "llm" in st.session_state:  # tests and demo mode inject a replacement
        return st.session_state["llm"]
    if not api_key():
        return None
    return ClaudeLLM(load_settings()["model"], api_key=api_key())


def pipeline() -> Pipeline:
    return Pipeline(storage(), llm())


# --- Routing ---------------------------------------------------------------------

def go(view: str, **params) -> None:
    st.session_state["view"] = view
    st.session_state.update(params)
    st.rerun()


def current_view() -> str:
    return st.session_state.get("view", "projects")
