"""Gather source material: OpenAI web search + RSS feeds."""

from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
import requests

import config
from .common import log


def web_search(client):
    """Return (notes, sources) from OpenAI web search. sources = [{"title", "url"}]."""
    prompt = config.RESEARCH_PROMPT.format(
        keywords="、".join(config.KEYWORDS), lookback_hours=config.NEWS_LOOKBACK_HOURS)
    log(f"web search with {config.TEXT_MODEL}: {config.KEYWORDS}")
    response = client.responses.create(
        model=config.TEXT_MODEL,
        tools=[{"type": "web_search"}],
        input=prompt,
    )
    sources, seen = [], set()
    for item in response.output:
        if item.type != "message":
            continue
        for content in item.content:
            for ann in getattr(content, "annotations", None) or []:
                if ann.type == "url_citation" and ann.url not in seen:
                    seen.add(ann.url)
                    sources.append({"title": ann.title, "url": ann.url})
    log(f"web search done: {len(sources)} cited sources")
    return response.output_text.strip(), sources


def _entry_time(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime(*parsed[:6], tzinfo=timezone.utc) if parsed else None


def fetch_rss():
    """Return recent RSS items matching KEYWORDS: [{"title", "url", "published", "summary"}]."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.NEWS_LOOKBACK_HOURS)
    keywords = [k.lower() for k in config.KEYWORDS]
    urls = []
    for feed in config.RSS_FEEDS:
        if "{keyword}" in feed:
            urls += [(feed.format(keyword=quote_plus(k)), False) for k in config.KEYWORDS]
        else:
            urls.append((feed, True))

    items, seen = [], set()
    for url, needs_filter in urls:
        try:
            resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0 autopost"})
            resp.raise_for_status()
        except requests.RequestException as e:
            log(f"[warn] RSS fetch failed ({url}): {e}")
            continue
        for entry in feedparser.parse(resp.content).entries:
            link, title = entry.get("link", ""), entry.get("title", "")
            summary = entry.get("summary", "")
            published = _entry_time(entry)
            if not link or link in seen or (published and published < cutoff):
                continue
            if needs_filter and not any(k in f"{title} {summary}".lower() for k in keywords):
                continue
            seen.add(link)
            items.append({"title": title, "url": link, "summary": summary[:300],
                          "published": published.isoformat() if published else ""})

    items.sort(key=lambda i: i["published"], reverse=True)
    items = items[:config.RSS_MAX_ITEMS]
    log(f"RSS done: {len(items)} recent items")
    return items


def format_rss(items):
    if not items:
        return "（沒有找到相關 RSS 文章）"
    return "\n".join(f"- [{i['published'][:10]}] {i['title']}\n  {i['url']}" for i in items)
