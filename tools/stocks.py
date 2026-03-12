"""Stocks — real-time quotes, watchlists, and market overview via yfinance."""

import json

DEFINITION = {
    "type": "function",
    "function": {
        "name": "stocks",
        "description": (
            "Get stock or crypto prices, market data, and watchlists. "
            "ONLY use when the user explicitly asks about stocks, share prices, "
            "tickers, crypto, or market data. Do NOT call for general conversation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["quote", "watchlist", "market"],
                    "description": (
                        "quote: detailed quote for a single symbol. "
                        "watchlist: brief quotes for multiple symbols. "
                        "market: overview of major indices."
                    ),
                },
                "symbol": {
                    "type": "string",
                    "description": "Ticker symbol (e.g. 'AAPL', 'TSLA', 'BTC-USD'). Required for quote.",
                },
                "symbols": {
                    "type": "string",
                    "description": "Comma-separated ticker symbols for watchlist (e.g. 'AAPL,TSLA,GOOG').",
                },
            },
            "required": ["action"],
        },
    },
}

INDICES = ["^GSPC", "^DJI", "^IXIC", "^RUT"]
INDEX_NAMES = {"^GSPC": "S&P 500", "^DJI": "Dow Jones", "^IXIC": "NASDAQ", "^RUT": "Russell 2000"}


def _fmt_num(n, prefix="", suffix="", decimals=2):
    if n is None:
        return "N/A"
    if abs(n) >= 1_000_000_000_000:
        return f"{prefix}{n / 1_000_000_000_000:.1f}T{suffix}"
    if abs(n) >= 1_000_000_000:
        return f"{prefix}{n / 1_000_000_000:.1f}B{suffix}"
    if abs(n) >= 1_000_000:
        return f"{prefix}{n / 1_000_000:.1f}M{suffix}"
    if abs(n) >= 1_000:
        return f"{prefix}{n / 1_000:.1f}K{suffix}"
    return f"{prefix}{n:.{decimals}f}{suffix}"


def _quote(symbol: str) -> dict:
    import yfinance as yf

    t = yf.Ticker(symbol.upper().strip())
    info = t.info
    if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
        return {"error": f"No data found for '{symbol}'."}

    price = info.get("currentPrice") or info.get("regularMarketPrice")
    prev = info.get("previousClose") or info.get("regularMarketPreviousClose")
    change = (price - prev) if price and prev else None
    change_pct = (change / prev * 100) if change and prev else None

    # 5-day sparkline
    spark = []
    try:
        hist = t.history(period="5d")
        spark = [round(row["Close"], 2) for _, row in hist.iterrows()]
    except Exception:
        pass

    return {
        "symbol": info.get("symbol", symbol.upper()),
        "name": info.get("shortName") or info.get("longName") or symbol.upper(),
        "price": round(price, 2) if price else None,
        "change": round(change, 2) if change else None,
        "change_pct": round(change_pct, 2) if change_pct else None,
        "prev_close": round(prev, 2) if prev else None,
        "open": round(info.get("open"), 2) if info.get("open") else None,
        "day_high": round(info.get("dayHigh"), 2) if info.get("dayHigh") else None,
        "day_low": round(info.get("dayLow"), 2) if info.get("dayLow") else None,
        "week52_high": round(info.get("fiftyTwoWeekHigh"), 2) if info.get("fiftyTwoWeekHigh") else None,
        "week52_low": round(info.get("fiftyTwoWeekLow"), 2) if info.get("fiftyTwoWeekLow") else None,
        "market_cap": _fmt_num(info.get("marketCap"), prefix="$"),
        "pe_ratio": round(info.get("trailingPE"), 2) if info.get("trailingPE") else None,
        "volume": _fmt_num(info.get("volume")),
        "sector": info.get("sector"),
        "exchange": info.get("exchange"),
        "spark": spark,
    }


def _watchlist(symbols: list[str]) -> list[dict]:
    import yfinance as yf

    results = []
    for sym in symbols[:8]:  # cap at 8
        try:
            t = yf.Ticker(sym.upper().strip())
            info = t.info
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            prev = info.get("previousClose") or info.get("regularMarketPreviousClose")
            change = (price - prev) if price and prev else None
            change_pct = (change / prev * 100) if change and prev else None
            results.append({
                "symbol": info.get("symbol", sym.upper()),
                "name": info.get("shortName") or sym.upper(),
                "price": round(price, 2) if price else None,
                "change": round(change, 2) if change else None,
                "change_pct": round(change_pct, 2) if change_pct else None,
            })
        except Exception:
            results.append({"symbol": sym.upper(), "name": sym.upper(), "error": True})
    return results


def _market() -> list[dict]:
    import yfinance as yf

    results = []
    for idx in INDICES:
        try:
            t = yf.Ticker(idx)
            info = t.info
            price = info.get("regularMarketPrice") or info.get("currentPrice")
            prev = info.get("previousClose") or info.get("regularMarketPreviousClose")
            change = (price - prev) if price and prev else None
            change_pct = (change / prev * 100) if change and prev else None
            results.append({
                "symbol": idx,
                "name": INDEX_NAMES.get(idx, idx),
                "price": round(price, 2) if price else None,
                "change": round(change, 2) if change else None,
                "change_pct": round(change_pct, 2) if change_pct else None,
            })
        except Exception:
            results.append({"symbol": idx, "name": INDEX_NAMES.get(idx, idx), "error": True})
    return results


def execute(args: dict) -> str:
    action = args.get("action", "quote")

    if action == "quote":
        symbol = args.get("symbol", "")
        if not symbol:
            return json.dumps({"error": "Please specify a ticker symbol."})
        return json.dumps({"action": "quote", "data": _quote(symbol)})

    elif action == "watchlist":
        raw = args.get("symbols", "")
        if not raw:
            return json.dumps({"error": "Please specify ticker symbols."})
        symbols = [s.strip() for s in raw.replace(" ", ",").split(",") if s.strip()]
        return json.dumps({"action": "watchlist", "data": _watchlist(symbols)})

    elif action == "market":
        return json.dumps({"action": "market", "data": _market()})

    return json.dumps({"error": f"Unknown action: {action}"})
