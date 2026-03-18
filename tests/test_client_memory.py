"""Tests for tools/client_memory.py."""

import json
from pathlib import Path

import pytest

from tools.client_memory import (
    _chunk_messages,
    _empty_profile,
    _find_client,
    _load_client,
    _merge_vectors,
    _normalize_name,
    _save_client,
    execute,
)


# ---------------------------------------------------------------------------
# _normalize_name
# ---------------------------------------------------------------------------
class TestNormalizeName:
    def test_basic(self):
        assert _normalize_name("John Doe") == "john_doe"

    def test_special_chars(self):
        assert _normalize_name("Zhang Wei & Li Na") == "zhang_wei__li_na"

    def test_chinese(self):
        result = _normalize_name("王芳 (Fang)")
        assert "fang" in result.lower()

    def test_empty(self):
        assert _normalize_name("") == ""


# ---------------------------------------------------------------------------
# _empty_profile
# ---------------------------------------------------------------------------
class TestEmptyProfile:
    def test_structure(self):
        p = _empty_profile("Test Client", source="wechat")
        assert p["name"] == "Test Client"
        assert p["source"] == "wechat"
        assert "vectors" in p
        v = p["vectors"]
        assert "recent_topics" in v
        assert "preferences" in v
        assert "property_history" in v
        assert "particularities" in v
        assert v["preferences"]["budget_min"] is None
        assert v["preferences"]["must_haves"] == []


# ---------------------------------------------------------------------------
# save / load / find
# ---------------------------------------------------------------------------
class TestClientIO:
    def test_save_and_load(self, tmp_clients_dir, sample_profile):
        _save_client(sample_profile)
        loaded = _load_client("Zhang Wei & Li Na")
        assert loaded is not None
        assert loaded["name"] == sample_profile["name"]
        assert loaded["vectors"]["preferences"]["budget_max"] == 900000

    def test_load_nonexistent(self, tmp_clients_dir):
        assert _load_client("Nobody") is None

    def test_find_exact(self, tmp_clients_dir, sample_profile):
        _save_client(sample_profile)
        found = _find_client("Zhang Wei & Li Na")
        assert found is not None
        assert found["name"] == "Zhang Wei & Li Na"

    def test_find_partial(self, tmp_clients_dir, sample_profile):
        _save_client(sample_profile)
        found = _find_client("Zhang")
        assert found is not None

    def test_find_not_found(self, tmp_clients_dir):
        assert _find_client("Nobody Here") is None


# ---------------------------------------------------------------------------
# _merge_vectors
# ---------------------------------------------------------------------------
class TestMergeVectors:
    def test_preferences_overwrite(self):
        existing = _empty_profile("Test")
        existing["vectors"]["preferences"]["budget_min"] = 500000
        extracted = {"preferences": {"budget_min": 700000, "budget_max": 900000}}
        _merge_vectors(existing, extracted)
        assert existing["vectors"]["preferences"]["budget_min"] == 700000
        assert existing["vectors"]["preferences"]["budget_max"] == 900000

    def test_preferences_list_dedup(self):
        existing = _empty_profile("Test")
        existing["vectors"]["preferences"]["must_haves"] = ["pool", "garage"]
        extracted = {"preferences": {"must_haves": ["garage", "basement"]}}
        _merge_vectors(existing, extracted)
        mh = existing["vectors"]["preferences"]["must_haves"]
        assert mh == ["pool", "garage", "basement"]

    def test_topics_cap_at_20(self):
        existing = _empty_profile("Test")
        existing["vectors"]["recent_topics"] = [{"date": f"2026-01-{i:02d}", "summary": f"topic {i}"} for i in range(18)]
        extracted = {"recent_topics": [{"date": "2026-02-01", "summary": "new1"}, {"date": "2026-02-02", "summary": "new2"}, {"date": "2026-02-03", "summary": "new3"}]}
        _merge_vectors(existing, extracted)
        assert len(existing["vectors"]["recent_topics"]) == 20

    def test_property_history_merge_by_address(self):
        existing = _empty_profile("Test")
        existing["vectors"]["property_history"] = [
            {"address": "123 Oak Lane", "status": "shown", "date": "2026-01-15", "notes": "liked"}
        ]
        extracted = {"property_history": [
            {"address": "123 Oak Lane", "status": "rejected", "date": "2026-01-18", "notes": "yard too small"},
            {"address": "456 Maple Dr", "status": "pending", "date": "2026-03-15", "notes": "showing"},
        ]}
        _merge_vectors(existing, extracted)
        ph = existing["vectors"]["property_history"]
        assert len(ph) == 2
        oak = next(p for p in ph if "oak" in p["address"].lower())
        assert oak["status"] == "rejected"  # overwritten

    def test_particularities_dedup(self):
        existing = _empty_profile("Test")
        existing["vectors"]["particularities"] = ["Has a dog", "Works from home"]
        extracted = {"particularities": ["Has a dog", "Son plays soccer"]}
        _merge_vectors(existing, extracted)
        parts = existing["vectors"]["particularities"]
        assert len(parts) == 3
        assert parts.count("Has a dog") == 1


