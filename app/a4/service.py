import html
import json
import re
import time
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener


BASE_URL = "https://www.a4.com/"
_CACHE_TTL = 900
_cache = {
    "categories": {"data": None, "ts": 0.0},
    "styles": {},
    "details": {},
}
_opener = build_opener(HTTPCookieProcessor())

FALLBACK_CATEGORIES = (
    ("Baseball", "sports/baseball"),
    ("Basketball", "sports/basketball"),
    ("Football", "sports/football"),
    ("Lacrosse", "sports/lacrosse"),
    ("Soccer", "sports/soccer"),
    ("Softball", "sports/softball"),
    ("Teamwear", "sports/teamwear"),
    ("Track/Running", "sports/track-running"),
    ("Volleyball", "sports/volleyball"),
    ("Short Sleeve Tees", "men/type/short-sleeve-tees"),
    ("Polos", "men/type/polos"),
    ("Fleece", "men/type/fleece"),
    ("Hoodies", "men/type/hoodies"),
    ("Sale", "sale"),
)


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.images = []
        self._link = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self._link = {
                "href": attrs.get("href", "").strip(),
                "title": attrs.get("title", "").strip(),
                "text": "",
            }
        elif tag == "img":
            self.images.append(
                {
                    "src": attrs.get("src") or attrs.get("data-src") or "",
                    "alt": attrs.get("alt", "").strip(),
                }
            )

    def handle_data(self, data):
        if self._link is not None:
            self._link["text"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self._link is not None:
            self._link["text"] = _clean_text(self._link["text"])
            self.links.append(self._link)
            self._link = None


def get_categories(force_refresh=False):
    cached = _cache["categories"]
    if not force_refresh and cached["data"] and time.time() - cached["ts"] < _CACHE_TTL:
        return cached["data"]

    try:
        page = _fetch(BASE_URL)
        categories = _parse_categories(page)
    except RuntimeError:
        categories = []

    if len(categories) < 8:
        categories = _fallback_categories()

    data = {"source": BASE_URL, "categories": categories, "count": len(categories)}
    _cache["categories"] = {"data": data, "ts": time.time()}
    return data


def get_styles(category_url, category_name="", force_refresh=False):
    url = _normalise_a4_url(category_url)
    cache_key = url.lower()
    cached = _cache["styles"].get(cache_key)
    if not force_refresh and cached and time.time() - cached["ts"] < _CACHE_TTL:
        return cached["data"]

    page = _fetch(url)
    styles = _parse_product_cards(page, url)
    data = {
        "category": category_name or _category_name_from_url(url),
        "source": url,
        "styles": styles[:80],
        "count": len(styles[:80]),
        "limited": len(styles) > 80,
    }
    _cache["styles"][cache_key] = {"data": data, "ts": time.time()}
    return data


def get_style_detail(style_url, style_code="", force_refresh=False):
    url = _normalise_a4_url(style_url)
    cache_key = url.lower()
    cached = _cache["details"].get(cache_key)
    if not force_refresh and cached and time.time() - cached["ts"] < _CACHE_TTL:
        return cached["data"]

    page = _fetch(url)
    detail = _parse_detail(page, url, style_code=style_code)
    _cache["details"][cache_key] = {"data": detail, "ts": time.time()}
    return detail


def _fetch(url):
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": BASE_URL,
            "Upgrade-Insecure-Requests": "1",
        },
    )
    try:
        with _opener.open(request, timeout=25) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"A4 returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach A4: {exc.reason}") from exc


