import html
import json
import re
import time
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


BASE_URL = "https://shop.ralawise.com/"
_CACHE_TTL = 900
FALLBACK_BRANDS = (
    ("Add It On", "additon"),
    ("Adidas", "adidas-"),
    ("Anthem", "anthem"),
    ("Asquith & Fox", "asquith-fox"),
    ("AWDis", "awdis"),
    ("BagBase", "bagbase"),
    ("Beechfield", "beechfield"),
    ("Bella+Canvas", "bella-canvas"),
    ("Build Your Brand", "build-your-brand"),
    ("Finden & Hales", "finden-hales"),
    ("Fruit of the Loom", "fruit-of-the-loom"),
    ("Gildan", "gildan"),
    ("Henbury", "henbury"),
    ("Just Cool", "just-cool"),
    ("Just Hoods", "just-hoods"),
    ("Just Polos", "just-polos"),
    ("Just T's", "just-ts"),
    ("Kariban", "kariban"),
    ("Kustom Kit", "kustom-kit"),
    ("Mumbles", "mumbles"),
    ("Premier", "premier"),
    ("Pro RTX", "pro-rtx"),
    ("Quadra", "quadra"),
    ("Regatta Professional", "regatta-professional"),
    ("Result", "result"),
    ("Russell", "russell"),
    ("SOL'S", "sols"),
    ("Tombo", "tombo"),
    ("Towel City", "towelcity"),
    ("TriDri®", "tridri-"),
    ("Under Armour", "underarmour"),
    ("Westford Mill", "westfordmill"),
    ("Yoko", "yoko"),
)
_cache = {
    "brands": {"data": None, "ts": 0.0},
    "styles": {},
    "details": {},
}


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.images = []
        self._current_link = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self._current_link = {
                "href": attrs.get("href", "").strip(),
                "text": "",
                "title": attrs.get("title", "").strip(),
            }
        elif tag == "img":
            self.images.append(
                {
                    "src": attrs.get("src") or attrs.get("data-src") or "",
                    "alt": attrs.get("alt", "").strip(),
                }
            )

    def handle_data(self, data):
        if self._current_link is not None:
            self._current_link["text"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self._current_link is not None:
            self._current_link["text"] = _clean_text(self._current_link["text"])
            self.links.append(self._current_link)
            self._current_link = None


def get_brands(force_refresh=False):
    cached = _cache["brands"]
    if not force_refresh and cached["data"] and time.time() - cached["ts"] < _CACHE_TTL:
        return cached["data"]

    try:
        page = _fetch(BASE_URL)
        brands = _parse_brand_menu(page)
    except RuntimeError:
        brands = []

    if len(brands) < 10:
        brands = _merge_fallback_brands(brands)

    brands.sort(key=lambda item: item["name"].casefold())
    data = {"source": BASE_URL, "brands": brands, "count": len(brands)}
    _cache["brands"] = {"data": data, "ts": time.time()}
    return data


def get_styles(brand_url, brand_name="", force_refresh=False):
    absolute_url = _normalise_ralawise_url(brand_url)
    cache_key = absolute_url.lower()
    cached = _cache["styles"].get(cache_key)
    if not force_refresh and cached and time.time() - cached["ts"] < _CACHE_TTL:
        return cached["data"]

    try:
        filter_data = _fetch_json(_brand_filter_url(absolute_url))
        styles = _parse_filter_entries(filter_data)
    except RuntimeError as exc:
        data = {
            "brand": brand_name or _brand_name_from_url(absolute_url),
            "source": absolute_url,
            "styles": [],
            "count": 0,
            "limited": False,
            "warning": str(exc),
        }
        _cache["styles"][cache_key] = {"data": data, "ts": time.time()}
        return data

    if not styles:
        page = _fetch(absolute_url)
        styles = _parse_product_json(page)
    if not styles:
        styles = _parse_product_links(page, absolute_url)

    data = {
        "brand": brand_name or _brand_name_from_url(absolute_url),
        "source": absolute_url,
        "styles": styles[:60],
        "count": len(styles[:60]),
        "limited": len(styles) > 60,
    }
    _cache["styles"][cache_key] = {"data": data, "ts": time.time()}
    return data


def get_style_detail(style_code, style_url="", force_refresh=False):
    code = _clean_text(style_code).upper()
    if not code:
        raise ValueError("Style code is required.")

    cache_key = f"{code}:{style_url}".lower()
    cached = _cache["details"].get(cache_key)
    if not force_refresh and cached and time.time() - cached["ts"] < _CACHE_TTL:
        return cached["data"]

    product = _fetch_product_summary(code)
    page_url = _normalise_ralawise_url(style_url) if style_url else product.get("url", "")
    detail_page = _fetch(page_url) if page_url else ""
    colours = _parse_detail_colours(detail_page)

    for colour in colours:
        colour["variants"] = _fetch_colour_variants(colour["entry_code"])
        colour["total_stock"] = sum(v.get("stock", 0) for v in colour["variants"])

    data = {
        "code": code,
        "source": page_url,
        "product": product,
        "colours": colours,
        "colour_count": len(colours),
        "variant_count": sum(len(c["variants"]) for c in colours),
    }
    _cache["details"][cache_key] = {"data": data, "ts": time.time()}
    return data


def _request(url, accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"):
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
            ),
            "Accept": accept,
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"Ralawise returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Ralawise: {exc.reason}") from exc


