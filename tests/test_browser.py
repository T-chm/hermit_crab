"""Tests for tools/browser.py and tools/property_lookup.py."""

import json

import pytest

from tools.property_lookup import execute as prop_execute, _format_price


class TestFormatPrice:
    def test_integer(self):
        assert _format_price(875000) == "$875,000"

    def test_none(self):
        assert _format_price(None) == ""

    def test_string(self):
        assert _format_price("N/A") == "N/A"


class TestBrowserTool:
    def test_no_bridge(self):
        """Browser tool returns error when bridge not connected."""
        from tools.browser import execute
        result = execute({"task": "go to example.com"})
        assert "bridge" in result.lower() or "not available" in result.lower() or "error" in result.lower()

    def test_empty_task(self):
        from tools.browser import execute
        result = execute({"task": ""})
        assert "specify" in result.lower()


class TestPropertyLookup:
    def test_no_address(self):
        result = json.loads(prop_execute({"address": ""}))
        assert result["error"] is not None
        assert "address" in result["error"].lower()

    def test_with_mocked_browser(self, monkeypatch):
        """Mock the browser tool to return simulated Zillow data."""
        mock_response = json.dumps({
            "address": "456 Maple Drive, Austin, TX",
            "price": 875000,
            "beds": 4,
            "baths": 3,
            "sqft": 2800,
            "days_on_market": 12,
            "status": "Active",
            "description": "Beautiful modern home with finished basement",
            "features": ["Finished basement", "Fenced yard", "2-car garage"],
            "property_type": "Single Family",
            "year_built": 2018,
        })

        import tools.browser
        monkeypatch.setattr(tools.browser, "execute", lambda args: mock_response)

        result = json.loads(prop_execute({"address": "456 Maple Drive, Austin TX"}))
        assert result["error"] is None
        assert result["price"] == 875000
        assert result["price_formatted"] == "$875,000"
        assert result["beds"] == 4
        assert "Finished basement" in result["features"]

    def test_browser_failure(self, monkeypatch):
        """Property lookup handles browser failure gracefully."""
        import tools.browser
        monkeypatch.setattr(tools.browser, "execute", lambda args: "Browser task failed: extension not connected")

        result = json.loads(prop_execute({"address": "123 Main St"}))
        # Should return something parseable, not crash
        assert "error" in result or "description" in result

    def test_browser_returns_non_json(self, monkeypatch):
        """Property lookup handles non-JSON browser response."""
        import tools.browser
        monkeypatch.setattr(tools.browser, "execute", lambda args: "The property at 123 Main St is listed at $500k with 3 beds")

        result = json.loads(prop_execute({"address": "123 Main St"}))
        assert result is not None  # Should not crash
        assert "description" in result or "error" in result
