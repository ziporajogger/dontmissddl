"""WeChat RSS source — fetch articles from RSS bridge services.

WeChat public accounts don't have open APIs. RSS bridge services
(Feeddd, WeRSS, etc.) convert them to RSS feeds. This module:
1. Parses the RSS XML for article titles + links
2. Optionally fetches the article body via HTTP for deeper extraction
"""

import os
import xml.etree.ElementTree as ET
import requests


def _parse_rss_feed(url: str) -> list[dict]:
    """Parse an RSS feed URL, return list of {title, link, summary}."""
    items = []
    try:
        resp = requests.get(url, timeout=30, headers={
            "User-Agent": "dontmissddl/1.0 (RSS Reader)"
        })
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        # Support both RSS 2.0 and Atom formats
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        for item in root.findall(".//item"):
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            desc = item.findtext("description", "")
            if title:
                items.append({"title": title, "link": link, "summary": desc})

        # Atom fallback
        if not items:
            for entry in root.findall(".//atom:entry", ns):
                title = entry.findtext("atom:title", "", ns)
                link_el = entry.find("atom:link", ns)
                link = link_el.get("href", "") if link_el is not None else ""
                summary = entry.findtext("atom:summary", "", ns)
                if title:
                    items.append({"title": title, "link": link, "summary": summary})

    except Exception as e:
        print(f"[RSS] Error parsing {url}: {e}")

    return items


def _fetch_article_body(url: str) -> str:
    """Try to fetch the article HTML and extract text."""
    if not url:
        return ""
    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (compatible; dontmissddl/1.0)"
        })
        resp.raise_for_status()
        html = resp.text

        # Crude text extraction: remove scripts/styles, get text
        import re
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
        html = re.sub(r'<[^>]+>', ' ', html)
        html = re.sub(r'\s+', ' ', html).strip()

        return html[:3000]  # Truncate
    except Exception:
        return ""


def fetch_wechat_articles() -> list[dict]:
    """Fetch recent articles from configured WeChat RSS feeds."""

    urls_str = os.environ.get("WECHAT_RSS_URLS", "")
    if not urls_str:
        print("[RSS] No WECHAT_RSS_URLS configured, skipping.")
        return []

    urls = [u.strip() for u in urls_str.split(",") if u.strip()]
    results = []

    for url in urls:
        print(f"[RSS] Fetching {url[:60]}...")
        items = _parse_rss_feed(url)
        print(f"  → {len(items)} articles")

        for item in items[:10]:  # Max 10 per feed per run
            title = item.get("title", "")
            summary = item.get("summary", "")
            link = item.get("link", "")

            # Try to get full article body for better DDL detection
            body = _fetch_article_body(link)

            text = f"文章标题：{title}\n\n摘要：{summary}"
            if body:
                text += f"\n\n正文：{body}"

            results.append({
                "text": text,
                "source": "wechat_rss",
                "source_group": title.split("：")[0] if "：" in title else "公众号",
                "source_url": link,
                "raw_text": f"Title: {title}",
            })

    print(f"[RSS] Total: {len(results)} article(s) from {len(urls)} feed(s).")
    return results
