"""Property Lookup — scrape public property data via headless browser."""

import json
import re
import urllib.parse

DEFINITION = {
    "type": "function",
    "function": {
        "name": "property_lookup",
        "description": (
            "Look up property details by address. Retrieves price, beds, baths, "
            "sqft, days on market, description, and features from public real "
            "estate listings (Zillow, Redfin, Realtor.com). "
            "Use when the user asks about a specific property or address."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "Property address (e.g. '456 Maple Drive, Austin TX').",
                },
            },
            "required": ["address"],
        },
    },
}


def _format_price(price) -> str:
    if price is None:
        return ""
    try:
        return f"${int(price):,}"
    except (ValueError, TypeError):
        return str(price)


def _scrape_zillow(address: str) -> dict | None:
    """Scrape property data from Zillow."""
    from tools.browser import _ensure_browser

    query = urllib.parse.quote(address)
    url = f"https://www.zillow.com/homes/{query}_rb/"

    page = None
    try:
        page = _ensure_browser()
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(3000)

        # Extract property data via JS
        data = page.evaluate("""() => {
            const result = {};

            // Try to get price
            const priceEl = document.querySelector('[data-testid="price"], .summary-container .price, .hdp__sc-1s2b8ok-0, span[data-testid="price"]');
            if (priceEl) {
                const priceText = priceEl.innerText.replace(/[^0-9]/g, '');
                result.price = parseInt(priceText) || null;
            }

            // Beds, baths, sqft from summary
            const summaryItems = document.querySelectorAll('[data-testid="bed-bath-beyond"] span, .summary-container .bed-bath-item, .bdbs span');
            const summaryText = document.body.innerText;

            const bedMatch = summaryText.match(/(\\d+)\\s*(?:bd|bed|bedroom)/i);
            if (bedMatch) result.beds = parseInt(bedMatch[1]);

            const bathMatch = summaryText.match(/(\\d+\\.?\\d*)\\s*(?:ba|bath|bathroom)/i);
            if (bathMatch) result.baths = parseFloat(bathMatch[1]);

            const sqftMatch = summaryText.match(/([\\d,]+)\\s*(?:sq\\s*ft|sqft|square\\s*feet)/i);
            if (sqftMatch) result.sqft = parseInt(sqftMatch[1].replace(/,/g, ''));

            // Address
            const addrEl = document.querySelector('[data-testid="bdp-header-address"], h1, .hdp__sc-1s2b8ok-0');
            if (addrEl) result.address = addrEl.innerText.trim();

            // Description
            const descEl = document.querySelector('[data-testid="description"], .comments, .Text-c11n-8-100-2__sc-aiai24-0');
            if (descEl) result.description = descEl.innerText.substring(0, 300).trim();

            // Status and days on market
            const statusMatch = summaryText.match(/(Active|Pending|Sold|For Sale|Under Contract)/i);
            if (statusMatch) result.status = statusMatch[1];

            const domMatch = summaryText.match(/(\\d+)\\s*(?:day|days)\\s*(?:on|ago)/i);
            if (domMatch) result.days_on_market = parseInt(domMatch[1]);

            // Year built
            const yearMatch = summaryText.match(/(?:built|year\\s*built)[:\\s]*(\\d{4})/i);
            if (yearMatch) result.year_built = parseInt(yearMatch[1]);

            // Features from facts section
            const features = [];
            document.querySelectorAll('.fact-value, .ds-overview-data li, [data-testid="fact-item"]').forEach(el => {
                const t = el.innerText.trim();
                if (t && t.length < 60) features.push(t);
            });
            if (features.length) result.features = features.slice(0, 15);

            // Property type
            const typeMatch = summaryText.match(/(Single Family|Condo|Townhouse|Multi[- ]Family|Manufactured|Apartment)/i);
            if (typeMatch) result.property_type = typeMatch[1];

            result.source = 'zillow';
            result.url = window.location.href;

            return result;
        }""")

        if data and (data.get("price") or data.get("beds")):
            return data
        return None

    except Exception:
        return None
    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass


def _scrape_redfin(address: str) -> dict | None:
    """Scrape property data from Redfin."""
    from tools.browser import _ensure_browser

    query = urllib.parse.quote(address)
    url = f"https://www.redfin.com/search#query={query}"

    page = None
    try:
        page = _ensure_browser()
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(3000)

        data = page.evaluate("""() => {
            const result = {};
            const text = document.body.innerText;

            const priceMatch = text.match(/\\$([\\d,]+)/);
            if (priceMatch) result.price = parseInt(priceMatch[1].replace(/,/g, ''));

            const bedMatch = text.match(/(\\d+)\\s*(?:Bd|Bed)/i);
            if (bedMatch) result.beds = parseInt(bedMatch[1]);

            const bathMatch = text.match(/(\\d+\\.?\\d*)\\s*(?:Ba|Bath)/i);
            if (bathMatch) result.baths = parseFloat(bathMatch[1]);

            const sqftMatch = text.match(/([\\d,]+)\\s*(?:Sq\\s*Ft|sqft)/i);
            if (sqftMatch) result.sqft = parseInt(sqftMatch[1].replace(/,/g, ''));

            result.source = 'redfin';
            result.url = window.location.href;
            return result;
        }""")

        if data and (data.get("price") or data.get("beds")):
            return data
        return None

    except Exception:
        return None
    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass


def execute(args: dict) -> str:
    address = args.get("address", "").strip()
    if not address:
        return json.dumps({"error": "Please provide a property address."})

    # Try sources in order
    for scraper in [_scrape_zillow, _scrape_redfin]:
        try:
            data = scraper(address)
            if data:
                data.setdefault("address", address)
                data["price_formatted"] = _format_price(data.get("price"))
                data["error"] = None
                return json.dumps(data, ensure_ascii=False)
        except Exception:
            continue

    # Fallback: use the browser tool to get page content
    try:
        from tools.browser import execute as browser_exec
        query = urllib.parse.quote(address)
        raw = browser_exec({"url": f"https://www.zillow.com/homes/{query}_rb/"})
        return json.dumps({
            "address": address,
            "description": raw[:500] if raw else "No data found.",
            "error": "Could not extract structured data. Raw page content included.",
        })
    except Exception as e:
        return json.dumps({"address": address, "error": f"Property lookup failed: {e}"})
