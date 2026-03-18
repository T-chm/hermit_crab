"""Browser — headless web browsing and content extraction via Playwright."""

import json
import re

DEFINITION = {
    "type": "function",
    "function": {
        "name": "browser",
        "description": (
            "Browse the web using a headless browser. Navigate to URLs and extract "
            "page content. Use for property lookups, web research, or any task "
            "needing live web data."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to navigate to and extract content from.",
                },
            },
            "required": ["url"],
        },
    },
}

# Singleton browser instance (lazy-init, reused across calls)
_playwright = None
_browser = None
_context = None

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _ensure_browser():
    """Lazy-init browser. Returns a Page in a fresh context each time
    to avoid cookie contamination from anti-bot CAPTCHAs."""
    global _playwright, _browser, _context
    if _browser is None:
        from playwright.sync_api import sync_playwright
        _playwright = sync_playwright().start()
        for launch_opts in [
            {"headless": False, "channel": "chrome", "args": ["--disable-blink-features=AutomationControlled", "--window-position=-2400,-2400"]},
            {"headless": True, "args": ["--disable-blink-features=AutomationControlled"]},
        ]:
            try:
                _browser = _playwright.chromium.launch(**launch_opts)
                break
            except Exception:
                continue
        if _browser is None:
            raise RuntimeError("Could not launch browser. Install Chrome or run: playwright install chromium")
    # Fresh context every time — prevents CAPTCHA cookie contamination
    ctx = _browser.new_context(
        user_agent=_USER_AGENT,
        viewport={"width": 1280, "height": 800},
        locale="en-US",
    )
    ctx.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    """)
    return ctx.new_page()


def _simplify_page(page) -> str:
    """Extract page content into LLM-friendly text."""
    title = page.title()
    url = page.url

    # Extract main text content via JS
    content = page.evaluate("""() => {
        // Remove noise elements
        const remove = ['script', 'style', 'nav', 'footer', 'header', 'noscript', 'iframe'];
        remove.forEach(tag => {
            document.querySelectorAll(tag).forEach(el => el.remove());
        });

        // Get text from main content area or body
        const main = document.querySelector('main, article, [role="main"], .content, #content');
        const target = main || document.body;

        // Get visible text, collapse whitespace
        const text = target.innerText || target.textContent || '';
        return text.replace(/\\n{3,}/g, '\\n\\n').trim().substring(0, 8000);
    }""")

    # Extract metadata
    meta = page.evaluate("""() => {
        const result = {};
        const desc = document.querySelector('meta[name="description"]');
        if (desc) result.description = desc.content;
        const og = {};
        document.querySelectorAll('meta[property^="og:"]').forEach(m => {
            og[m.getAttribute('property').replace('og:', '')] = m.content;
        });
        if (Object.keys(og).length) result.og = og;
        return result;
    }""")

    parts = [f"Title: {title}", f"URL: {url}"]
    if meta.get("description"):
        parts.append(f"Description: {meta['description']}")
    parts.append(f"\n{content}")

    return "\n".join(parts)


def execute(args: dict) -> str:
    url = args.get("url", "").strip()
    if not url:
        return "Please specify a URL."

    # Ensure URL has protocol
    if not url.startswith("http"):
        url = "https://" + url

    page = None
    try:
        page = _ensure_browser()
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        # Small wait for dynamic content
        page.wait_for_timeout(2000)
        result = _simplify_page(page)
        return result
    except Exception as e:
        return f"Browser error: {e}"
    finally:
        if page:
            try:
                ctx = page.context
                page.close()
                ctx.close()
            except Exception:
                pass
