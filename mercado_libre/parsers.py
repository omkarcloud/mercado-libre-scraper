"""Mercado Libre page state / JSON -> clean dicts. Pure functions, no I/O.

Fixtures (mercado_libre/fixtures/, captured 2026-10-24 through the app
webview route, see fetch.py): `*.html` are complete raw pages, `*.state.json`
the page's own `_n.ctx.r` state object (what extract_state returns), `*.json`
raw JSON responses. Every page built on the nordic framework inlines its
state as `_n.ctx.r={...}`; the data lives under
appProps.pageProps.initialState (search / product / best sellers) or
appProps.pageProps.data (deals).

Record shapes (all sites share them; ids carry the site prefix):
  polycard   a listing card (search, category, seller, store, deals, best
             sellers, classifieds) -> parse_polycard
  VPP / UPP  a product page: components keyed by id -> parse_product
  VIP        a classified page (real estate / vehicles) -> parse_classified
"""
import html as html_lib
import json
import math
import re
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse

from mercado_libre import refs

_STATE_RE = re.compile(r"_n\.ctx\.r\s*=\s*(\{)")
_TITLE_RE = re.compile(r"<title>([^<]*)</title>", re.I)
_INSTALLMENTS_RE = re.compile(r"(\d+)\s*(?:cuotas?|x|vezes|parcelas?)", re.I)
_INT_RE = re.compile(r"-?\d[\d.,]*")
_PICTURE_TEMPLATE = "https://http2.mlstatic.com/D_NQ_NP_{id}-O.webp"
# The site's condition labels (es / pt) -> the API's english tokens.
_CONDITIONS = {"nuevo": "new", "novo": "new", "usado": "used", "reacondicionado": "refurbished",
               "recondicionado": "refurbished", "new": "new", "used": "used"}
_THUMB_TEMPLATE = "https://http2.mlstatic.com/D_Q_NP_2X_{id}-R.webp"


# ---- state extraction ------------------------------------------------------------

def extract_state(html):
    """The page's `_n.ctx.r={...}` object, or None. The JSON contains braces
    inside strings, so this walks the text string-aware instead of
    regexing to the first `};`."""
    if not html:
        return None
    match = _STATE_RE.search(html)
    if not match:
        return None
    start = match.start(1)
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(html)):
        char = html[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start:index + 1])
                except ValueError:
                    return None
    return None


def page_title(html):
    match = _TITLE_RE.search(html or "")
    return html_lib.unescape(match.group(1)).strip() if match else ""


def page_props(state):
    if not isinstance(state, dict):
        return None
    props = (state.get("appProps") or {}).get("pageProps")
    return props if isinstance(props, dict) else None


def initial_state(state):
    props = page_props(state)
    if not props:
        return None
    ist = props.get("initialState")
    return ist if isinstance(ist, dict) else None


# ---- small value helpers ------------------------------------------------------------

def _text(value):
    """A label-like node -> its text, or None."""
    if value is None:
        return None
    if isinstance(value, str):
        value = " ".join(value.split())
        return value or None
    if isinstance(value, dict):
        for key in ("text", "label", "title", "name", "value"):
            inner = value.get(key)
            if isinstance(inner, str):
                return _text(inner)
            if isinstance(inner, dict) and key in ("label", "title"):
                return _text(inner)
    return None


def _number(value):
    """Loose numeric: int when whole, float otherwise, None when absent."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if float(value).is_integer() else value
    if isinstance(value, str):
        match = _INT_RE.search(value)
        if not match:
            return None
        token = match.group(0).rstrip(".,")
        if "," in token:
            # es/pt locale: "1.299.999,50" -> dots group, comma is decimal
            head, _, tail = token.rpartition(",")
            token = head.replace(".", "").replace(",", "") + ("." + tail if len(tail) <= 2 else tail)
        elif token.count(".") == 1 and 1 <= len(token.split(".")[1]) <= 2:
            pass   # "4.9" (a rating) keeps its decimal point
        else:
            token = token.replace(".", "")
        try:
            number = float(token)
        except ValueError:
            return None
        return int(number) if number.is_integer() else number
    return None


def _int(value):
    number = _number(value)
    return int(number) if isinstance(number, (int, float)) else None


def _money(node):
    """{"value": 1999999, "currency": "ARS"} / {"value", "currency_id"} -> {amount, currency}."""
    if not isinstance(node, dict):
        return None
    amount = _number(node.get("value"))
    if amount is None:
        return None
    return {"amount": amount, "currency": node.get("currency") or node.get("currency_id")}


def _render(template, values):
    """Fill a polycard text template ("{icon} {label}") with its values'
    texts; icons and unknown keys disappear."""
    if not isinstance(template, str):
        return None
    lookup = {}
    for item in values or []:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        kind = item.get("type")
        text = None
        if kind == "price":
            money = _money(item.get("price"))
            text = _format_amount(money) if money else None
        elif kind in ("label", "pill", "text"):
            text = _text(item.get(kind) or item.get("label") or item.get("pill"))
        elif kind == "icon":
            text = ""
        if key:
            lookup[key] = text or ""
    rendered = re.sub(r"\{(\w+)\}", lambda m: lookup.get(m.group(1), ""), template)
    rendered = " ".join(rendered.split())
    return rendered or None


def _format_amount(money):
    amount = money["amount"]
    if isinstance(amount, float):
        text = f"{amount:,.2f}"
    else:
        text = f"{amount:,}"
    return f"{text} {money.get('currency') or ''}".strip()


def _picture_link(picture_id, template=None):
    if not picture_id:
        return None
    template = (template or _PICTURE_TEMPLATE).replace("{sanitizedTitle}", "").replace("{sanitized_title}", "")
    template = template.replace("{square}", "NQ").replace("{2x}", "").replace("{size}", "O")
    return template.replace("{id}", picture_id)


def _absolute(link, site=None):
    """Polycard urls come without a scheme (www.mercadolibre.com.ar/...) or
    as a site-relative 'products/<id>/' path."""
    if not link:
        return None
    link = link.split("#")[0]
    if link.startswith(("http://", "https://")):
        return link
    if link.startswith("//"):
        return "https:" + link
    if re.match(r"^[a-z0-9.-]+\.(?:mercadolibre|mercadolivre)\.[a-z.]+/", link, re.I):
        return "https://" + link
    if site:
        return refs.site_info(site)["home"] + "/" + link.lstrip("/")
    return link


def _clean_link(link):
    """Drop the tracking fragment and the deal / client query junk."""
    if not link:
        return None
    link = link.split("#")[0]
    parsed = urlparse(link)
    if parsed.query:
        keep = [pair for pair in parsed.query.split("&")
                if pair.split("=")[0] in ("offer_type",)]
        link = link.split("?")[0] + ("?" + "&".join(keep) if keep else "")
    return link


def _iso_date(value):
    """ISO 8601 timestamps -> YYYY-MM-DD (UTC)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value[:10] if re.match(r"\d{4}-\d{2}-\d{2}", value) else None
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.date().isoformat()


