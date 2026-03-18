"""Tests for tools/browser.py and tools/property_lookup.py."""

import json
from unittest.mock import MagicMock, patch

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
    def test_empty_url(self):
        from tools.browser import execute
        result = execute({"url": ""})
        assert "specify" in result.lower()

    def test_navigate_mocked(self):
        """Browser navigates and returns simplified page content."""
        from tools.browser import execute

        mock_page = MagicMock()
        mock_page.title.return_value = "Example Domain"
        mock_page.url = "https://example.com"
        mock_page.evaluate.side_effect = [
            "This domain is for use in illustrative examples.",  # content
            {"description": "Example domain"},  # metadata
        ]

        with patch("tools.browser._ensure_browser", return_value=mock_page):
            result = execute({"url": "https://example.com"})
            assert "Example Domain" in result
            assert "example.com" in result


class TestPropertyLookup:
    def test_no_address(self):
        result = json.loads(prop_execute({"address": ""}))
        assert result["error"] is not None
        assert "address" in result["error"].lower()

    def test_with_mocked_zillow(self):
        """Property lookup with mocked Zillow scraper."""
        mock_data = {
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
            "source": "zillow",
            "url": "https://www.zillow.com/...",
        }

        with patch("tools.property_lookup._scrape_zillow", return_value=mock_data):
            result = json.loads(prop_execute({"address": "456 Maple Drive, Austin TX"}))
            assert result["error"] is None
            assert result["price"] == 875000
            assert result["price_formatted"] == "$875,000"
            assert result["beds"] == 4
            assert "Finished basement" in result["features"]

    def test_zillow_scraper_success(self):
        """Property lookup succeeds with mocked Zillow scraper."""
        mock_data = {
            "price": 450000,
            "beds": 3,
            "baths": 2,
            "source": "zillow",
        }

        with patch("tools.property_lookup._scrape_zillow", return_value=mock_data):
            result = json.loads(prop_execute({"address": "123 Main St"}))
            assert result["error"] is None
            assert result["source"] == "zillow"

    def test_all_scrapers_fail(self):
        """Returns fallback when scraper fails."""
        with patch("tools.property_lookup._scrape_zillow", return_value=None), \
             patch("tools.browser.execute", return_value="Some page content here"):
            result = json.loads(prop_execute({"address": "123 Nowhere St"}))
            assert result is not None
            assert "address" in result
