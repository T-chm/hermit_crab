"""Integration tests — full pipeline with real test data and mocked LLM."""

import json
from pathlib import Path

import pytest

from tools.client_memory import _save_client, _find_client, execute as mem_execute
from tools.client_brief import execute as brief_execute


class TestFullPipelineZhangWei:
    """Ingest WeChat → query → brief for the primary test client."""

    def test_ingest_and_query(self, tmp_clients_dir, test_wechat_dir, mock_llm_extract, monkeypatch):
        import tools.client_memory as cm
        monkeypatch.setattr(cm, "_DEFAULT_WECHAT_DIR", test_wechat_dir)

        result = mem_execute({"action": "ingest_wechat", "client_name": "张伟"})
        assert "张伟" in result

        profile = _find_client("张伟")
        assert profile is not None
        v = profile["vectors"]
        assert len(v["recent_topics"]) > 0
        assert v["preferences"]["budget_max"] == 900000
        assert "finished basement" in [h.lower() for h in v["preferences"]["must_haves"]] or len(v["preferences"]["must_haves"]) > 0
        assert len(v["property_history"]) > 0
        assert len(v["particularities"]) > 0

    def test_brief_generation(self, tmp_clients_dir, sample_profile, mock_llm_call):
        _save_client(sample_profile)
        result = json.loads(brief_execute({"client_name": "Zhang Wei"}))
        assert result["error"] is None
        assert result["client_name"] == "Zhang Wei & Li Na"

        brief = result["brief"]
        assert brief["preferences"]["budget"] == "$700k - $900k"
        assert len(brief["property_history"]["items"]) == 4
        assert len(brief["particularities"]["items"]) == 4
        # Summary is populated by LLM mock — check structure exists
        assert "summary" in brief["recent_topics"]


class TestFullPipelineDavidChen:
    def test_ingest_and_query(self, tmp_clients_dir, test_wechat_dir, mock_llm_extract, monkeypatch):
        import tools.client_memory as cm
        monkeypatch.setattr(cm, "_DEFAULT_WECHAT_DIR", test_wechat_dir)

        mem_execute({"action": "ingest_wechat", "client_name": "David"})
        profile = _find_client("David")
        assert profile is not None
        assert profile["source"] == "wechat"


class TestFullPipelineWangFang:
    def test_ingest_and_query(self, tmp_clients_dir, test_wechat_dir, mock_llm_extract, monkeypatch):
        import tools.client_memory as cm
        monkeypatch.setattr(cm, "_DEFAULT_WECHAT_DIR", test_wechat_dir)

        mem_execute({"action": "ingest_wechat", "client_name": "王芳"})
        profile = _find_client("王芳")
        assert profile is not None


class TestReingestIncremental:
    def test_merge_not_overwrite(self, tmp_clients_dir, test_wechat_dir, mock_llm_extract, monkeypatch):
        import tools.client_memory as cm
        monkeypatch.setattr(cm, "_DEFAULT_WECHAT_DIR", test_wechat_dir)

        # First ingest
        mem_execute({"action": "ingest_wechat", "client_name": "David"})
        profile1 = _find_client("David")
        sources1 = len(profile1["raw_sources"])

        # Second ingest — should add, not replace
        mem_execute({"action": "ingest_wechat", "client_name": "David"})
        profile2 = _find_client("David")
        assert len(profile2["raw_sources"]) == sources1 + 1


class TestBriefAfterIngest:
    def test_all_clients(self, tmp_clients_dir, test_wechat_dir, mock_llm_extract, mock_llm_call, monkeypatch):
        import tools.client_memory as cm
        monkeypatch.setattr(cm, "_DEFAULT_WECHAT_DIR", test_wechat_dir)

        # Ingest all
        mem_execute({"action": "ingest_wechat"})

        # Brief for each
        for name in ["张伟", "David", "王芳"]:
            result = json.loads(brief_execute({"client_name": name}))
            assert result["error"] is None, f"Brief failed for {name}: {result['error']}"
            assert "brief" in result


class TestListAfterIngest:
    def test_all_shown(self, tmp_clients_dir, test_wechat_dir, mock_llm_extract, monkeypatch):
        import tools.client_memory as cm
        monkeypatch.setattr(cm, "_DEFAULT_WECHAT_DIR", test_wechat_dir)

        mem_execute({"action": "ingest_wechat"})
        result = mem_execute({"action": "list_clients"})
        assert "Clients (3)" in result


class TestDirectDispatch:
    def test_prep_for_meeting(self):
        from app import _try_direct_dispatch
        result = _try_direct_dispatch("prep me for my meeting with Zhang Wei at 456 Maple Drive")
        assert result is not None
        assert result[0] == "client_brief"
        assert "zhang wei" in result[1]["client_name"].lower()
        assert "456 maple drive" in result[1]["address"].lower()

    def test_brief_me_on(self):
        from app import _try_direct_dispatch
        result = _try_direct_dispatch("brief me on David Chen")
        assert result is not None
        assert result[0] == "client_brief"
        assert "david chen" in result[1]["client_name"].lower()

    def test_list_clients(self):
        from app import _try_direct_dispatch
        result = _try_direct_dispatch("list my clients")
        assert result is not None
        assert result[0] == "client_memory"
        assert result[1]["action"] == "list_clients"

    def test_ingest_wechat(self):
        from app import _try_direct_dispatch
        result = _try_direct_dispatch("ingest wechat conversations")
        assert result is not None
        assert result[0] == "client_memory"
        assert result[1]["action"] == "ingest_wechat"

    def test_look_up_property(self):
        from app import _try_direct_dispatch
        result = _try_direct_dispatch("look up 456 Maple Drive Austin TX")
        assert result is not None
        assert result[0] == "property_lookup"
        assert "456" in result[1]["address"]

    def test_zillow_url_dispatch(self):
        """Sharing a Zillow listing URL should route to property_lookup with extracted address."""
        from app import _try_direct_dispatch
        result = _try_direct_dispatch(
            "Get listing information from this link: "
            "https://www.zillow.com/homedetails/786-Lakewood-Dr-Sunnyvale-CA-94089/19493113_zpid/"
            "?utm_campaign=zillowwebmessage&utm_medium=referral&utm_source=txtshare"
        )
        assert result is not None
        assert result[0] == "property_lookup"
        assert "786" in result[1]["address"]
        assert "Lakewood" in result[1]["address"]
        assert "Sunnyvale" in result[1]["address"]

    def test_zillow_url_short(self):
        """Bare Zillow URL without surrounding text."""
        from app import _try_direct_dispatch
        result = _try_direct_dispatch(
            "https://www.zillow.com/homedetails/123-Main-St-Austin-TX-78701/12345_zpid/"
        )
        assert result is not None
        assert result[0] == "property_lookup"
        assert "123" in result[1]["address"]
        assert "Main" in result[1]["address"]

    def test_generic_url_dispatch(self):
        """Non-property URLs should route to browser tool."""
        from app import _try_direct_dispatch
        result = _try_direct_dispatch("check out https://example.com/article")
        assert result is not None
        assert result[0] == "browser"
        assert "example.com" in result[1]["url"]

    def test_redfin_url_dispatch(self):
        """Redfin URLs should extract address and route to property_lookup."""
        from app import _try_direct_dispatch
        result = _try_direct_dispatch(
            "https://www.redfin.com/CA/Sunnyvale/786-Lakewood-Dr-94089/home/1234567"
        )
        assert result is not None
        assert result[0] == "property_lookup"
        assert "786" in result[1]["address"]
        assert "Sunnyvale" in result[1]["address"]
