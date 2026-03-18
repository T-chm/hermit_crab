"""Property Lookup — scrape public property data via browser extension."""

import json
import re

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


def execute(args: dict) -> str:
    address = args.get("address", "").strip()
    if not address:
        return json.dumps({"error": "Please provide a property address."})

    # Use the browser tool to search and extract property data
    task = (
        f"Go to zillow.com and search for the property at: {address}. "
        "Once you find the listing, extract the following information and return it as JSON: "
        "address, price (number), beds (number), baths (number), sqft (number), "
        "days_on_market (number), status (Active/Pending/Sold), "
        "description (first 200 chars), features (array of strings), "
        "property_type (Single Family/Condo/Townhouse), year_built, lot_sqft. "
        "If Zillow doesn't have results, try redfin.com or realtor.com. "
        "Return ONLY the JSON object, no other text."
    )

    try:
        from tools.browser import execute as browser_exec
        raw = browser_exec({"task": task})
    except Exception as e:
        return json.dumps({"error": f"Browser not available: {e}"})

    # Try to parse structured JSON from the browser result
    try:
        # Look for JSON in the response
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            data = json.loads(m.group(0))
            # Normalize the output
            result = {
                "address": data.get("address", address),
                "price": data.get("price"),
                "price_formatted": _format_price(data.get("price")),
                "beds": data.get("beds"),
                "baths": data.get("baths"),
                "sqft": data.get("sqft"),
                "days_on_market": data.get("days_on_market"),
                "status": data.get("status", "Unknown"),
                "description": data.get("description", ""),
                "features": data.get("features", []),
                "property_type": data.get("property_type", ""),
                "year_built": data.get("year_built"),
                "lot_sqft": data.get("lot_sqft"),
                "source": data.get("source", "web"),
                "url": data.get("url", ""),
                "error": None,
            }
            return json.dumps(result, ensure_ascii=False)

        # No JSON found — return the raw text as a fallback
        return json.dumps({
            "address": address,
            "description": raw[:500] if raw else "No data found.",
            "error": "Could not extract structured data. Raw result included.",
        })

    except json.JSONDecodeError:
        return json.dumps({
            "address": address,
            "description": raw[:500] if raw else "No data found.",
            "error": "Failed to parse property data.",
        })


def _format_price(price) -> str:
    if price is None:
        return ""
    try:
        return f"${int(price):,}"
    except (ValueError, TypeError):
        return str(price)
