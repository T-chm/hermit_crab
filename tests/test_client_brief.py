"""Tests for tools/client_brief.py."""

import json

import pytest

from tools.client_brief import execute
from tools.client_memory import _save_client


class TestClientBrief:
    def test_no_client_name(self):
        result = json.loads(execute({"client_name": ""}))
        assert result["error"] is not None
        assert "specify" in result["error"].lower()

    def test_unknown_client(self, tmp_clients_dir):
        result = json.loads(execute({"client_name": "Nobody Here"}))
        assert result["error"] is not None
        assert "No profile found" in result["error"]

    def test_basic_structure(self, tmp_clients_dir, sample_profile, mock_llm_call):
        _save_client(sample_profile)
        result = json.loads(execute({"client_name": "Zhang Wei"}))
        assert result["error"] is None
        assert result["client_name"] == "Zhang Wei & Li Na"
        assert "generated_at" in result
        assert "brief" in result

    def test_all_sections_present(self, tmp_clients_dir, sample_profile, mock_llm_call):
        _save_client(sample_profile)
        result = json.loads(execute({"client_name": "Zhang Wei"}))
        brief = result["brief"]
        assert "recent_topics" in brief
        assert "preferences" in brief
        assert "property_history" in brief
        assert "particularities" in brief

    def test_preferences_formatting(self, tmp_clients_dir, sample_profile, mock_llm_call):
        _save_client(sample_profile)
        result = json.loads(execute({"client_name": "Zhang Wei"}))
        prefs = result["brief"]["preferences"]
        assert "$700k" in prefs["budget"]
        assert "$900k" in prefs["budget"]
        assert "finished basement" in prefs["must_haves"]
        assert "traffic noise" in prefs["dealbreakers"]

    def test_property_history_items(self, tmp_clients_dir, sample_profile, mock_llm_call):
        _save_client(sample_profile)
        result = json.loads(execute({"client_name": "Zhang Wei"}))
        items = result["brief"]["property_history"]["items"]
        assert len(items) == 4
        addresses = [i["address"] for i in items]
        assert "123 Oak Lane" in addresses
        assert "456 Maple Drive" in addresses

    def test_no_property(self, tmp_clients_dir, sample_profile, mock_llm_call):
        _save_client(sample_profile)
        result = json.loads(execute({"client_name": "Zhang Wei"}))
        assert result["property"] is None
        assert "property_alignment" not in result["brief"]

    def test_with_simulated_property(self, tmp_clients_dir, sample_profile, mock_llm_call, monkeypatch):
        """Test brief with property data by mocking _fetch_property."""
        _save_client(sample_profile)
        mock_prop = {
            "address": "456 Maple Drive",
            "price": 875000,
            "price_formatted": "$875,000",
            "beds": 4,
            "baths": 3,
            "sqft": 2800,
            "features": ["Finished basement", "Fenced yard"],
        }
        import tools.client_brief as cb
        monkeypatch.setattr(cb, "_fetch_property", lambda addr: mock_prop)
        result = json.loads(execute({"client_name": "Zhang Wei", "address": "456 Maple Drive"}))
        assert result["property"] is not None
        assert result["property"]["price"] == 875000
        assert "property_alignment" in result["brief"]
        assert result["brief"]["property_alignment"]["score"] == "Strong match"

    def test_property_lookup_import_error(self, tmp_clients_dir, sample_profile, mock_llm_call, monkeypatch):
        """Graceful handling when property_lookup not available."""
        _save_client(sample_profile)
        import tools.client_brief as cb
        monkeypatch.setattr(cb, "_fetch_property", lambda addr: None)
        result = json.loads(execute({"client_name": "Zhang Wei", "address": "456 Maple Drive"}))
        assert result["error"] is None
        assert result["property"] is None
