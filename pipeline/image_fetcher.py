"""Fetch relevant images from Wikipedia for a given topic title."""

import json
import re
import urllib.parse
import urllib.request

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
_NUMERIC_PREFIX = re.compile(r"^\d+\.\d+\s+")
_ROOT_LEN = 5
_STOPWORDS = frozenset({
    "a", "an", "the", "of", "in", "and", "or", "to", "for", "with", "by",
    "on", "at", "is", "are", "be", "as", "its", "it", "that", "which",
    "from", "this", "these", "those", "how", "their", "using", "used",
    "use", "into", "about", "after", "all", "also", "been", "between",
    "both", "during", "each", "has", "have", "may", "more", "most",
    "other", "some", "such", "than", "then", "they", "was", "were",
    "when", "can", "will", "one", "two", "three", "new", "via", "per",
})


def _clean_topic_title(title):
    return _NUMERIC_PREFIX.sub("", title).strip()


def _extract_key_terms(text):
    """Return lowercase tokens of 3+ chars that are not stopwords."""
    tokens = re.findall(r"[a-zA-Z]{3,}", text.lower())
    return {t for t in tokens if t not in _STOPWORDS}


def _shares_root(a, b):
    """True if a and b share the same 5-char prefix (handles word variants like optical/optics)."""
    return (
        len(a) >= _ROOT_LEN
        and len(b) >= _ROOT_LEN
        and (a.startswith(b[:_ROOT_LEN]) or b.startswith(a[:_ROOT_LEN]))
    )


def _is_relevant(page_title, key_terms):
    """True if the page title shares at least one root-matched term with key_terms."""
    if page_title.lower().endswith("(disambiguation)"):
        return False
    title_terms = _extract_key_terms(page_title)
    for pt in title_terms:
        for kt in key_terms:
            if pt == kt or _shares_root(pt, kt):
                return True
    return False


def _build_query(topic_title, topic_description=""):
    """Combine cleaned title + first clause of description for a more specific query."""
    clean_title = _clean_topic_title(topic_title)
    if not topic_description:
        return clean_title
    first_clause = re.split(r"[.,;]", topic_description)[0][:80].strip()
    return f"{clean_title} {first_clause}" if first_clause else clean_title


def _api_get(params):
    url = WIKIPEDIA_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "LearnAnything/1.0 (educational)"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _search_pages(query, limit=7):
    data = _api_get({
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": limit,
        "format": "json",
    })
    results = data.get("query", {}).get("search", [])
    return [r["title"] for r in results]


def _get_thumbnails(titles):
    if not titles:
        return {}
    data = _api_get({
        "action": "query",
        "titles": "|".join(titles),
        "prop": "pageimages",
        "pithumbsize": 600,
        "pilimit": len(titles),
        "format": "json",
    })
    pages = data.get("query", {}).get("pages", {})
    thumbnails = {}
    for page in pages.values():
        thumbnail = page.get("thumbnail")
        if thumbnail:
            thumbnails[page["title"]] = {
                "image_title": page["title"],
                "image_url": thumbnail["source"],
            }
    return thumbnails


def fetch_topic_images(topic_title, topic_description="", max_images=3):
    """Return up to max_images image dicts for a topic.

    Each dict has keys: image_title, image_url.
    Returns [] on any failure so callers never have to handle exceptions.
    """
    try:
        query = _build_query(topic_title, topic_description)
        if not query:
            return []
        key_terms = _extract_key_terms(f"{topic_title} {topic_description}")
        candidate_titles = _search_pages(query, limit=max_images + 4)
        if not candidate_titles:
            return []
        relevant = [t for t in candidate_titles if _is_relevant(t, key_terms)]
        if not relevant:
            relevant = candidate_titles
        thumbnails = _get_thumbnails(relevant[: max_images + 2])
        images = []
        for title in relevant:
            if title in thumbnails:
                images.append(thumbnails[title])
                if len(images) >= max_images:
                    break
        return images
    except Exception:
        return []
