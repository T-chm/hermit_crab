"""Property Lookup — scrape public property data via Zillow autocomplete + browser."""

import json
import re
import urllib.parse
import urllib.request

DEFINITION = {
    "type": "function",
    "function": {
        "name": "property_lookup",
        "description": (
            "Look up property details by address. Retrieves price, beds, baths, "
            "sqft, days on market, description, and features from public real "
            "estate listings. Use when the user asks about a specific property or address."
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

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _format_price(price) -> str:
    if price is None:
        return ""
    try:
        return f"${int(price):,}"
    except (ValueError, TypeError):
        return str(price)


def _zillow_autocomplete(address: str) -> dict | None:
    """Use Zillow's autocomplete API to get zpid and address details."""
    try:
        query = urllib.parse.quote(address)
        url = (
            f"https://www.zillowstatic.com/autocomplete/v3/suggestions"
            f"?q={query}&resultTypes=allAddress&resultCount=1"
        )
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        results = data.get("results", [])
        if results:
            return results[0].get("metaData", {})
    except Exception:
        pass
    return None


def _build_zillow_url(meta: dict) -> str:
    """Build Zillow homedetails URL from autocomplete metadata."""
    zpid = meta.get("zpid")
    street = meta.get("streetNumber", "") + " " + meta.get("streetName", "")
    city = meta.get("city", "")
    state = meta.get("state", "")
    zipcode = meta.get("zipCode", "")
    slug = f"{street} {city} {state} {zipcode}".strip()
    slug = re.sub(r"[,.]", "", slug).replace(" ", "-")
    return f"https://www.zillow.com/homedetails/{slug}/{zpid}_zpid/"


def _scrape_zillow(address: str) -> dict | None:
    """Look up property via Zillow autocomplete API + browser scraping."""
    # Step 1: Get zpid from autocomplete
    meta = _zillow_autocomplete(address)
    if not meta or not meta.get("zpid"):
        return None

    # Step 2: Navigate to homedetails page with real Chrome
    url = _build_zillow_url(meta)
    from tools.browser import _ensure_browser

    page = None
    try:
        page = _ensure_browser()
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(3000)

        title = page.title()
        if "denied" in title.lower() or "captcha" in title.lower():
            return None

        text = page.evaluate("() => document.body.innerText || ''")
        if "confirm you are" in text.lower():
            return None

        data = _extract_from_text(text)
        if not (data.get("price") or data.get("beds")):
            return None

        # Get address from page
        addr = page.evaluate("""() => {
            const el = document.querySelector('h1, [data-testid="bdp-header-address"]');
            return el ? el.innerText.trim() : '';
        }""")
        if addr:
            data["address"] = addr

        # Get description
        desc = page.evaluate("""() => {
            const el = document.querySelector('[data-testid="description"], .comments, .Text-c11n-8-100-2__sc-aiai24-0');
            return el ? el.innerText.substring(0, 300).trim() : '';
        }""")
        if desc:
            data["description"] = desc

        # Get features
        features = page.evaluate("""() => {
            const items = [];
            document.querySelectorAll('.fact-value, [data-testid="fact-item"], .ds-overview-data li').forEach(el => {
                const t = el.innerText.trim();
                if (t && t.length < 60 && t.length > 2) items.push(t);
            });
            return items.slice(0, 15);
        }""")
        if features:
            data["features"] = features

        data["source"] = "zillow"
        data["url"] = page.url
        return data

    except Exception:
        return None
    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass


def _extract_from_text(text: str) -> dict:
    """Extract property data from page text using regex."""
    data = {}
    # Price — look for Zestimate or listing price
    for pattern in [
        r"(?:Zestimate|Price|Listed)[^\$]*\$\s*([\d,]+)",
        r"\$\s*([\d,]+)",
    ]:
        m = re.search(pattern, text)
        if m:
            val = int(m.group(1).replace(",", ""))
            if val > 50000:  # filter noise
                data["price"] = val
                break

    bed_m = re.search(r"(\d+)\s*\n?\s*(?:bd|bed|bedroom)", text, re.IGNORECASE)
    if bed_m:
        data["beds"] = int(bed_m.group(1))

    bath_m = re.search(r"(\d+\.?\d*)\s*\n?\s*(?:ba|bath|bathroom)", text, re.IGNORECASE)
    if bath_m:
        data["baths"] = float(bath_m.group(1))

    sqft_m = re.search(r"([\d,]+)\s*\n?\s*(?:sq\s*ft|sqft|square feet)", text, re.IGNORECASE)
    if sqft_m:
        data["sqft"] = int(sqft_m.group(1).replace(",", ""))

    status_m = re.search(r"\b(Active|Pending|Sold|For Sale|Under Contract|Off Market)\b", text, re.IGNORECASE)
    if status_m:
        data["status"] = status_m.group(1)

    dom_m = re.search(r"(\d+)\s*(?:day|days)\s*(?:on|ago)", text, re.IGNORECASE)
    if dom_m:
        data["days_on_market"] = int(dom_m.group(1))

    year_m = re.search(r"(?:Built in|year\s*built)[:\s]*(\d{4})", text, re.IGNORECASE)
    if year_m:
        data["year_built"] = int(year_m.group(1))

    type_m = re.search(r"\b(SingleFamily|Single Family|Condo|Townhouse)\b", text, re.IGNORECASE)
    if type_m:
        data["property_type"] = type_m.group(1)

    lot_m = re.search(r"([\d.]+)\s*Acres?\s*Lot", text, re.IGNORECASE)
    if lot_m:
        data["lot_acres"] = float(lot_m.group(1))

    return data


def execute(args: dict) -> str:
    address = args.get("address", "").strip()
    if not address:
        return json.dumps({"error": "Please provide a property address."})

    # Try Zillow (autocomplete API + homedetails page)
    data = _scrape_zillow(address)
    if data:
        data.setdefault("address", address)
        data["price_formatted"] = _format_price(data.get("price"))
        data["error"] = None
        return json.dumps(data, ensure_ascii=False)

    # Fallback: browse the address as a URL
    try:
        from tools.browser import execute as browser_exec
        raw = browser_exec({"url": f"https://www.zillow.com/homes/{urllib.parse.quote(address)}_rb/"})
        return json.dumps({
            "address": address,
            "description": raw[:500] if raw else "No data found.",
            "error": "Could not extract structured property data.",
        })
    except Exception as e:
        return json.dumps({"address": address, "error": f"Property lookup failed: {e}"})