# ---------------------------------------------------------------------------
# _chunk_messages
# ---------------------------------------------------------------------------
class TestChunkMessages:
    def test_small(self):
        msgs = [{"time": "2026-01-01 10:00", "content": "Hello"}]
        chunks = _chunk_messages(msgs)
        assert len(chunks) == 1

    def test_large(self):
        msgs = [{"time": f"2026-01-01 {i:02d}:00", "content": "x" * 500} for i in range(30)]
        chunks = _chunk_messages(msgs, max_tokens=1000)
        assert len(chunks) > 1


# ---------------------------------------------------------------------------
# execute() actions
# ---------------------------------------------------------------------------
class TestExecute:
    def test_list_clients_empty(self, tmp_clients_dir):
        result = execute({"action": "list_clients"})
        assert "No client profiles" in result

    def test_list_clients_populated(self, tmp_clients_dir, sample_profile):
        _save_client(sample_profile)
        result = execute({"action": "list_clients"})
        assert "Zhang Wei" in result
        assert "$700k" in result or "$900k" in result

    def test_query_existing(self, tmp_clients_dir, sample_profile):
        _save_client(sample_profile)
        result = execute({"action": "query", "client_name": "Zhang Wei"})
        data = json.loads(result)
        assert data["name"] == "Zhang Wei & Li Na"

    def test_query_unknown(self, tmp_clients_dir):
        result = execute({"action": "query", "client_name": "Nobody"})
        assert "No profile found" in result

    def test_delete_existing(self, tmp_clients_dir, sample_profile):
        _save_client(sample_profile)
        result = execute({"action": "delete", "client_name": "Zhang Wei & Li Na"})
        assert "Deleted" in result
        assert _load_client("Zhang Wei & Li Na") is None

    def test_delete_nonexistent(self, tmp_clients_dir):
        result = execute({"action": "delete", "client_name": "Nobody"})
        assert "No profile found" in result

    def test_update_new_client(self, tmp_clients_dir, mock_llm_extract):
        result = execute({"action": "update", "client_name": "New Client", "info": "Budget is $500k"})
        assert "Updated" in result
        loaded = _find_client("New Client")
        assert loaded is not None

    def test_update_existing(self, tmp_clients_dir, sample_profile, mock_llm_extract):
        _save_client(sample_profile)
        result = execute({"action": "update", "client_name": "Zhang Wei", "info": "Now wants a pool"})
        assert "Updated" in result

    def test_ingest_wechat_all(self, tmp_clients_dir, test_wechat_dir, mock_llm_extract, monkeypatch):
        import tools.client_memory as cm
        monkeypatch.setattr(cm, "_DEFAULT_WECHAT_DIR", test_wechat_dir)
        result = execute({"action": "ingest_wechat"})
        assert "ingestion complete" in result.lower()
        assert "张伟" in result or "Zhang" in result
        assert "David" in result

    def test_ingest_wechat_single(self, tmp_clients_dir, test_wechat_dir, mock_llm_extract, monkeypatch):
        import tools.client_memory as cm
        monkeypatch.setattr(cm, "_DEFAULT_WECHAT_DIR", test_wechat_dir)
        result = execute({"action": "ingest_wechat", "client_name": "David"})
        assert "David" in result
        # Should NOT have Zhang Wei
        assert "张伟" not in result

    def test_ingest_wechat_missing_dir(self, tmp_clients_dir):
        result = execute({"action": "ingest_wechat", "wechat_dir": "/nonexistent/path"})
        assert "not found" in result.lower()

    def test_ingest_folder_txt(self, tmp_clients_dir, tmp_inbox_dir, mock_llm_extract):
        # Create a test transcript
        (tmp_inbox_dir / "john_smith_sms.txt").write_text(
            "John: Hey, I'm looking for a 3-bed house around $600k\n"
            "Agent: Sure, any preferred areas?\n"
            "John: Near downtown if possible\n"
        )
        result = execute({"action": "ingest_folder"})
        assert "ingestion complete" in result.lower()

    def test_ingest_folder_empty(self, tmp_clients_dir, tmp_inbox_dir):
        result = execute({"action": "ingest_folder"})
        assert "No .txt or .csv" in result
