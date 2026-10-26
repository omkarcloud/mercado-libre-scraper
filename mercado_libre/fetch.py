"""Mercado Libre transport: plain curl_cffi with browser-impersonated TLS,
no browser, no cookies kept. Egress: one sticky exit per thread session
(config.mercado_libre_proxy(), knob MERCADO_LIBRE_EXIT); a retryable
failure drops the session so the retry rides a fresh exit.

Why the pages are open to curl at all (research 2026-10-23/24): with a
desktop browser user agent every core page is behind three walls — a
JavaScript proof-of-work interstitial ("bot-interceptor-muralla"), then a
reCAPTCHA Enterprise wall, and a login wall for flagged exits. The site's
own native-app webview is exempt: the Mercado Libre Android app user agent
plus the query flag `skipWebview=true` makes the server render the full
MOBILE page with its state inlined as `_n.ctx.r={...}` (nordic framework),
on every surface, from every exit tried (AR/US/BR/MX residential, the
datacenter account, even a home IP), with no challenge. Without the flag
the app UA gets a 72 KB client-side webview shell. Server redirects
(category paths, articulo.<domain>/<item> -> /p/<product>, …) DROP the
flag, so a redirect is followed and the final URL re-requested with it.

Upstream surfaces (mercado_libre/refs.py builds the URLs):

  * SEARCH / CATEGORY / SELLER / STORE / CLASSIFIEDS LISTINGS
        GET listado.<domain>/<query><filters>?skipWebview=true  (lista. on MLB;
        inmuebles./autos. verticals; tienda.<domain>/<slug>; _CustId_<id>)
        -> initialState.results[] polycards, 50 per page, pagination
  * PRODUCT   GET <domain>/p/<id> | articulo.<domain>/<ID>-_JM | /up/<id>
        -> initialState.components (VPP / VIP). Unknown ids answer HTTP 404.
        A bare MLA… id is a catalog product OR an item: the product URL is
        tried first, the item URL on its 404.
  * REVIEWS   GET <domain>/noindex/catalog/reviews/<id>/search?... JSON
        (offset / limit / rating; an item id resolves to its catalog
        product) and the summary page …/reviews/<id>?…&modal=true
  * BEST SELLERS  GET <domain>/mas-vendidos/<category>  (404 for unknown)
  * DEALS         GET <domain>/ofertas?page=N&category=…
  * CATEGORIES    GET <domain>/menu/departments (JSON tree, no UA trick
        needed) and api.mercadolibre.com/categories/<id>[/attributes],
        sites/<site>/domain_discovery/search — the only api.mercadolibre.com
        paths still open without an OAuth token
  * STORES        GET <domain>/tiendas-oficiales/api/sites/<site>/brands/search
  * SUGGEST       GET http2.mlstatic.com/resources/sites/<site>/autosuggest —
        a CDN that refuses the pod's own IP and the datacenter exits on the
        MLA path with a bare 403, so it rides its own lane: a residential
        exit in the site's country (config.mercado_libre_suggest_proxy)

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  MercadoLibreUpstreamError  transport failure / 5xx / webview shell  — retryable
  MercadoLibreBlocked        403 / 429 / muralla / captcha / login wall — retryable
  MercadoLibreBadRequest     upstream 400                               — never retried
  MercadoLibreNotFound       404 / unknown id / "no results" shells     — never retried
"""
import os
import re
import sys
import threading
import time
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from mercado_libre import refs

IMPERSONATE = "chrome"
PAGE_TIMEOUT = 40      # listing pages are 1–3 MB
JSON_TIMEOUT = 20
MAX_REDIRECT_HOPS = 4

# The site's native app webview identity (research 2026-10-24): exempt from
# the muralla / captcha / login walls on every surface.
APP_USER_AGENT = "MercadoLibre-Android/10.300.1 (Linux; U; Android 13; Pixel 7 Build/TQ3A)"
SKIP_WEBVIEW = "skipWebview=true"

PAGE_HEADERS = {
    "accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "accept-language": "es-AR,es;q=0.9,pt-BR;q=0.8,en;q=0.7",
    "user-agent": APP_USER_AGENT,
}
JSON_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "es-AR,es;q=0.9,pt-BR;q=0.8,en;q=0.7",
}

_TITLE_RE = re.compile(r"<title>([^<]*)</title>", re.I)
_CHALLENGE_MARKERS = ("bot-interceptor-muralla", "gz-account-verification", "captcha-wall-index")
_ERROR_PAGE_MARKERS = ("Hubo un error accediendo a esta pagina",)


class MercadoLibreUpstreamError(UpstreamError):
    """Transport failure, 5xx or an unrendered webview shell — retryable."""


class MercadoLibreBlocked(MercadoLibreUpstreamError, Blocked):
    """403 / 429 or one of the site's challenge walls — retryable on a fresh exit."""


