"""Shared fixtures for Hermit Crab RE tests."""

import json
import shutil
from pathlib import Path

import pytest


@pytest.fixture
def tmp_clients_dir(tmp_path, monkeypatch):
    """Temporary directory for client profiles."""
    d = tmp_path / "clients"
    d.mkdir()
    import tools.client_memory as cm
    monkeypatch.setattr(cm, "CLIENTS_DIR", d)
    return d


@pytest.fixture
def tmp_inbox_dir(tmp_path, monkeypatch):
    """Temporary directory for text file ingestion."""
    d = tmp_path / "inbox"
    d.mkdir()
    import tools.client_memory as cm
    monkeypatch.setattr(cm, "INBOX_DIR", d)
    return d


@pytest.fixture
def test_wechat_dir():
    """Path to existing test WeChat export data."""
    return Path(__file__).parent.parent / "test_data" / "wechat_export"


@pytest.fixture
def sample_profile():
    """Pre-built Zhang Wei profile for tests that need an existing client."""
    return {
        "name": "Zhang Wei & Li Na",
        "created": "2026-01-10T10:00:00",
        "last_updated": "2026-03-15T09:00:00",
        "source": "wechat",
        "vectors": {
            "recent_topics": [
                {"date": "2026-03-08", "summary": "Expanded budget to $900k, finished basement mandatory"},
                {"date": "2026-03-12", "summary": "Found matching property 456 Maple Drive, showing Saturday"},
            ],
            "preferences": {
                "budget_min": 700000,
                "budget_max": 900000,
                "locations": ["Maple Heights"],
                "must_haves": ["finished basement", "fenced yard", "home office"],
                "dealbreakers": ["traffic noise"],
                "style": "Single family",
            },
            "property_history": [
                {"address": "123 Oak Lane", "status": "rejected", "date": "2026-01-18",
                 "notes": "Kitchen great but backyard too small for dogs"},
                {"address": "789 Elm St", "status": "rejected", "date": "2026-01-25",
                 "notes": "Traffic noise, wife can't work from home"},
                {"address": "55 Cedar Court", "status": "rejected", "date": "2026-02-15",
                 "notes": "No finished basement"},
                {"address": "456 Maple Drive", "status": "pending", "date": "2026-03-15",
                 "notes": "Showing scheduled Saturday 2 PM"},
            ],
            "particularities": [
                "Two dogs, need fenced yard",
                "Li Na works from home, needs quiet",
                "Son plays soccer",
                "Li Na recently promoted",
            ],
        },
        "raw_sources": [
            {"file": "wechat:张伟 & 李娜", "ingested": "2026-03-17T10:00:00", "message_count": 19}
        ],
    }


MOCK_EXTRACT_RESPONSE = {
    "recent_topics": [
        {"date": "2026-03-08", "summary": "Budget expanded to $900k, finished basement required"},
    ],
    "preferences": {
        "budget_min": 700000,
        "budget_max": 900000,
        "locations": ["Maple Heights"],
        "must_haves": ["finished basement", "fenced yard"],
        "dealbreakers": ["traffic noise"],
        "style": "",
    },
    "property_history": [
        {"address": "123 Oak Lane", "status": "rejected", "date": "2026-01-18",
         "notes": "Backyard too small"},
    ],
    "particularities": ["Two dogs", "Son plays soccer"],
}

MOCK_SUMMARY_RESPONSE = {
    "recent_summary": "Client recently expanded budget to $900k with finished basement as mandatory.",
    "preferences_summary": "Looking for single family in Maple Heights with fenced yard and finished basement.",
    "history_summary": "Shown 4 properties, rejected 3 due to yard size, noise, and missing basement.",
    "particularities_summary": "Has two dogs needing fenced yard, son plays soccer, wife works from home.",
}

MOCK_ALIGNMENT_RESPONSE = {
    "matches": ["Within budget at $875k", "Has finished basement", "Quiet cul-de-sac"],
    "concerns": ["HOA not previously discussed"],
    "score": "Strong match",
}


@pytest.fixture
def mock_llm_extract(monkeypatch):
    """Patch _llm_extract to return deterministic data."""
    def _mock(text):
        return MOCK_EXTRACT_RESPONSE.copy()

    import tools.client_memory as cm
    monkeypatch.setattr(cm, "_llm_extract", _mock)
    return _mock


@pytest.fixture
def mock_llm_call(monkeypatch):
    """Patch _llm_call in client_brief to return deterministic summaries."""
    def _mock(prompt, msg):
        if "alignment" in prompt.lower() or "property" in prompt.lower():
            return MOCK_ALIGNMENT_RESPONSE.copy()
        return MOCK_SUMMARY_RESPONSE.copy()

    import tools.client_brief as cb
    monkeypatch.setattr(cb, "_llm_call", _mock)
    return _mock