def _fetch(url):
    return _request(url)


def _fetch_json(url):
    raw = _request(url, accept="application/json, text/plain, */*")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ralawise did not return valid product data.") from exc


def _fetch_product_summary(code):
    payload = _fetch_json(urljoin(BASE_URL, f"/services/productservice/GetProducts?codes={code}"))
    rows = payload.get("Data") or []
    row = rows[0] if rows else {}
    extended = row.get("ExtendedData") or {}
    images = row.get("ImageUrls") or []
    return {
        "code": code,
        "name": _clean_text(row.get("DisplayName") or row.get("Name") or code),
        "brand": _clean_text(row.get("BrandName", "")),
        "brand_logo": urljoin(BASE_URL, row.get("BrandLogoUrl", "")) if row.get("BrandLogoUrl") else "",
        "url": urljoin(BASE_URL, row.get("DetailUrl", "")) if row.get("DetailUrl") else "",
        "image": urljoin(BASE_URL, images[0]) if images else "",
        "price": _clean_text(row.get("FromPrice", "")),
        "size_range": _clean_text(row.get("SizeRange", "")),
        "description": _clean_html(row.get("Description", "")),
        "fabric": _clean_html(extended.get("Fabric", "")),
        "weight": _clean_html(extended.get("Weight", "")),
        "size": _clean_html(extended.get("Size", "")),
    }


def _parse_detail_colours(page):
    match = re.search(r"Colours:\s*'((?:\\'|[^'])*)'", page, flags=re.S)
    if not match:
        return []
    raw = match.group(1).replace("\\'", "'")
    try:
        groups = json.loads(html.unescape(raw))
    except json.JSONDecodeError:
        return []

    colours = []
    for group in groups:
        group_name = _clean_text(group.get("ColourGroupName", ""))
        for colour in group.get("Colours") or []:
            images = colour.get("ImageUrls") or []
            rgb = _clean_text(colour.get("Rgb", ""))
            colours.append(
                {
                    "group": group_name,
                    "name": _clean_text(colour.get("ColourName") or colour.get("DisplayName")),
                    "display": _clean_text(colour.get("ColourName") or colour.get("DisplayName")),
                    "display_name": _clean_text(colour.get("DisplayName") or ""),
                    "colour_code": _clean_text(colour.get("ColourCode", "")),
                    "entry_code": _clean_text(colour.get("EntryCode", "")),
                    "rgb": rgb,
                    "hex": _rgb_to_hex(rgb),
                    "pantone": _clean_text(colour.get("Pantone", "")),
                    "cmyk": _clean_text(colour.get("Cmyk", "")),
                    "image": urljoin(BASE_URL, images[0]) if images else "",
                    "variants": [],
                    "total_stock": 0,
                }
            )
    return colours