def _parse_categories(page):
    parser = LinkParser()
    parser.feed(page)
    wanted_prefixes = (
        "/sports/",
        "/men/",
        "/women/",
        "/youth/",
        "/sale",
    )
    blocked = {"all", "color", "favorites", "log in", "sign in", "advanced search"}
    categories = []
    seen = set()
    for link in parser.links:
        name = _clean_text(link.get("text") or link.get("title"))
        href = link.get("href", "")
        parsed = urlparse(urljoin(BASE_URL, href))
        if parsed.netloc and parsed.netloc not in ("www.a4.com", "a4.com"):
            continue
        path = parsed.path.rstrip("/")
        if not any(path.startswith(prefix.rstrip("/")) for prefix in wanted_prefixes):
            continue
        if not name or name.casefold() in blocked or len(name) > 36:
            continue
        key = path.lower()
        if key in seen:
            continue
        seen.add(key)
        categories.append({"name": name, "url": urljoin(BASE_URL, path.lstrip("/")), "slug": path.strip("/")})
    return categories[:120]


def _fallback_categories():
    return [
        {"name": name, "url": urljoin(BASE_URL, slug.rstrip("/") + "/"), "slug": slug.strip("/")}
        for name, slug in FALLBACK_CATEGORIES
    ]


def _parse_product_cards(page, page_url):
    blocks = re.findall(
        r'<li[^>]+class=["\'][^"\']*\bproduct-item\b[^"\']*["\'][^>]*>(.*?)</li>',
        page,
        flags=re.I | re.S,
    )
    if not blocks:
        blocks = re.findall(
            r'<div[^>]+class=["\'][^"\']*\bproduct-item-info\b[^"\']*["\'][^>]*>(.*?)</div>\s*</div>',
            page,
            flags=re.I | re.S,
        )

    styles = []
    for block in blocks:
        href = _first_match(block, r'<a[^>]+href=["\']([^"\']+)["\'][^>]*class=["\'][^"\']*product-item-link')
        if not href:
            href = _first_match(block, r'<a[^>]+class=["\'][^"\']*product-item-link[^"\']*["\'][^>]+href=["\']([^"\']+)')
        name = _clean_html(_first_match(block, r'class=["\'][^"\']*product-item-link[^"\']*["\'][^>]*>(.*?)</a>'))
        code = _extract_style_code(_clean_html(block))
        image = _first_match(block, r'<img[^>]+(?:data-src|src)=["\']([^"\']+)')
        price = _clean_html(_first_match(block, r'(?:As low as|Special Price|Regular Price).*?</span>|<span[^>]+class=["\'][^"\']*price[^"\']*["\'][^>]*>(.*?)</span>'))
        if not href or not name:
            continue
        styles.append(
            {
                "name": name,
                "code": code,
                "url": urljoin(page_url, href),
                "image": _normalise_image(image, page_url),
                "description": price,
            }
        )

    if not styles:
        styles = _parse_product_cards_from_text(page, page_url)
    return _dedupe_styles(styles)


def _parse_product_cards_from_text(page, page_url):
    text = _clean_html(page)
    parser = LinkParser()
    parser.feed(page)
    product_links = [
        link for link in parser.links
        if _looks_like_product_url(link.get("href", "")) and _clean_text(link.get("text") or link.get("title"))
    ]
    styles = []
    for link in product_links:
        name = _clean_text(link.get("text") or link.get("title"))
        href = urljoin(page_url, link["href"])
        idx = text.find(name)
        nearby = text[max(0, idx - 80): idx + len(name) + 80] if idx >= 0 else name
        styles.append(
            {
                "name": name,
                "code": _extract_style_code(nearby),
                "url": href,
                "image": _image_for_name(page, name, page_url),
                "description": _first_match(nearby, r"As low as \$[0-9.,]+") or "",
            }
        )
    return styles


def _parse_detail(page, page_url, style_code=""):
    name = _meta(page, "og:title") or _clean_html(_first_match(page, r'<h1[^>]*>(.*?)</h1>'))
    description = _meta(page, "description") or _meta(page, "og:description")
    image = _meta(page, "og:image") or _first_match(page, r'<img[^>]+(?:data-src|src)=["\']([^"\']+)')
    code = style_code or _extract_style_code(name + " " + _clean_html(page))
    specs = _parse_specs(page)
    colors = _parse_colors(page)
    return {
        "code": code,
        "source": page_url,
        "product": {
            "code": code,
            "name": _clean_text(name).replace(f"{code} | ", "") if code else _clean_text(name),
            "description": _clean_text(description),
            "image": _normalise_image(image, page_url),
            "price": _clean_html(_first_match(page, r'<span[^>]+class=["\'][^"\']*price[^"\']*["\'][^>]*>(.*?)</span>')),
        },
        "specs": specs,
        "colors": colors,
        "color_count": len(colors),
    }