class MercadoLibreBadRequest(BadRequest):
    """Upstream 400 — never retried."""


class MercadoLibreNotFound(NotFound):
    """Product / listing / category / store does not exist — never retried."""


# One session per cheroot worker thread and egress lane: a curl handle must
# not be shared across threads; these GETs are stateless (no cookies are
# needed), so thread-lifetime sessions with keep-alive are enough. Lane
# "main" rides config.mercado_libre_proxy(); lane "suggest:<site>" rides
# config.mercado_libre_suggest_proxy(<site>) (the autosuggest CDN refuses
# the pod's own IP on some sites, see config's Mercado Libre block).
_local = threading.local()
MAIN_LANE = "main"


def _proxy_for(lane):
    if lane.startswith("suggest:"):
        return config.mercado_libre_suggest_proxy(lane.split(":", 1)[1])
    return config.mercado_libre_proxy()


def _session(lane=MAIN_LANE):
    sessions = getattr(_local, "sessions", None)
    if sessions is None:
        sessions = _local.sessions = {}
    sess = sessions.get(lane)
    if sess is None:
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        proxy = _proxy_for(lane)
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        sessions[lane] = sess
    return sess


def _drop_session(lane=MAIN_LANE):
    """Close the thread's session on that lane so the retry rides a fresh exit."""
    sessions = getattr(_local, "sessions", None) or {}
    sess = sessions.pop(lane, None)
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def _retrying(fn, lane=MAIN_LANE):
    """Run fn() under the shared retry policy (retryable errors only;
    NotFound / BadRequest surface immediately)."""
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except MercadoLibreUpstreamError as e:
            last = e
            _drop_session(lane)
            if attempt < config.MAX_RETRIES:
                time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


def _page_title(text):
    match = _TITLE_RE.search(text or "")
    return match.group(1).strip() if match else ""


def _classify(resp, label):
    """Map an HTTP response to the error taxonomy; return the body text."""
    if resp.status_code == 404:
        raise MercadoLibreNotFound(f"{label} not found")
    if resp.status_code == 400:
        raise MercadoLibreBadRequest(resp.text[:200])
    if resp.status_code in (401, 403, 429):
        raise MercadoLibreBlocked(f"HTTP {resp.status_code} for {label}")
    if resp.status_code != 200:
        raise MercadoLibreUpstreamError(f"HTTP {resp.status_code} for {label}")
    return resp.text


def _with_skip_webview(url):
    if SKIP_WEBVIEW in url:
        return url
    return url + ("&" if "?" in url else "?") + SKIP_WEBVIEW


def _check_walls(text, final_url, label):
    low_url = final_url or ""
    if "/gz/account-verification" in low_url or "/captcha/wall" in low_url:
        raise MercadoLibreBlocked(f"challenge wall for {label}")
    head = text[:60000]
    if any(marker in head for marker in _CHALLENGE_MARKERS):
        raise MercadoLibreBlocked(f"challenge page for {label}")
    if any(marker in head for marker in _ERROR_PAGE_MARKERS):
        raise MercadoLibreBlocked(f"error page for {label}")


def get_page(url, label):
    """GET a site page as the app webview with skipWebview=true, following
    the server's own redirects and re-appending the flag they drop.
    Returns (html, final_url)."""
    def once():
        target = _with_skip_webview(url)
        for _ in range(MAX_REDIRECT_HOPS):
            try:
                resp = _session().get(target, headers=PAGE_HEADERS, timeout=PAGE_TIMEOUT,
                                      allow_redirects=True)
            except Exception as e:
                raise MercadoLibreUpstreamError(f"request failed: {type(e).__name__}: {e}")
            text = _classify(resp, label)
            final_url = str(resp.url)
            _check_walls(text, final_url, label)
            if SKIP_WEBVIEW in final_url:
                if "_n.ctx.r=" not in text:
                    raise MercadoLibreUpstreamError(f"no page state rendered for {label}")
                return text, final_url
            target = _with_skip_webview(final_url)
        raise MercadoLibreUpstreamError(f"redirect loop for {label}")
    return _retrying(once)


def get_json(url, label, headers=None, lane=MAIN_LANE):
    """GET a JSON surface; returns the decoded payload."""
    def once():
        try:
            resp = _session(lane).get(url, headers=headers or JSON_HEADERS, timeout=JSON_TIMEOUT)
        except Exception as e:
            raise MercadoLibreUpstreamError(f"request failed: {type(e).__name__}: {e}")
        text = _classify(resp, label)
        try:
            return resp.json()
        except Exception:
            raise MercadoLibreBlocked(f"non-JSON response for {label}: {text[:120]}")
    return _retrying(once, lane)


# ---- listings ----------------------------------------------------------------