def _fetch_colour_variants(entry_code):
    if not entry_code:
        return []
    payload = _fetch_json(urljoin(BASE_URL, f"/services/productservice/Variants?code={entry_code}"))
    rows = payload.get("Data") or []
    variants = []
    for row in rows:
        variants.append(
            {
                "size": _clean_text(row.get("SizeCode", "")),
                "entry_code": _clean_text(row.get("EntryCode", "")),
                "stock": int(float(row.get("Stock") or 0)),
                "total_stock": int(float(row.get("TotalStock") or 0)),
                "supplier_stock": int(float(row.get("SupplierStock") or 0)),
                "next_available": _clean_text(row.get("NextAvailable", "")),
            }
        )
    return variants


def _brand_filter_url(brand_url):
    parsed = urlparse(brand_url)
    path = parsed.path.rstrip("/")
    if not path:
        raise ValueError("Brand URL path is required.")
    return urljoin(BASE_URL, f"{path}/Filter?page=1&pageSize=60")


def _parse_filter_entries(payload):
    entries = payload.get("Data", {}).get("Entries", []) if isinstance(payload, dict) else []
    styles = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = _clean_text(entry.get("DisplayName") or entry.get("Name") or "")
        code = _clean_text(entry.get("ProductGroupCode") or entry.get("EntryCode") or "")
        if not name and not code:
            continue
        images = entry.get("ImageUrls") or []
        image = images[0] if images else ""
        details = []
        if entry.get("BrandName"):
            details.append(_clean_text(entry["BrandName"]))
        if entry.get("SizeRange"):
            details.append(f"Sizes {entry['SizeRange']}")
        if entry.get("AvailableColours") is not None:
            details.append(f"{entry['AvailableColours']} colours")
        styles.append(
            {
                "name": name or code,
                "code": code,
                "url": urljoin(BASE_URL, entry.get("DetailUrl", "")),
                "image": urljoin(BASE_URL, image) if image else "",
                "description": " | ".join(details),
            }
        )
    return _dedupe_styles(styles)


def _parse_product_json(page):
    styles = []
    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page,
        flags=re.I | re.S,
    ):
        raw = html.unescape(match.group(1).strip())
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for item in _walk_json(payload):
            if not isinstance(item, dict):
                continue
            if item.get("@type") != "Product" and "Product" not in str(item.get("@type", "")):
                continue
            name = _clean_text(item.get("name", ""))
            if not name:
                continue
            styles.append(
                {
                    "name": name,
                    "code": _clean_text(item.get("sku") or item.get("mpn") or ""),
                    "url": urljoin(BASE_URL, item.get("url", "")),
                    "image": _first_image(item.get("image")),
                    "description": _clean_text(item.get("description", "")),
                }
            )
    return _dedupe_styles(styles)


def _parse_product_links(page, page_url):
    parser = LinkParser()
    parser.feed(page)
    image_by_alt = {
        _clean_text(img["alt"]).casefold(): urljoin(page_url, img["src"])
        for img in parser.images
        if img.get("src") and _clean_text(img.get("alt"))
    }
    styles = []
    for link in parser.links:
        name = _clean_text(link.get("text") or link.get("title"))
        href = link.get("href", "")
        if not name or not href:
            continue
        absolute_url = urljoin(page_url, href)
        if not _looks_like_style(name, absolute_url, page_url):
            continue
        code = _extract_style_code(name, absolute_url)
        styles.append(
            {
                "name": name,
                "code": code,
                "url": absolute_url,
                "image": image_by_alt.get(name.casefold(), ""),
                "description": "",
            }
        )
    return _dedupe_styles(styles)


def _walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _first_image(value):
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = value.get("url", "")
    return urljoin(BASE_URL, value) if value else ""


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


def _parse_brand_menu(page):
    menu_match = re.search(
        r'<div[^>]*class=["\'][^"\']*\bbrandMenu\b[^"\']*["\'][^>]*>(.*?)<div[^>]*class=["\'][^"\']*\becomNavigationBlock\b',
        page,
        flags=re.I | re.S,
    )
    menu_html = menu_match.group(1) if menu_match else page
    parser = LinkParser()
    parser.feed(menu_html)

    brands = []
    seen = set()
    for link in parser.links:
        name = _clean_text(link.get("title") or link.get("text"))
        href = link.get("href", "").strip()
        if not _looks_like_brand(name, href):
            continue
        absolute_url = urljoin(BASE_URL, href)
        key = absolute_url.lower()
        if key in seen:
            continue
        seen.add(key)
        brands.append(
            {
                "name": name,
                "url": absolute_url,
                "slug": urlparse(absolute_url).path.strip("/"),
            }
        )
    return brands


