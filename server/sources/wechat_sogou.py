"""WeChat Sogou source — search public account articles via Sogou with Playwright.

Sogou (搜狗) renders search results dynamically with JavaScript.
Playwright is used to load the page, dismiss any CAPTCHA prompts,
and extract article links + content.
"""

import os
import re
import random
import time
from html import unescape
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


def _setup_page(page):
    """Configure page to look like a real browser."""
    page.set_viewport_size({"width": 1440, "height": 900})
    # Neutralize automation flags
    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN','zh','en'] });
    """)


def _wait_a_bit(min_s: float = 0.3, max_s: float = 1.5):
    """Human-like pause."""
    time.sleep(random.uniform(min_s, max_s))


def _clean_html(html: str) -> str:
    """Strip tags, decode entities."""
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
    html = re.sub(r"<br\s*/?>", "\n", html)
    html = re.sub(r"</p>", "\n", html)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"\s+", " ", html)
    return unescape(html).strip()


def _search_account(page, account_name: str, max_articles: int = 5) -> list[dict]:
    """Search for an account on Sogou and return article list."""
    articles = []

    try:
        # Navigate directly to search results URL (skip typing into search box)
        from urllib.parse import quote
        query_encoded = quote(account_name, safe="")
        search_url = (
            f"https://weixin.sogou.com/weixin"
            f"?type=2&query={query_encoded}&ie=utf8"
        )
        page.goto(search_url, timeout=20000, wait_until="domcontentloaded")
        _wait_a_bit(2.0, 4.0)

        # Check for captcha
        _handle_captcha(page)

        # Extract article links from Sogou's obfuscated structure
        # Sogou uses <a data-z="art" href="/link?url=..."> inside .img-box divs
        link_els = page.locator("a[data-z='art']")
        count = min(link_els.count(), max_articles * 2)
        print(f"  Found {link_els.count()} article links (data-z=art)")

        seen = set()
        for i in range(count):
            try:
                el = link_els.nth(i)
                if not el.is_visible():
                    continue

                # Get the Sogou intermediate link
                sogou_path = (el.get_attribute("href") or "").strip()
                if not sogou_path or sogou_path in seen:
                    continue
                seen.add(sogou_path)

                # Title from the link element's text or alt
                title = (el.get_attribute("title") or el.inner_text() or "").strip()[:200]

                # Title is in the parent <li>, not the <a> tag itself
                # Use JavaScript to find ancestor li
                parent_text = ""
                try:
                    parent_text = el.evaluate(
                        "el => { const li = el.closest('li'); return li ? li.innerText : ''; }"
                    ) or ""
                except Exception:
                    pass

                if parent_text:
                    lines = [l.strip() for l in parent_text.split("\n") if l.strip()]
                    if lines:
                        title = lines[0][:200]

                # Extract summary (text between title and date)
                summary = ""
                # Extract date from parent text
                date = ""
                dm = re.search(r"(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})", parent_text)
                if dm:
                    date = dm.group()

                if not title:
                    continue

                articles.append({
                    "title": title,
                    "link": sogou_path,  # Store Sogou path, resolve later
                    "summary": summary,
                    "date": date,
                })

                if len(articles) >= max_articles:
                    break

            except Exception:
                continue

    except PlaywrightTimeout as e:
        print(f"  Timeout: {e}")
    except Exception as e:
        print(f"  Search error: {type(e).__name__}: {e}")

    print(f"  -> extracted {len(articles)} articles")
    return articles


def _handle_captcha(page) -> bool:
    """Try to dismiss any CAPTCHA. Returns True if CAPTCHA was present."""
    captcha_texts = ["验证码", "请输入验证码", "CAPTCHA", "verify"]
    for ct in captcha_texts:
        if ct in (page.content() or "")[:3000]:
            print("  [WARN] CAPTCHA detected - page may be blocked")
            return True
    return False


def _fetch_article_text(page, url_or_path: str) -> tuple[str, str]:
    """Navigate to an article and extract its body text.
    Handles both direct mp.weixin.qq.com URLs and Sogou /link?url= redirects.
    Returns (final_url, body_text).
    """
    if not url_or_path:
        return ("", "")

    try:
        # If it's a Sogou redirect path, prepend domain
        if url_or_path.startswith("/link?"):
            url = f"https://weixin.sogou.com{url_or_path}"
        else:
            url = url_or_path

        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        _wait_a_bit(1.0, 2.0)

        final_url = page.url

        # WeChat article content is in #js_content
        content_el = page.locator("#js_content")
        if content_el.count() > 0 and content_el.first.is_visible():
            return (final_url, _clean_html(content_el.first.inner_html() or "")[:4000])

        # Fallback: get page text
        body = page.locator("body").first
        if body.is_visible():
            return (final_url, _clean_html(body.inner_text() or "")[:3000])

        return (final_url, "")
    except Exception as e:
        return ("", f"[fetch error: {e}]")


def fetch_sogou_articles() -> list[dict]:
    """Fetch articles from configured WeChat public account names via Sogou + Playwright."""

    names_str = os.environ.get("WECHAT_SOGOU_NAMES", "")
    if not names_str:
        print("[Sogou] No WECHAT_SOGOU_NAMES configured, skipping.")
        return []

    names = [n.strip() for n in names_str.split(",") if n.strip()]
    results = []

    print(f"[Sogou] Launching browser...")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
        )
        page = context.new_page()
        _setup_page(page)

        try:
            for name in names:
                print(f"[Sogou] Searching: {name}")
                articles = _search_account(page, name, max_articles=5)
                print(f"  -> {len(articles)} articles")

                for art in articles:
                    title = art.get("title", "")
                    summary = art.get("summary", "")
                    sogou_link = art.get("link", "")
                    date = art.get("date", "")

                    final_url, body = _fetch_article_text(page, sogou_link)

                    text = f"文章标题：{title}\n\n摘要：{summary}"
                    if date:
                        text = f"发布日期：{date}\n{text}"
                    if body and not body.startswith("[fetch error"):
                        text += f"\n\n正文：{body}"

                    results.append({
                        "text": text,
                        "source": "sogou_wechat",
                        "source_group": name,
                        "source_url": final_url or sogou_link,
                        "raw_text": f"Title: {title}",
                    })

                    _wait_a_bit(0.5, 1.5)

        finally:
            browser.close()

    print(f"[Sogou] Total: {len(results)} article(s) from {len(names)} account(s).")
    return results