def _parse_specs(page):
    specs = []
    for label in ("Fabric", "Features", "Sizes", "Description", "Decoration", "Fit"):
        match = re.search(label + r"</?[^>]*>\s*<[^>]+>(.*?)</", page, flags=re.I | re.S)
        if match:
            specs.append({"label": label, "value": _clean_html(match.group(1))})
    if not specs:
        for match in re.finditer(r'<tr[^>]*>\s*<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>', page, flags=re.I | re.S):
            specs.append({"label": _clean_html(match.group(1)), "value": _clean_html(match.group(2))})
    return [s for s in specs if s["label"] and s["value"]][:12]


def _parse_colors(page):
    colors = []
    seen = set()
    for match in re.finditer(r'(?:option-label|aria-label|title)=["\']([^"\']+)["\'][^>]*(?:data-option-id|data-option-label|option-id)?', page, flags=re.I):
        name = _clean_text(match.group(1))
        if not name or name.lower() in seen or len(name) > 40:
            continue
        seen.add(name.lower())
        colors.append({"name": name, "swatch": "", "image": "", "inventory": []})
    for match in re.finditer(r'background:\s*(#[0-9a-fA-F]{3,6})', page):
        if len(colors) > len([c for c in colors if c.get("swatch")]):
            for color in colors:
                if not color.get("swatch"):
                    color["swatch"] = match.group(1)
                    break
    return colors[:60]


def _normalise_a4_url(url):
    absolute = urljoin(BASE_URL, url or "")
    parsed = urlparse(absolute)
    if parsed.netloc not in ("www.a4.com", "a4.com"):
        raise ValueError("Only www.a4.com URLs are allowed.")
    return absolute


def _normalise_image(src, page_url):
    if not src:
        return ""
    src = html.unescape(src)
    if src.startswith("//"):
        return "https:" + src
    return urljoin(page_url, src)


def _image_for_name(page, name, page_url):
    idx = page.find(name)
    chunk = page[max(0, idx - 1400): idx + 1400] if idx >= 0 else page[:3000]
    return _normalise_image(_first_match(chunk, r'<img[^>]+(?:data-src|src)=["\']([^"\']+)'), page_url)


def _looks_like_product_url(href):
    path = urlparse(urljoin(BASE_URL, href)).path
    if not path or path.count("/") > 2:
        return False
    blocked = ("/sports/", "/men/", "/women/", "/youth/", "/sale", "/marketing/", "/customer/")
    return not path.startswith(blocked) and path.endswith(".html")


def _extract_style_code(value):
    match = re.search(r"\b[A-Z]{1,4}\d{2,5}[A-Z]?\b", value or "")
    return match.group(0) if match else ""


def _meta(page, name):
    patterns = [
        rf'<meta[^>]+name=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']*)',
        rf'<meta[^>]+property=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']*)',
    ]
    for pattern in patterns:
        value = _first_match(page, pattern)
        if value:
            return html.unescape(value)
    return ""


def _first_match(value, pattern):
    match = re.search(pattern, value or "", flags=re.I | re.S)
    return match.group(1) if match and match.groups() else (match.group(0) if match else "")


def _dedupe_styles(styles):
    clean = []
    seen = set()
    for style in styles:
        key = (style.get("url") or style.get("name", "")).lower()
        if key in seen:
            continue
        seen.add(key)
        clean.append(style)
    return clean


def _category_name_from_url(url):
    slug = urlparse(url).path.strip("/").split("/")[-1]
    return slug.replace("-", " ").title() if slug else "A4"


def _clean_text(value):
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def _clean_html(value):
    text = re.sub(r"<script.*?</script>", " ", str(value or ""), flags=re.I | re.S)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return _clean_text(text)