def _merge_fallback_brands(live_brands):
    by_name = {brand["name"].casefold(): brand for brand in live_brands}
    for name, slug in FALLBACK_BRANDS:
        by_name.setdefault(
            name.casefold(),
            {
                "name": name,
                "url": urljoin(BASE_URL, f"{slug}/"),
                "slug": slug,
            },
        )
    return list(by_name.values())


def _slugify_brand(name):
    slug = html.unescape(name).casefold()
    slug = slug.replace("&", "and")
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def _looks_like_brand(name, href):
    if not name or len(name) > 42:
        return False
    parsed = urlparse(urljoin(BASE_URL, href))
    path = parsed.path.strip("/")
    if parsed.netloc and parsed.netloc != "shop.ralawise.com":
        return False
    if not path:
        return False
    if "/" in path:
        return False
    excluded = {
        "0-9",
        "a",
        "b",
        "c",
        "d",
        "e",
        "f",
        "g",
        "h",
        "i",
        "j",
        "k",
        "l",
        "m",
        "n",
        "o",
        "p",
        "q",
        "r",
        "s",
        "t",
        "u",
        "v",
        "w",
        "x",
        "y",
        "z",
        "shop",
        "shop all",
        "outerwear",
        "promotions",
        "new season",
        "fitness",
        "golf",
        "alfresco",
        "view all",
        "resources",
        "register",
        "forgotten password?",
    }
    return name.casefold() not in excluded


def _looks_like_style(name, url, page_url):
    if url.rstrip("/") == page_url.rstrip("/"):
        return False
    if "shop.ralawise.com" not in urlparse(url).netloc:
        return False
    lowered = name.casefold()
    blocked = (
        "forgotten password",
        "register",
        "filter by",
        "customer support",
        "delivery",
        "privacy",
        "cookie",
        "terms",
        "promotions",
        "raladeal",
        "order tracking",
        "make an enquiry",
        "new features",
        "quick shop",
        "join ralawise",
        "about us",
        "contact us",
        "resource hub",
        "payment options",
        "returns",
        "compliance",
        "revert",
    )
    if any(item in lowered for item in blocked):
        return False
    path = urlparse(url).path.strip("/")
    blocked_paths = (
        "landing-pages/",
        "footer-pages/",
        "my-account/",
        "create-account/",
        "customerserviceuserrolepage/",
        "link/",
        "de/",
        "fr/",
        "nl/",
    )
    if path.casefold().startswith(blocked_paths):
        return False
    return bool(re.search(r"\b[a-z]{1,5}\d{2,5}[a-z]?\b", name, re.I) or "/product" in path)


def _extract_style_code(name, url):
    match = re.search(r"\b[A-Z]{1,5}\d{2,5}[A-Z]?\b", name.upper())
    if match:
        return match.group(0)
    match = re.search(r"([a-z]{1,5}\d{2,5}[a-z]?)", urlparse(url).path, re.I)
    return match.group(1).upper() if match else ""


def _normalise_ralawise_url(url):
    absolute_url = urljoin(BASE_URL, url or "")
    parsed = urlparse(absolute_url)
    if parsed.netloc != "shop.ralawise.com":
        raise ValueError("Only shop.ralawise.com URLs are allowed.")
    return absolute_url


def _brand_name_from_url(url):
    slug = urlparse(url).path.strip("/").strip("-")
    return slug.replace("-", " ").title() if slug else "Ralawise"


def _clean_text(value):
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def _clean_html(value):
    text = re.sub(r"<br\s*/?>", " ", str(value or ""), flags=re.I)
    text = re.sub(r"</?(b|strong|em|span|p|div)[^>]*>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return _clean_text(text)


def _rgb_to_hex(rgb):
    nums = [int(n) for n in re.findall(r"\d+", rgb or "")[:3]]
    if len(nums) != 3:
        return ""
    return "#{:02x}{:02x}{:02x}".format(*[max(0, min(255, n)) for n in nums])