def fetch_listing(url, label):
    """A search / category / seller / store / classifieds listing page."""
    return get_page(url, label)


# ---- products ---------------------------------------------------------------

def fetch_product(ref):
    """The product / item / user-product page for a resolved reference
    (refs.resolve_product). A bare id is tried as a catalog product first,
    then as an item (each shape 404s for the other kind). Returns
    (html, final_url, kind)."""
    site, ident, kind = ref["site"], ref["id"], ref["kind"]
    if kind == "user_product":
        html, final = get_page(refs.user_product_link(site, ident), f"product {ident}")
        return html, final, kind
    if kind == "item":
        html, final = get_page(refs.item_link(site, ident), f"item {ident}")
        return html, final, kind
    try:
        html, final = get_page(refs.product_link(site, ident), f"product {ident}")
        return html, final, "product"
    except MercadoLibreNotFound:
        if kind == "product":
            raise
    html, final = get_page(refs.item_link(site, ident), f"item {ident}")
    return html, final, "item"


# ---- reviews ----------------------------------------------------------------

def _reviews_base(site, object_id):
    return f"{refs.site_info(site)['home']}/noindex/catalog/reviews/{object_id}"


def fetch_reviews(site, object_id, is_item, offset=0, limit=30, rating=None):
    """The reviews-modal search XHR: {"reviews": [...]} (a message object
    instead when the product has none)."""
    params = (f"objectId={object_id}&siteId={site}&isItem={'true' if is_item else 'false'}"
              f"&offset={offset}&limit={limit}&x-is-webview=false&source_platform=%2Fweb%2Fdesktop")
    if rating:
        params += f"&rating={rating}"
    headers = dict(JSON_HEADERS, referer=f"{_reviews_base(site, object_id)}?noIndex=true&access=view_all&modal=true")
    payload = get_json(f"{_reviews_base(site, object_id)}/search?{params}", f"reviews {object_id}", headers)
    if not isinstance(payload, dict):
        raise MercadoLibreUpstreamError("unexpected reviews payload shape")
    return payload


def fetch_reviews_summary(site, object_id):
    """The reviews modal page: rating summary, star distribution, AI summary
    and the first 15 reviews."""
    url = f"{_reviews_base(site, object_id)}?noIndex=true&access=view_all&modal=true&controlled=true"
    html, _ = get_page(url, f"reviews {object_id}")
    return html


# ---- categories ---------------------------------------------------------------

def fetch_menu(site):
    """The department menu JSON: departments -> categories -> children."""
    return get_json(f"{refs.site_info(site)['home']}/menu/departments", f"menu {site}")


def fetch_stores_landing(site):
    """The official-stores landing page: its state lists the site's root
    categories (26 on MLA) — the department menu JSON only covers one
    department, and sites/<site>/categories needs an OAuth token."""
    info = refs.site_info(site)
    html, _ = get_page(f"{info['home']}/{info['stores_path']}", f"stores landing {site}")
    return html


def fetch_category_api(category_id):
    """api.mercadolibre.com/categories/<id> (open without a token)."""
    return get_json(f"{refs.API_HOST}/categories/{category_id}", f"category {category_id}")


def fetch_category_attributes(category_id):
    return get_json(f"{refs.API_HOST}/categories/{category_id}/attributes", f"category {category_id} attributes")


def fetch_domain_discovery(site, query, limit):
    url = f"{refs.API_HOST}/sites/{site}/domain_discovery/search?q={quote(query)}&limit={limit}"
    return get_json(url, f"category discovery {query!r}")


# ---- stores -------------------------------------------------------------------

def fetch_stores(site, query=None, offset=0, limit=100):
    """The official-stores directory JSON (brands search)."""
    info = refs.site_info(site)
    url = f"{info['home']}/{info['stores_path']}/api/sites/{site}/brands/search?status=active&offset={offset}&limit={limit}"
    if query:
        url += f"&q={quote(query)}&platformId=ML"
    headers = dict(JSON_HEADERS, referer=f"{info['home']}/{info['stores_path']}")
    return get_json(url, f"stores {site}", headers)


# ---- suggest -------------------------------------------------------------------

def fetch_autosuggest(site, query, limit):
    """The search-box suggestions JSON. Rides its own egress lane: the CDN
    answers a bare 403 to the pod's own IP and the datacenter exits on the
    MLA path while in-country residential exits pass (pod probe 2026-10-26)."""
    url = (f"{refs.STATIC_HOST}/resources/sites/{site}/autosuggest?showFilters=true"
           f"&limit={limit}&api_version=2&q={quote(query)}")
    return get_json(url, f"suggest {query!r}", dict(JSON_HEADERS, referer=refs.site_info(site)["home"] + "/"),
                    lane=f"suggest:{site}")