def _iso_datetime(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _site_of(record_id, fallback=None):
    return refs.site_from_id(record_id) or fallback


def _currency_of(site):
    return refs.site_info(site)["currency"] if site in refs.SITES else None


# ---- polycards ----------------------------------------------------------------------

def _price_block(price):
    """A polycard `price` component body -> the public price dict."""
    if not isinstance(price, dict):
        return None
    current = _money(price.get("current_price"))
    previous = None
    for label in price.get("price_labels") or []:
        for value in (label or {}).get("values") or []:
            if value.get("type") == "price" and (value.get("price") or {}).get("previous"):
                previous = _money(value.get("price"))
    discount_pct = _number(price.get("discount_pct"))
    if discount_pct is None and price.get("discount_polylabel"):
        text = _render(price["discount_polylabel"].get("text"), price["discount_polylabel"].get("values"))
        match = re.search(r"(\d+)\s*%", text or "")
        discount_pct = int(match.group(1)) if match else None
    installments = _installments(price.get("installments"))
    complements = [_render(item.get("text"), item.get("values")) for item in price.get("price_complements") or []]
    discount_complement = None
    if isinstance(price.get("discount_complement"), dict):
        discount_complement = _render(price["discount_complement"].get("text"), price["discount_complement"].get("values"))
    return {
        "current": current,
        "previous": previous,
        "discount_percent": discount_pct,
        "prefix": _text(price.get("prefix")),
        "installments": installments,
        "discount_note": discount_complement,
        "notes": [c for c in complements if c] or None,
    }


def _installments(node):
    if not isinstance(node, dict):
        return None
    text = _render(node.get("text"), node.get("values"))
    amount = None
    for value in node.get("values") or []:
        if value.get("type") == "price":
            amount = _money(value.get("price"))
    match = _INSTALLMENTS_RE.search(node.get("text") or "")
    return {
        "quantity": int(match.group(1)) if match else None,
        "amount": amount,
        "is_interest_free": bool(node.get("no_interest")) if "no_interest" in node else None,
        "text": text,
    }


def parse_polycard(card, site=None, position=None):
    """One listing card -> {id, product_id, title, link, price, ...}."""
    pc = card.get("polycard") if isinstance(card, dict) and "polycard" in card else card
    if not isinstance(pc, dict):
        return None
    meta = pc.get("metadata") or {}
    item_id = meta.get("id")
    site = _site_of(item_id, site) or _site_of(meta.get("product_id"), site)
    comps = {}
    for comp in pc.get("components") or []:
        if isinstance(comp, dict) and comp.get("type"):
            comps.setdefault(comp.get("id") or comp["type"], comp)

    def body(key):
        """A component's payload: components are {type, id, <type>: {...}}."""
        comp = comps.get(key)
        return comp.get(comp.get("type")) if isinstance(comp, dict) else None

    title = _text(body("title"))
    seller_comp = comps.get("seller")
    seller_name = None
    is_official_store = None
    if seller_comp:
        seller_name = _render(seller_comp["seller"].get("text"), seller_comp["seller"].get("values"))
        is_official_store = any(v.get("key") == "icon_cockade" for v in seller_comp["seller"].get("values") or [])
    rating = None
    sold_label = None
    review = comps.get("review_compacted")
    if review:
        for value in review["review_compacted"].get("values") or []:
            text = _text(value.get("label"))
            if value.get("key") == "label":
                rating = _number(text)
            elif value.get("key") == "label2":
                sold_label = (text or "").strip("| ").strip() or None
    shipping_texts = []
    for line in body("shipping_v2") or []:
        text = _render(line.get("text"), line.get("values"))
        if text:
            shipping_texts.append(text)
    shipping_blob = " ".join(shipping_texts).lower()
    shipping_keys = {v.get("key") for line in body("shipping_v2") or [] for v in line.get("values") or []}
    # "Llega gratis hoy por ser tu primera compra": free only for a new buyer
    is_first_purchase_offer = "new_buyer" in shipping_keys or "primera compra" in shipping_blob or "primeira compra" in shipping_blob
    mentions_free = "gratis" in shipping_blob or "grátis" in shipping_blob
    is_full = any(v.get("key") in ("full_icon", "vpp_full_icon") for line in body("shipping_v2") or [] for v in line.get("values") or [])
    promotions = [_render(p.get("text"), p.get("values")) for p in body("promotions") or []
                  if isinstance(p, dict) and p.get("text")]
    promotions = [p for p in promotions if p]
    countdown = comps.get("highlight_countdown")
    variations = pc.get("variations_compacted") or {}
    pictures = (pc.get("pictures") or {}).get("pictures") or []
    picture_id = pictures[0].get("id") if pictures and isinstance(pictures[0], dict) else None
    link = _absolute(meta.get("url"), site)
    is_ad = bool(link and "/mclics/" in link)
    user_product_id = meta.get("user_product_id") if meta.get("user_product_id") not in (None, "not_apply") else None
    # deal / best-seller cards carry a site-relative "products/<id>/" url that
    # 404s: the catalog product lives at /p/<id>, a user product at /up/<id>
    if link and (("/products/" in link) or is_ad) and meta.get("product_id") and site:
        link = refs.product_link(site, meta["product_id"])
    elif link and "/products/" in link and user_product_id and site:
        link = refs.user_product_link(site, user_product_id)
    elif (is_ad or (link and "/products/" in link)) and item_id and site:
        link = refs.item_link(site, item_id)
    cbt = comps.get("cbt")
    condition = _CONDITIONS.get((_text(body("item_condition")) or "").lower(), _text(body("item_condition")))
    highlight = comps.get("highlight")
    highlight_text = _render(highlight["highlight"].get("text"), highlight["highlight"].get("values")) if highlight else None
    sold_quantity = _int(((meta.get("tracks") or {}).get("sold_quantity")))
    if sold_quantity is None and sold_label:
        sold_quantity = _int(sold_label)
    record = {
        "id": item_id,
        "product_id": meta.get("product_id"),
        "user_product_id": meta.get("user_product_id") if meta.get("user_product_id") != "not_apply" else None,
        "title": title,
        "link": _clean_link(link),
        "condition": condition,
        "price": _price_block(body("price_v2") or body("price")),
        "seller": {"name": seller_name, "is_official_store": is_official_store} if seller_name else None,
        "rating": rating,
        "sold_quantity": sold_quantity,
        "shipping": {
            "text": shipping_texts or None,
            "is_free": (mentions_free and not is_first_purchase_offer) if shipping_texts else None,
            "is_free_for_first_purchase": (mentions_free and is_first_purchase_offer) if shipping_texts else None,
            "is_fulfillment": is_full if shipping_texts else None,
        } if shipping_texts else None,
        "highlight": highlight_text,
        "is_ad": is_ad,
        "deal_ends_at": _iso_datetime(((countdown or {}).get("highlight_countdown") or {}).get("countdown", {}).get("period_end")) if countdown else None,
        "promotions": promotions or None,
        "variations": [v.get("description") for v in variations.get("variations") or [] if v.get("description")] or None,
        "attributes": (body("attributes_list") or {}).get("texts") or None,
        "location": _text(body("location")),
        "headline": _text(body("headline")),
        "label": _text((comps.get("project") or {}).get("pill")),
        "availability": _text(body("available_units")) or _text(body("possession_date")),
        "is_international": bool(cbt),
        "international_origin": _render(cbt["cbt"].get("text"), cbt["cbt"].get("values")) if cbt else None,
        "has_trade_in": "trade_in" in comps or None,
        "is_featured": bool(pc.get("featured")) or None,
        "image": _picture_link(picture_id),
        "position": position,
    }
    return record


def _pagination(ist, page, page_size):
    event = ((ist.get("melidata_track") or {}).get("event_data") or {})
    total = _int(event.get("total"))
    pagination = ist.get("pagination") or {}
    limit = _int(event.get("limit")) or page_size
    results_limit = _int(pagination.get("results_limit"))
    reachable = min(total, results_limit) if (total is not None and results_limit) else total
    total_pages = None
    if reachable is not None and limit:
        total_pages = max(math.ceil(reachable / limit), 1 if page == 1 else 0)
    page_count = _int(pagination.get("page_count"))
    if page_count and (total_pages is None or page_count < total_pages):
        total_pages = page_count
    return {"page": page, "items_per_page": limit, "total_pages": total_pages, "total_count": total}


def _breadcrumb(nodes):
    out = []
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        text = _text(node.get("text") or node.get("label"))
        link = node.get("url") or node.get("target")
        if text:
            out.append({"name": text, "link": link})
    return out or None


def _sort_options(ist):
    sorts = (((ist.get("view_options") or {}).get("sort") or {}).get("sorts")) or []
    out = []
    for sort in sorts:
        if isinstance(sort, dict) and sort.get("id"):
            out.append({"id": sort["id"], "name": sort.get("name"), "is_selected": bool(sort.get("selected"))})
    return out or None


def _applied_filters(ist):
    options = ist.get("filtering_options") or {}
    out = []
    for flt in options.get("applied_filters") or []:
        for value in flt.get("values") or []:
            out.append({"id": flt.get("id"), "name": flt.get("name"), "value_id": value.get("id"), "value": value.get("name")})
    return out or None


def _available_filters(ist):
    options = ist.get("filtering_options") or {}
    out = []
    for flt in options.get("available_filters") or []:
        values = []
        for value in flt.get("values") or []:
            match = re.search(r"(\d[\d.,]*)\s*resultados?", value.get("accessibility_text") or "")
            values.append({"id": value.get("id"), "name": value.get("name"),
                           "results": _int(match.group(1)) if match else None,
                           "link": (value.get("url") or "").split("#")[0] or None})
        out.append({"id": flt.get("id"), "name": flt.get("name"), "type": flt.get("type"), "values": values})
    return out or None


def parse_listing(state, page=1, site=None):
    """A search / category / seller / store / classifieds listing page state
    -> {results, pagination, query, category, breadcrumb, sort, filters}."""
    ist = initial_state(state)
    if not ist or "results" not in ist:
        return None
    event = ((ist.get("melidata_track") or {}).get("event_data") or {})
    results = []
    for index, card in enumerate(ist.get("results") or []):
        if isinstance(card, dict) and card.get("id") == "POLYCARD":
            parsed = parse_polycard(card, site, position=(page - 1) * refs.PAGE_SIZE + len(results) + 1)
            if parsed:
                results.append(parsed)
    site = site or (_site_of(results[0]["id"]) if results else None) or _site_of(event.get("category_id"))
    header = ist.get("header") if isinstance(ist.get("header"), dict) else None
    return {
        "site": site,
        "query": ist.get("query") or event.get("query") or None,
        "category": {"id": event.get("category_id"), "path": event.get("category_path") or None}
        if event.get("category_id") else None,
        "vertical": ist.get("vertical") or event.get("vertical") or None,
        "sort": event.get("sort_id") or None,
        "sort_options": _sort_options(ist),
        "applied_filters": _applied_filters(ist),
        "available_filters": _available_filters(ist),
        "breadcrumb": _breadcrumb(ist.get("breadcrumb")),
        "related_searches": [r.get("q") for r in ((ist.get("related_searches") or {}).get("related_searches") or []) if r.get("q")] or None,
        "header": {"title": header.get("title"), "subtitle": header.get("subtitle"),
                   "logo": ((header.get("logo") or {}).get("pictures") or {}).get("2x") or ((header.get("logo") or {}).get("pictures") or {}).get("1x"),
                   "link": header.get("url")} if header else None,
        "results": results,
        "pagination": _pagination(ist, page, refs.PAGE_SIZE),
    }


def is_no_results_page(state, html=None):
    """The 'No encontramos resultados' shell: a search state with no
    appProps at all (unknown seller / store / category)."""
    if not isinstance(state, dict):
        return True
    return page_props(state) is None


# ---- product page (VPP / UPP) -----------------------------------------------------------

def _visible(comp):
    return isinstance(comp, dict) and comp.get("state") != "HIDDEN"


def _event_data(components, ist=None):
    """The page's melidata view event: VPP pages carry it as the `track`
    component, VIP pages at initialState.track."""
    track = components.get("track") or (ist or {}).get("track") or {}
    return ((track.get("melidata_event") or {}).get("event_data")) or {}


def _coordinate(value):
    """A latitude / longitude given as a number or a plain decimal string."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and re.fullmatch(r"-?\d{1,3}(\.\d+)?", value.strip()):
        return float(value)
    return None


def _find_coordinates(node, depth=0):
    """Any {latitude, longitude} pair nested in a map config."""
    if depth > 6 or not isinstance(node, (dict, list)):
        return None
    if isinstance(node, dict):
        lat = _coordinate(node.get("latitude", node.get("lat")))
        lng = _coordinate(node.get("longitude", node.get("lng", node.get("lon"))))
        if lat is not None and lng is not None:
            return {"latitude": lat, "longitude": lng}
        for value in node.values():
            found = _find_coordinates(value, depth + 1)
            if found:
                return found
    else:
        for value in node:
            found = _find_coordinates(value, depth + 1)
            if found:
                return found
    return None


def _price_component(comp):
    """A VPP `price` component -> {amount, currency, original, installments, notes}."""
    if not _visible(comp):
        return None
    price = comp.get("price") or {}
    money = _money({"value": price.get("value"), "currency": price.get("currency_id")})
    if not money:
        return None
    original = _number(price.get("original_value"))
    installments = None
    notes = []
    for sub in comp.get("subtitles") or []:
        values = sub.get("values") or {}
        text = sub.get("text") or ""
        rendered = text
        for key, value in values.items():
            inner = _money({"value": value.get("value"), "currency": value.get("currency") or money["currency"]}) if isinstance(value, dict) and value.get("type") == "price" else None
            rendered = rendered.replace("{" + key + "}", _format_amount(inner) if inner else _text(value) or "")
        rendered = " ".join(rendered.split())
        if sub.get("id") == "pricing_price_subtitle":
            match = _INSTALLMENTS_RE.search(text)
            amount = next((_money({"value": v.get("value"), "currency": money["currency"]}) for v in values.values()
                           if isinstance(v, dict) and v.get("type") == "price"), None)
            installments = {"quantity": int(match.group(1)) if match else None, "amount": amount,
                            "is_interest_free": ("mismo precio" in text.lower() or "sin interés" in text.lower() or "sem juros" in text.lower()),
                            "text": rendered}
        elif rendered:
            notes.append(rendered)
    discount = None
    for tag in comp.get("price_tags") or []:
        text = _text(tag)
        match = re.search(r"(\d+)\s*%", text or "")
        if match:
            discount = int(match.group(1))
    return {
        "current": money,
        "previous": {"amount": original, "currency": money["currency"]} if original is not None else None,
        "discount_percent": discount,
        "installments": installments,
        "notes": notes or None,
    }


def _key_values(components):
    """highlighted_specs `key_value` rows + the technical_specifications
    groups -> ({key: value}, [groups])."""
    highlights = {}
    groups = []
    for comp in components:
        if not isinstance(comp, dict):
            continue
        if comp.get("type") == "key_value":
            title = comp.get("title") or {}
            values = title.get("values") or {}
            key = _text(values.get("key"))
            value = _text(values.get("value"))
            if key and value:
                highlights[key.rstrip(":")] = value
        elif comp.get("type") == "technical_specifications":
            for spec in comp.get("specs") or []:
                attributes = [{"name": a.get("id"), "value": a.get("text")} for a in spec.get("attributes") or [] if a.get("id")]
                if attributes:
                    groups.append({"group": spec.get("title"), "attributes": attributes})
    return highlights, groups


def _seller_from_vpp(components, event):
    data = components.get("seller_data") or {}
    parts = {c.get("id"): c for c in data.get("components") or [] if isinstance(c, dict)}
    header = parts.get("seller_header") or {}
    status = parts.get("seller_status") or {}
    banner = parts.get("seller_banner") or {}
    view_event = ((data.get("viewport_track") or {}).get("melidata_event") or {}).get("event_data") or {}
    name = event.get("seller_name") or view_event.get("shop_name")
    title = _text(header.get("title"))
    if title and not name:
        name = re.sub(r"^(Vendido por|Vendido por:)\s*", "", title, flags=re.I)
    products = _text(((header.get("products") or {}).get("values") or {}).get("products"))
    followers_node = ((header.get("followers") or {}).get("cta_do_follow") or {}).get("title") or {}
    followers = _text((followers_node.get("values") or {}).get("followers"))
    status_info = status.get("seller_status_info") or {}
    info_rows = []
    sales = None
    for row in status.get("info") or []:
        title_text = _text(row.get("title"))
        subtitle = _text(row.get("subtitle"))
        if subtitle and title_text and subtitle.lower() in ("ventas", "vendas"):
            sales = title_text
        elif subtitle:
            info_rows.append(subtitle)
    link = ((header.get("action") or {}).get("target") or (banner.get("logo") or {}).get("action", {}).get("target"))
    seller_id = event.get("seller_id") or view_event.get("seller_id")
    store_id = event.get("official_store_id") or None
    out = {
        "id": seller_id,
        "name": name,
        "is_official_store": bool(store_id) or view_event.get("seller_type") == "official_store",
        "official_store_id": store_id,
        "reputation_level": event.get("reputation_level") or view_event.get("reputation"),
        "power_seller_status": event.get("power_seller_status") if event.get("power_seller_status") not in (None, "not_apply") else None,
        "status": _text(status_info.get("title")),
        "status_note": _text(status_info.get("subtitle")),
        "reputation_rank": _int(status.get("rank")) if status else None,
        "sales": sales,
        "service_notes": info_rows or None,
        "products": products,
        "followers": followers,
        "logo": ((banner.get("logo") or {}).get("url") or {}).get("src"),
        "link": _clean_link(link) if link else None,
    }
    if not any(v for k, v in out.items() if k not in ("is_official_store",)):
        return None
    return out


def _variations(components, item_id=None):
    """outside_variations pickers. On a catalog product page each option is
    another product (its own id and link); on a plain item page every option
    repeats the item's own id, so those ids are null and the option name is
    the identifier."""
    pickers = []
    for picker in (components.get("outside_variations") or {}).get("pickers") or []:
        options = []
        for product in picker.get("products") or []:
            price = product.get("price") or {}
            option_id = product.get("id")
            if option_id and option_id == item_id:
                option_id = None
            options.append({
                "id": option_id,
                "name": _text(product.get("label")) or _text(product.get("option_label")),
                "link": _clean_link(product.get("permalink")),
                "image": _picture_link((product.get("picture") or {}).get("id")),
                "price": _money({"value": price.get("value"), "currency": price.get("currency_id")}) if price else None,
                "previous_price": _money({"value": price.get("original_value"), "currency": price.get("currency_id")}) if price and price.get("original_value") else None,
                "stock": _text(product.get("stock")),
                "is_selected": (product.get("decoration_type") == "SELECTED"
                                or _text(product.get("option_label") or product.get("label")) == _text(picker.get("selected_option"))),
            })
        pickers.append({"id": picker.get("id"), "name": (_text(picker.get("label")) or "").rstrip(":") or picker.get("id"),
                        "selected": _text(picker.get("selected_option")), "options": options or None})
    return pickers or None


def _gallery(components):
    gallery = components.get("gallery") or {}
    template = (gallery.get("picture_config") or {}).get("template")
    pictures = []
    for picture in gallery.get("pictures") or []:
        if isinstance(picture, dict) and picture.get("id"):
            pictures.append({"link": _picture_link(picture["id"], template), "width": picture.get("width"), "height": picture.get("height")})
    return pictures or None


def _buy_box_offers(components, currency):
    offers = []
    for item in (components.get("buy_box_offers") or {}).get("items") or []:
        price_comp = next((c for c in item.get("components") or [] if c.get("id") == "price"), None)
        offers.append({"type": item.get("type"), "item_id": item.get("item_id"), "title": _text(item.get("title")),
                       "price": _price_component(price_comp), "is_selected": bool(item.get("selected"))})
    return offers or None


def _rating_block(rating):
    if not isinstance(rating, dict):
        return None
    levels = rating.get("levels") or []
    stars = {}
    for level in levels:
        index = level.get("index")
        if isinstance(index, int):
            stars[str(5 - index)] = {"count": _int(level.get("value")), "percent": _number(level.get("percentage"))}
    return {
        "average": _number(rating.get("average")),
        "count": _int(rating.get("amount")),
        "with_comments": _int(rating.get("reviews_with_comments")) or None,
        "stars": stars or None,
        "photos": _int(rating.get("pictures_quantity")),
        "videos": _int(rating.get("videos_quantity")),
    }


def parse_product(state, page_url=None, site=None):
    """A product (VPP / UPP) page state -> the product record."""
    ist = initial_state(state)
    if not ist or not isinstance(ist.get("components"), dict):
        return None
    components = ist["components"]
    event = _event_data(components, ist)
    header = components.get("header") or {}
    metadata = components.get("metadata") or {}
    item_id = event.get("item_id")
    if _visible(components.get("no_stock_status")) and "has_stock" not in event:
        event = dict(event, has_stock=False)
    product_id = event.get("catalog_product_id") if event.get("catalog_product_id") not in (None, "N/A", "not_apply") else None
    page_id = ist.get("id")
    site = _site_of(item_id, site) or _site_of(product_id, site) or _site_of(page_id, site)
    currency = event.get("currency_id") or _currency_of(site)
    price = None
    for item in (components.get("buy_box_offers") or {}).get("items") or []:
        if item.get("selected") or item.get("type") == "BEST_PRICE" or item.get("item_id") == item_id:
            price_comp = next((c for c in item.get("components") or [] if c.get("id") == "price"), None)
            price = _price_component(price_comp) or price
    if price is None:
        price = _price_component(components.get("price"))
    if price is None and event.get("price") is not None:
        price = {"current": {"amount": _number(event.get("price")), "currency": currency},
                 "previous": {"amount": _number(event.get("original_price")), "currency": currency} if event.get("original_price") else None,
                 "discount_percent": None, "installments": None, "notes": None}
    if price and price.get("previous") is None and event.get("original_price"):
        price["previous"] = {"amount": _number(event.get("original_price")), "currency": currency}
    if price and price.get("discount_percent") is None and price.get("previous") and price["current"]:
        prev, cur = price["previous"]["amount"], price["current"]["amount"]
        if prev and cur and prev > cur:
            price["discount_percent"] = round((prev - cur) / prev * 100)
    highlights, spec_groups = _key_values((components.get("highlighted_specs_attrs") or {}).get("components") or [])
    features = []
    for comp in (components.get("highlighted_specs_features") or {}).get("components") or []:
        if comp.get("type") == "highlighted_features":
            features.extend(_text(f) for f in comp.get("features") or [] if _text(f))
    reviews_comp = components.get("reviews_capability_v3") or {}
    rating = _rating_block(reviews_comp.get("rating")) if _visible(reviews_comp) else None
    if rating is None and isinstance(header.get("reviews"), dict):
        rating = {"average": _number(header["reviews"].get("rating")), "count": _int(header["reviews"].get("amount"))}
    reviews_event = event.get("reviews") if isinstance(event.get("reviews"), dict) else {}
    if rating and reviews_event and rating.get("with_comments") is None:
        rating["with_comments"] = _int(reviews_event.get("reviews_with_comment"))
    summary_comp = (reviews_comp.get("summary") or {}) if isinstance(reviews_comp.get("summary"), dict) else {}
    ai_summary = next((_text(c.get("summary_text")) for c in summary_comp.get("components") or [] if c.get("id") == "SUMMARY"), None)
    description = components.get("description") or {}
    quantity = components.get("available_quantity") or {}
    selector = quantity.get("quantity_selector") or {}
    available = _int(selector.get("available_quantity"))
    if available is None:
        available = _int(((quantity.get("picker") or {}).get("track") or {}).get("melidata_event", {}).get("event_data", {}).get("quantity"))
    if available is None:
        available = _int(event.get("quantity"))
    benefits = [_render(b.get("text"), [{"key": k, "type": "label", "label": v.get("label")} for k, v in (b.get("values") or {}).items()])
                for b in (components.get("buy_benefits") or {}).get("benefits") or []]
    payment_methods = []
    for group in (components.get("payment_methods") or {}).get("payment_methods") or []:
        for icon in group.get("icons") or []:
            if icon.get("name") and icon["name"] not in payment_methods:
                payment_methods.append(icon["name"])
    schema = ist.get("schema") if isinstance(ist.get("schema"), list) else []
    offer = ((schema[0] if schema else {}).get("offers") or {}) if schema else {}
    canonical = metadata.get("url_canonical") or ((components.get("share") or {}).get("permalink") or "").split("?")[0] or page_url
    subtitle = header.get("subtitle") or ""
    condition = event.get("item_condition") or (("used" if re.search(r"\busad[oa]\b", subtitle, re.I) else "new") if subtitle else None)
    return {
        "id": item_id or page_id,
        "product_id": product_id,
        "user_product_id": event.get("user_product_id") if event.get("user_product_id") not in (None, "not_apply") else None,
        "parent_product_id": event.get("catalog_parent_id") if event.get("catalog_parent_id") not in (None, "not_apply") else None,
        "site": site,
        "title": header.get("title") or page_title_from_state(state),
        "subtitle": subtitle or None,
        "link": _clean_link(canonical),
        "condition": condition,
        "sold_quantity": _int(event.get("sold_quantity")),
        "price": price,
        "offers": _buy_box_offers(components, currency),
        "variations": _variations(components, item_id),
        "stock": {
            "has_stock": bool(event.get("has_stock")) if "has_stock" in event else (available or 0) > 0,
            "available_quantity": available,
            "note": _text((components.get("stock_information") or {}).get("title")) if _visible(components.get("stock_information")) else None,
            "type": event.get("stock_type") if event.get("stock_type") not in (None, "not_apply") else None,
        },
        "shipping": {
            "is_free": event.get("free_shipping") if isinstance(event.get("free_shipping"), bool) else None,
            "mode": event.get("shipping_mode") if event.get("shipping_mode") not in (None, "not_specified") else None,
            "logistic_type": event.get("logistic_type") or None,
            "has_local_pickup": event.get("local_pick_up") if isinstance(event.get("local_pick_up"), bool) else None,
            "has_store_pickup": event.get("store_pick_up") if isinstance(event.get("store_pick_up"), bool) else None,
            "cost": _money({"value": ((offer.get("shippingDetails") or {}).get("shippingRate") or {}).get("value"),
                            "currency": ((offer.get("shippingDetails") or {}).get("shippingRate") or {}).get("currency")}),
        },
        "rating": rating,
        "reviews_ai_summary": ai_summary,
        "highlights": features or None,
        "specs": highlights or None,
        "spec_groups": spec_groups or None,
        "description": description.get("content") if _visible(description) else None,
        "images": _gallery(components),
        "seller": _seller_from_vpp(components, event),
        "benefits": [b for b in benefits if b] or None,
        "payment_methods": payment_methods or None,
        "category": {"id": event.get("category_id"), "domain_id": event.get("domain_id"),
                     "breadcrumb": _breadcrumb((components.get("breadcrumb") or {}).get("categories"))}
        if event.get("category_id") or components.get("breadcrumb") else None,
        "listing_type": event.get("listing_type_id") or None,
        "related_searches": [_text(r.get("label")) for r in (components.get("related_searches") or {}).get("related_searches") or [] if _text(r.get("label"))] or None,
        "availability": (offer.get("availability") or "").rsplit("/", 1)[-1] or None,
        "price_valid_until": _iso_date(offer.get("priceValidUntil")),
        "tags": [t for t in event.get("tags") or [] if isinstance(t, str)] or None,
    }


def page_title_from_state(state):
    title = (state or {}).get("title")
    return title.strip() if isinstance(title, str) and title.strip() else None


# ---- classified page (VIP) --------------------------------------------------------------

def _rows_text(comp):
    out = []
    for row in (comp or {}).get("content_rows") or []:
        text = _text(row.get("title")) or _text(row.get("label"))
        if text:
            out.append(text)
    return out


def _location_block(components):
    location = components.get("location") or components.get("location_and_points") or {}
    rows = _rows_text(location)
    coords = _find_coordinates(location.get("map_info") or location.get("map") or components.get("map_configuration"))
    proximity = _rows_text(components.get("item_proximity"))
    address = rows[0] if rows else (proximity[0] if proximity else None)
    if not address and coords is None:
        return None
    return {"address": address, "notes": (rows[1:] or None) if rows else None, "coordinates": coords}


def _features_groups(components):
    groups = []
    for comp_key in ("all_features", "highlighted_specs_attrs", "highlighted_specs_res"):
        comp = components.get(comp_key) or {}
        if comp_key == "highlighted_specs_res":
            attributes = [{"name": None, "value": _text(a.get("label"))} for a in comp.get("attributes") or [] if _text(a.get("label"))]
            if attributes:
                groups.append({"group": _text(comp.get("title")) or "summary", "attributes": attributes})
            continue
        highlights, spec_groups = _key_values(comp.get("components") or [])
        if highlights:
            groups.append({"group": _text(comp.get("title")) or "highlights", "attributes": [{"name": k, "value": v} for k, v in highlights.items()]})
        groups.extend(spec_groups)
        for spec in comp.get("specs") or []:
            attributes = [{"name": a.get("id"), "value": a.get("text")} for a in spec.get("attributes") or [] if a.get("id")]
            if attributes:
                groups.append({"group": spec.get("title"), "attributes": attributes})
    # de-duplicate identical groups coming from the two spec components
    seen = set()
    unique = []
    for group in groups:
        key = json.dumps(group, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            unique.append(group)
    return unique or None


def _seller_profile(components, event):
    profile = components.get("seller_profile") or {}
    if not _visible(profile):
        return None
    name_node = profile.get("seller_name") or {}
    status = (profile.get("seller_status") or {}).get("seller_status_info") or {}
    extra = []
    for row in profile.get("extra_info") or []:
        if isinstance(row, dict):
            text = _text(row.get("title")) or _text(row.get("subtitle")) or _text(row)
            if text:
                extra.append(text)
    return {
        "id": event.get("seller_id"),
        "name": _text(name_node.get("title")) or event.get("seller_name"),
        "type": event.get("seller_type") or event.get("item_seller_type") or None,
        "heading": _text(profile.get("header")),
        "label": _text(name_node.get("label")),
        "is_verified": bool(name_node.get("user_status_icon")),
        "logo": ((name_node.get("logo") or {}).get("url") or {}).get("src"),
        "reputation_level": event.get("reputation_level") if event.get("reputation_level") not in (None, "none") else None,
        "power_seller_status": event.get("power_seller_status") if event.get("power_seller_status") not in (None, "not_apply") else None,
        "status": _text(status.get("title")),
        "status_note": _text(status.get("subtitle")),
        "reputation_rank": _int((profile.get("seller_status") or {}).get("rank")),
        "notes": extra or None,
        "link": ((name_node.get("action") or {}).get("target")) or ((profile.get("link_label") or {}).get("action") or {}).get("target"),
    }


def parse_classified(state, page_url=None, site=None):
    """A classified (real-estate / vehicle / service) VIP state -> record."""
    ist = initial_state(state)
    if not ist or not isinstance(ist.get("components"), dict):
        return None
    components = ist["components"]
    event = _event_data(components, ist)
    header = components.get("header") or {}
    item_id = event.get("item_id") or ist.get("id")
    site = _site_of(item_id, site)
    price_comp = components.get("price") or {}
    price_node = price_comp.get("price") or {}
    price = _money({"value": price_node.get("value"), "currency": price_node.get("currency_id")}) if _visible(price_comp) else None
    if price is None and event.get("price") is not None:
        price = {"amount": _number(event.get("price")), "currency": event.get("currency_id") or _currency_of(site)}
    description = components.get("description") or {}
    models = []
    models_comp = components.get("models") or {}
    for row in models_comp.get("content_rows") or models_comp.get("models") or []:
        if isinstance(row, dict):
            pictures = [_picture_link(p.get("id")) for p in row.get("pictures") or [] if isinstance(p, dict) and p.get("id")]
            models.append({"price_label": _text(row.get("upper_label")), "price": _text(row.get("title")),
                           "description": _text(row.get("subtitle")), "images": pictures or None})
    poi = []
    poi_comp = (components.get("points_of_interest") or ist.get("points_of_interest")
                or components.get("location_and_points") or {})
    for group in poi_comp.get("categories") or poi_comp.get("groups") or []:
        if isinstance(group, dict):
            poi.append({"category": _text(group.get("title")), "summary": (_text(group.get("subtitle")) or "").rstrip(", ") or None,
                        "places": [_text(p) for p in group.get("items") or group.get("places") or [] if _text(p)] or None})
    comparison = components.get("price_comparison") or {}
    chart = comparison.get("chart") or {}
    metadata = components.get("metadata") or {}
    share = components.get("share") or ist.get("share") or {}
    schema = ist.get("schema") if isinstance(ist.get("schema"), list) else []
    link = metadata.get("url_canonical") or (share.get("permalink") or "").split("?")[0] or page_url
    return {
        "id": item_id,
        "site": site,
        "title": header.get("title") or page_title_from_state(state),
        "subtitle": header.get("subtitle") or None,
        "link": _clean_link(link),
        "vertical": ist.get("vertical") or event.get("vertical") or None,
        "price": {"current": price, "label": _text(price_comp.get("upper_label")),
                  "notes": [_text(s) for s in price_comp.get("subtitles") or [] if _text(s)] or None} if price else None,
        "price_reference": {"low": _text(chart.get("lower_band")), "high": _text(chart.get("upper_band")),
                            "note": _text(comparison.get("header_title"))} if _visible(comparison) and chart else None,
        "attributes": _features_groups(components),
        "location": _location_block(components),
        "description": description.get("content") if _visible(description) else None,
        "images": _gallery(components),
        "models": models or None,
        "points_of_interest": poi or None,
        "seller": _seller_profile(components, event),
        "category": {"id": event.get("category_id"), "domain_id": event.get("domain_id"),
                     "breadcrumb": _breadcrumb((components.get("breadcrumb") or {}).get("categories"))}
        if event.get("category_id") or components.get("breadcrumb") else None,
        "condition": event.get("item_condition") or None,
        "listing_type": event.get("listing_type_id") or None,
        "published_at": _iso_date(event.get("start_time")),
        "availability": ((schema[0].get("offers") or {}).get("availability") or "").rsplit("/", 1)[-1] or None if schema else None,
    }


# ---- reviews ------------------------------------------------------------------------------

def _review_media(node):
    """A review's media (list of pictures / videos, or {pictures, videos})."""
    out = []
    if isinstance(node, dict):
        items = list(node.get("pictures") or []) + list(node.get("videos") or [])
    elif isinstance(node, list):
        items = node
    else:
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = (item.get("type") or ("video" if item.get("video_url") or item.get("thumbnail") else "photo")).lower()
        link = item.get("url") or item.get("video_url") or _picture_link(item.get("id") or item.get("picture_id"))
        if link:
            entry = {"type": kind, "link": link}
            if item.get("thumbnail"):
                entry["thumbnail"] = item["thumbnail"] if isinstance(item["thumbnail"], str) else _text(item["thumbnail"])
            out.append(entry)
    return out


def parse_review(review):
    if not isinstance(review, dict):
        return None
    comment = review.get("comment") or {}
    content = comment.get("content") or {}
    likes = None
    for action in review.get("actions") or []:
        if action.get("id") == "LIKE":
            likes = _int(action.get("value"))
    created = None
    for action in review.get("actions") or []:
        track = ((action.get("track") or {}).get("event_data") or {}).get("review") or {}
        if track.get("created_date"):
            created = _iso_date(track["created_date"])
    if not created:
        track = (((comment.get("menu_options") or {}).get("items") or [{}])[0].get("track") or {}).get("event_data", {}).get("review") or {}
        created = _iso_date(track.get("created_date"))
    # the review lists its media once at the top level; the carousel repeats
    # them at another resolution, so it is only a fallback
    media = _review_media(review.get("media")) or _review_media(comment.get("media"))
    if not media and isinstance(review.get("carousel"), dict):
        media = _review_media(review["carousel"].get("media"))
    return {
        "id": review.get("id"),
        "rating": _int(review.get("rating")),
        "text": _text(content.get("text")),
        "date": created,
        "relative_date": _text(comment.get("date")),
        "country": _text(comment.get("country")),
        "variant": _text(review.get("variant")),
        "likes": likes,
        "is_translated": bool(comment.get("translated")) if "translated" in comment else None,
        "media": media or None,
    }


def parse_reviews_search(payload):
    """The reviews search XHR -> (reviews, not_found_message)."""
    if not isinstance(payload, dict):
        return [], None
    reviews = [parse_review(r) for r in payload.get("reviews") or []]
    message = payload.get("message") if isinstance(payload.get("message"), dict) else None
    return [r for r in reviews if r], (_text(message.get("title")) if message else None)


def parse_reviews_summary(state):
    """The reviews modal page state -> {rating, ai_summary, highlights, reviews}."""
    ist = initial_state(state)
    if not ist:
        return None
    rating = _rating_block(ist.get("rating")) if isinstance(ist.get("rating"), dict) else None
    summary = ist.get("summary") or {}
    ai_summary = next((_text(c.get("summary_text")) for c in summary.get("components") or [] if c.get("id") == "SUMMARY"), None)
    track = (summary.get("track_data") or {})
    media = []
    for item in (ist.get("carousel") or {}).get("media") or []:
        if item.get("url"):
            media.append({"type": item.get("type") or "photo", "link": item.get("url"), "rating": _int(item.get("rating"))})
    message = ist.get("message") if isinstance(ist.get("message"), dict) else None
    return {
        "object_id": ist.get("object_id"),
        "object_type": ist.get("object_type"),
        "rating": rating,
        "with_comments": _int(ist.get("reviews_with_comment")),
        "ai_summary": {"text": ai_summary, "updated_at": _iso_date(track.get("last_updated"))} if ai_summary else None,
        "qualitative_attributes": [_text(a) for a in ist.get("quali_attributes") or [] if _text(a)] or None,
        "media": media or None,
        "reviews": [r for r in (parse_review(x) for x in ist.get("reviews") or []) if r],
        "message": _text(message.get("title")) if message else None,
    }


# ---- categories -----------------------------------------------------------------------------

def parse_menu(payload):
    """menu/departments -> [{name, categories: [{id, name, link, children}]}]."""
    departments = []
    for department in (payload or {}).get("departments") or []:
        categories = []
        for category in department.get("categories") or []:
            children = [{"id": c.get("id"), "name": c.get("name"), "link": _clean_link(c.get("permalink"))}
                        for c in category.get("children_categories") or [] if c.get("id")]
            categories.append({"id": category.get("id"), "name": category.get("name"),
                               "link": _clean_link(category.get("permalink")), "children": children or None})
        departments.append({"name": department.get("name"), "categories": categories})
    return departments


def menu_links(payload):
    """{category id: listing link} for every menu node that has one."""
    links = {}
    for department in parse_menu(payload):
        for category in department["categories"]:
            if category.get("link"):
                links[category["id"]] = category["link"]
            for child in category.get("children") or []:
                if child.get("link"):
                    links[child["id"]] = child["link"]
    return links


def parse_root_categories(state):
    """The official-stores landing state -> the site's root categories
    [{id, name, official_stores}] (pageProps.categoryList)."""
    props = page_props(state) or {}
    out = []
    for category in props.get("categoryList") or []:
        if not isinstance(category, dict) or not category.get("id"):
            continue
        paging = ((category.get("items") or {}).get("paging")) or {}
        out.append({"id": category["id"], "name": category.get("name"), "official_stores": _int(paging.get("total"))})
    return out


def parse_category_api(payload):
    """api.mercadolibre.com/categories/<id> -> the category record."""
    if not isinstance(payload, dict) or not payload.get("id"):
        return None
    settings = payload.get("settings") or {}
    return {
        "id": payload.get("id"),
        "name": payload.get("name"),
        "link": payload.get("permalink"),
        "image": payload.get("picture"),
        "total_items": _int(payload.get("total_items_in_this_category")),
        "path": [{"id": p.get("id"), "name": p.get("name")} for p in payload.get("path_from_root") or []] or None,
        "children": [{"id": c.get("id"), "name": c.get("name"), "total_items": _int(c.get("total_items_in_this_category"))}
                     for c in payload.get("children_categories") or []] or None,
        "attribute_types": payload.get("attribute_types"),
        "is_adult": settings.get("adult_content") if isinstance(settings.get("adult_content"), bool) else None,
        "listing_allowed": settings.get("listing_allowed") if isinstance(settings.get("listing_allowed"), bool) else None,
        "catalog_domain": payload.get("meta_categ_id") or None,
    }


def parse_category_attributes(payload):
    out = []
    for attribute in payload or []:
        if not isinstance(attribute, dict) or not attribute.get("id"):
            continue
        tags = attribute.get("tags") or {}
        values = [{"id": v.get("id"), "name": v.get("name")} for v in attribute.get("values") or [] if v.get("id")]
        out.append({
            "id": attribute["id"],
            "name": attribute.get("name"),
            "type": attribute.get("value_type"),
            "group": attribute.get("attribute_group_name"),
            "hint": attribute.get("hint"),
            "is_required": bool(tags.get("required")) or None,
            "is_catalog_required": bool(tags.get("catalog_required")) or None,
            "allows_variations": bool(tags.get("allow_variations")) or None,
            "values": values or None,
            "units": [u.get("name") for u in attribute.get("allowed_units") or [] if u.get("name")] or None,
            "default_unit": attribute.get("default_unit"),
        })
    return out


def parse_domain_discovery(payload):
    out = []
    for row in payload or []:
        if isinstance(row, dict):
            out.append({"category_id": row.get("category_id"), "category_name": row.get("category_name"),
                        "domain_id": row.get("domain_id"), "domain_name": row.get("domain_name"),
                        "attributes": [{"id": a.get("id"), "name": a.get("name"), "value_id": a.get("value_id"), "value": a.get("value_name")}
                                       for a in row.get("attributes") or []] or None})
    return out


# ---- best sellers / deals ---------------------------------------------------------------------

def parse_best_sellers(state, site=None):
    ist = initial_state(state)
    if not ist:
        return None
    results = []
    for block in ist.get("results") or []:
        trends = (block or {}).get("trends_categories") or {}
        for card in trends.get("polycards") or []:
            parsed = parse_polycard(card, site, position=len(results) + 1)
            if parsed:
                results.append(parsed)
    sidebar = ist.get("sidebar") or {}
    breadcrumb = None
    filters = None
    for comp in sidebar.get("components") or []:
        if comp.get("type") == "BREADCRUMB":
            breadcrumb = [{"id": n.get("id") or None, "name": n.get("text"), "link": n.get("url")} for n in comp.get("nodes") or []]
        elif comp.get("type") == "AVAILABLE_FILTERS":
            filters = []
            for flt in comp.get("filters") or []:
                filters.append({"id": flt.get("id"), "name": flt.get("name"),
                                "values": [{"id": v.get("id"), "name": v.get("name"), "link": v.get("url"), "results": _int(v.get("results"))}
                                           for v in flt.get("values") or []] or None})
    header = ist.get("header") or {}
    return {
        "site": site or (_site_of(results[0]["id"]) if results else None),
        "title": header.get("title"),
        "description": (ist.get("seo") or {}).get("description"),
        "breadcrumb": breadcrumb or None,
        "filters": filters or None,
        "results": results,
    }


def parse_deals(state, page=1, site=None):
    props = page_props(state) or {}
    data = props.get("data")
    if not isinstance(data, dict):
        return None
    paging = data.get("paging") or {}
    limit = _int(paging.get("limit")) or _int(data.get("limit")) or 25
    # ?page=N lands at offset (N-1) * data.limit (20) while each page carries
    # paging.limit (25) items, so the pages overlap and the page count follows
    # the step, not the page size (verified 2026-10-26: page 25 -> offset 480)
    step = _int(data.get("limit")) or limit
    total = _int(paging.get("total"))
    offset = _int(paging.get("offset")) or 0
    results = []
    if total is None or offset < total:
        for card in data.get("items") or []:
            parsed = parse_polycard(card, site, position=offset + len(results) + 1)
            if parsed:
                results.append(parsed)
    total_pages = math.ceil(total / step) if total and step else None
    filters = []
    for flt in data.get("availableFilters") or []:
        if isinstance(flt, dict):
            filters.append({"id": flt.get("id"), "name": flt.get("name"),
                            "values": [{"id": v.get("id"), "name": v.get("name")} for v in flt.get("values") or []] or None})
    return {
        "site": site or (_site_of(results[0]["id"]) if results else None),
        "category": data.get("category") or None,
        "domain_id": data.get("domain_id") or None,
        "filters": filters or None,
        "results": results,
        "pagination": {"page": page, "items_per_page": limit, "total_pages": total_pages, "total_count": total},
    }


# ---- stores -----------------------------------------------------------------------------------

def parse_store(row):
    if not isinstance(row, dict):
        return None
    pictures = {p.get("name"): p.get("secure_url") or p.get("url") for p in row.get("pictures") or [] if isinstance(p, dict)}
    link = row.get("landing_permalink") or row.get("permalink")
    slug = None
    if link:
        slug = urlparse(link).path.rstrip("/").rsplit("/", 1)[-1] or None
    return {
        "id": row.get("official_store_id"),
        "name": row.get("name"),
        "slug": slug,
        "link": link,
        "logo": pictures.get("high_resolution_logo") or pictures.get("logo") or pictures.get("logo_landing"),
        "background": pictures.get("background"),
        "category_ids": row.get("categories_ids") or None,
        "storefront_id": row.get("storefront_id"),
        "relevance_position": _int(row.get("relevance_position")),
    }


def parse_stores(payload, page=1, limit=100):
    if not isinstance(payload, dict):
        return None
    paging = payload.get("paging") or {}
    total = _int(paging.get("total"))
    results = [s for s in (parse_store(r) for r in payload.get("results") or []) if s]
    return {
        "query": (payload.get("filters") or {}).get("q") or None,
        "results": results,
        "pagination": {"page": page, "items_per_page": limit, "total_pages": math.ceil(total / limit) if total else (1 if results else 0),
                       "total_count": total},
    }


# ---- suggest ------------------------------------------------------------------------------------

def parse_autosuggest(payload):
    out = []
    for row in (payload or {}).get("suggested_queries") or []:
        if not isinstance(row, dict) or not row.get("q"):
            continue
        out.append({"query": row.get("q"), "is_verified_store": bool(row.get("is_verified_store")),
                    "filters": [{"id": f.get("id"), "name": f.get("name"), "value_id": f.get("value_id"), "value": f.get("value_name")}
                                for f in row.get("filters") or [] if isinstance(f, dict)] or None})
    return out
