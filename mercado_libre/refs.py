"""Reference resolvers + the per-site domain table for /mercado-libre/*.

ONE param per input (tripadvisor QueryOrIdField convention): every id param
also accepts the Mercado Libre link of the same record. Resolvers raise
ValueError with a user-facing message (RefField turns it into a 400) and
return plain dicts the api layer consumes.

Identifier shapes (captured 2026-10-24):
  * site id          3 letters: MLA (Argentina), MLB (Brazil), MLM (Mexico)…
                     every other id starts with its site id
  * item             MLA1918268342 — one seller's listing; link form
                     articulo.<domain>/MLA-1918268342-_JM (produto. on MLB)
  * catalog product  MLA39328824 — the shared product page that groups the
                     sellers' items; link form <domain>/<slug>/p/MLA39328824
                     or /p/MLA39328824. Same prefix + digits as an item, so
                     a bare id is tried as a product first, then as an item.
  * user product     MLAU3735180826 — a seller's own product page, /up/<id>
  * seller           numeric user id; link forms listado…/_CustId_<id>,
                     ?seller_id=<id>. Nicknames (/perfil/<nick>) have no
                     public listing page any more, so they are rejected.
  * official store   slug; link forms tienda.<domain>/<slug>,
                     <domain>/tienda/<slug> (loja on MLB)
  * category         MLA1055; listing link listado.<domain>/<path>/ (lista.
                     on MLB) or a classifieds vertical link
"""
import re
from urllib.parse import urlparse

# site id -> (ISO country, registrable domain, search host label, item host
# label, store host label, official-stores path, currency)
SITES = {
    "MLA": ("AR", "mercadolibre.com.ar", "listado", "articulo", "tienda", "tiendas-oficiales", "ARS"),
    "MLB": ("BR", "mercadolivre.com.br", "lista", "produto", "loja", "lojas-oficiais", "BRL"),
    "MLM": ("MX", "mercadolibre.com.mx", "listado", "articulo", "tienda", "tiendas-oficiales", "MXN"),
    "MLC": ("CL", "mercadolibre.cl", "listado", "articulo", "tienda", "tiendas-oficiales", "CLP"),
    "MCO": ("CO", "mercadolibre.com.co", "listado", "articulo", "tienda", "tiendas-oficiales", "COP"),
    "MPE": ("PE", "mercadolibre.com.pe", "listado", "articulo", "tienda", "tiendas-oficiales", "PEN"),
    "MLU": ("UY", "mercadolibre.com.uy", "listado", "articulo", "tienda", "tiendas-oficiales", "UYU"),
    "MEC": ("EC", "mercadolibre.com.ec", "listado", "articulo", "tienda", "tiendas-oficiales", "USD"),
    "MLV": ("VE", "mercadolibre.com.ve", "listado", "articulo", "tienda", "tiendas-oficiales", "VES"),
    "MBO": ("BO", "mercadolibre.com.bo", "listado", "articulo", "tienda", "tiendas-oficiales", "BOB"),
    "MPY": ("PY", "mercadolibre.com.py", "listado", "articulo", "tienda", "tiendas-oficiales", "PYG"),
    "MGT": ("GT", "mercadolibre.com.gt", "listado", "articulo", "tienda", "tiendas-oficiales", "GTQ"),
    "MHN": ("HN", "mercadolibre.com.hn", "listado", "articulo", "tienda", "tiendas-oficiales", "HNL"),
    "MNI": ("NI", "mercadolibre.com.ni", "listado", "articulo", "tienda", "tiendas-oficiales", "NIO"),
    "MSV": ("SV", "mercadolibre.com.sv", "listado", "articulo", "tienda", "tiendas-oficiales", "USD"),
    "MCR": ("CR", "mercadolibre.co.cr", "listado", "articulo", "tienda", "tiendas-oficiales", "CRC"),
    "MPA": ("PA", "mercadolibre.com.pa", "listado", "articulo", "tienda", "tiendas-oficiales", "USD"),
    "MRD": ("DO", "mercadolibre.com.do", "listado", "articulo", "tienda", "tiendas-oficiales", "DOP"),
}
SITE_IDS = tuple(SITES)
DEFAULT_SITE = "MLA"
_COUNTRY_TO_SITE = {v[0]: k for k, v in SITES.items()}
_DOMAIN_TO_SITE = {v[1]: k for k, v in SITES.items()}

API_HOST = "https://api.mercadolibre.com"
STATIC_HOST = "https://http2.mlstatic.com"

ID_RE = re.compile(r"^(ML[A-Z]|M[A-Z]{2})(\d{6,15})$", re.I)
USER_PRODUCT_RE = re.compile(r"^(ML[A-Z]|M[A-Z]{2})U(\d{6,15})$", re.I)
DASHED_ITEM_RE = re.compile(r"^(ML[A-Z]|M[A-Z]{2})-(\d{6,15})$", re.I)
CATEGORY_RE = re.compile(r"^(ML[A-Z]|M[A-Z]{2})(\d{1,9})$", re.I)
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-_.]{0,100}$", re.I)

_LINK_PRODUCT_RE = re.compile(r"/p/((?:ML[A-Z]|M[A-Z]{2})\d{6,15})(?:[/?#]|$)", re.I)
_LINK_PRODUCTS_RE = re.compile(r"/products/((?:ML[A-Z]|M[A-Z]{2})\d{6,15})(?:[/?#]|$)", re.I)
_LINK_USER_PRODUCT_RE = re.compile(r"/up/((?:ML[A-Z]|M[A-Z]{2})U\d{6,15})(?:[/?#]|$)", re.I)
_LINK_ITEM_RE = re.compile(r"/((?:ML[A-Z]|M[A-Z]{2})-\d{6,15})(?:-|/|\?|#|$)", re.I)
_LINK_ITEM_PARAM_RE = re.compile(r"[?&](?:item_id|wid)=((?:ML[A-Z]|M[A-Z]{2})\d{6,15})", re.I)
_LINK_CUSTID_RE = re.compile(r"_CustId_(\d{3,15})", re.I)
_LINK_SELLER_PARAM_RE = re.compile(r"[?&]seller_id=(\d{3,15})", re.I)
_LINK_STORE_PATH_RE = re.compile(r"/(?:tienda|loja)/([a-z0-9][a-z0-9\-_.]{0,100})", re.I)
_LINK_BEST_SELLERS_RE = re.compile(r"/mas-vendidos/((?:ML[A-Z]|M[A-Z]{2})\d{1,9})", re.I)
_LINK_CATEGORY_PARAM_RE = re.compile(r"[?&](?:category|category_id)=((?:ML[A-Z]|M[A-Z]{2})\d{1,9})", re.I)


# ---- sites -----------------------------------------------------------------------

def site_info(site):
    country, domain, search, item, store, stores_path, currency = SITES[site]
    return {"id": site, "country": country, "domain": domain, "search_host": f"{search}.{domain}",
            "item_host": f"{item}.{domain}", "store_host": f"{store}.{domain}",
            "stores_path": stores_path, "currency": currency, "home": f"https://www.{domain}"}


def resolve_site(value):
    """A site id (MLA) or an ISO country code (AR) -> the site id."""
    value = (value or "").strip().upper()
    if value in SITES:
        return value
    if value in _COUNTRY_TO_SITE:
        return _COUNTRY_TO_SITE[value]
    raise ValueError("Must be a Mercado Libre site id (MLA, MLB, MLM, MLC, MCO, MPE, MLU, "
                     "MEC, MLV, ...) or its country code (AR, BR, MX, ...).")


def site_from_id(value):
    """The site id encoded in an item / product / category id, or None."""
    prefix = (value or "")[:3].upper()
    return prefix if prefix in SITES else None


def site_from_host(host):
    """The site id for a mercadolibre.* / mercadolivre.* hostname, or None."""
    host = (host or "").lower()
    for domain, site in _DOMAIN_TO_SITE.items():
        if host == domain or host.endswith("." + domain):
            return site
    return None


def _as_url(value):
    if value.startswith("//"):
        return "https:" + value
    return value


def _is_link(value):
    return value.startswith(("http://", "https://", "//"))


def _site_link(value):
    """Parse a link and insist it is a Mercado Libre one -> (url, site)."""
    url = _as_url(value)
    site = site_from_host(urlparse(url).hostname)
    if not site:
        raise ValueError("Must be a mercadolibre.* / mercadolivre.com.br link.")
    return url, site


# ---- products / items --------------------------------------------------------

def resolve_product(value):
    """Bare id or product link -> {"id", "kind", "site"}; kind is "product"
    (catalog page), "item", "user_product" or "unknown" (a bare MLA… id, which
    is a product or an item: fetch tries the product page first)."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Must not be empty.")
    if _is_link(value):
        url, site = _site_link(value)
        for regex, kind in ((_LINK_USER_PRODUCT_RE, "user_product"), (_LINK_PRODUCT_RE, "product"),
                            (_LINK_PRODUCTS_RE, "product")):
            match = regex.search(url)
            if match:
                ident = match.group(1).upper()
                return {"id": ident, "kind": kind, "site": site_from_id(ident) or site}
        match = _LINK_ITEM_RE.search(urlparse(url).path)
        if match:
            ident = match.group(1).upper().replace("-", "")
            return {"id": ident, "kind": "item", "site": site_from_id(ident) or site}
        match = _LINK_ITEM_PARAM_RE.search(url)
        if match:
            ident = match.group(1).upper()
            return {"id": ident, "kind": "item", "site": site_from_id(ident) or site}
        raise ValueError("Must be a Mercado Libre product link (…/p/MLA39328824, "
                         "articulo.mercadolibre.com.ar/MLA-1918268342-_JM or …/up/MLAU…).")
    candidate = value.upper()
    if USER_PRODUCT_RE.match(candidate) and site_from_id(candidate):
        return {"id": candidate, "kind": "user_product", "site": site_from_id(candidate)}
    match = DASHED_ITEM_RE.match(candidate)
    if match and site_from_id(candidate):
        ident = match.group(1) + match.group(2)
        return {"id": ident, "kind": "item", "site": site_from_id(ident)}
    if ID_RE.match(candidate) and site_from_id(candidate):
        return {"id": candidate, "kind": "unknown", "site": site_from_id(candidate)}
    raise ValueError("Must be a Mercado Libre item or product id (MLA1918268342, MLA39328824, "
                     "MLAU3735180826) or the product link.")


def item_link(site, item_id):
    info = site_info(site)
    return f"https://{info['item_host']}/{item_id[:3]}-{item_id[3:]}-_JM"


def product_link(site, product_id):
    return f"{site_info(site)['home']}/p/{product_id}"


def user_product_link(site, user_product_id):
    return f"{site_info(site)['home']}/up/{user_product_id}"


# ---- sellers / stores ---------------------------------------------------------

def resolve_seller(value):
    """Numeric seller id or a seller listing link -> {"id", "site" | None}."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Must not be empty.")
    if value.isdigit():
        return {"id": int(value), "site": None}
    if _is_link(value):
        url, site = _site_link(value)
        match = _LINK_CUSTID_RE.search(url) or _LINK_SELLER_PARAM_RE.search(url)
        if match:
            return {"id": int(match.group(1)), "site": site}
        raise ValueError("Must be a seller listing link (listado.mercadolibre.com.ar/_CustId_71229887); "
                         "profile links by nickname have no public listing page.")
    raise ValueError("Must be a numeric seller id (71229887) or a _CustId_ listing link.")


def seller_items_link(site, seller_id):
    return f"https://{site_info(site)['search_host']}/_CustId_{seller_id}"


def resolve_store(value):
    """Official store slug or store link -> {"slug", "site" | None}."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Must not be empty.")
    if _is_link(value):
        url, site = _site_link(value)
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        match = _LINK_STORE_PATH_RE.search(parsed.path)
        if match:
            return {"slug": match.group(1).lower(), "site": site}
        if host.startswith(("tienda.", "loja.")):
            slug = parsed.path.strip("/").split("/")[0]
            if slug and SLUG_RE.match(slug):
                return {"slug": slug.lower(), "site": site}
        raise ValueError("Must be an official store link (tienda.mercadolibre.com.ar/samsung "
                         "or https://www.mercadolibre.com.ar/tienda/samsung).")
    if SLUG_RE.match(value):
        return {"slug": value.lower(), "site": None}
    raise ValueError("Must be an official store slug (samsung) or the store link.")


def store_link(site, slug):
    return f"https://{site_info(site)['store_host']}/{slug}"


def store_listing_url(site, slug, **filters):
    """The store's listing with filters. tienda.<domain>/<slug><filters> is
    read as another store's slug (empty page, verified 2026-10-26); filtered
    store pages are a search segment on the search host,
    listado.<domain>/_Tienda_<slug>_Desde_51… (_Loja_ on MLB). Without
    filters the plain store link (its header carries the store's name)."""
    segments = filter_segments(**filters)
    if not segments:
        return store_link(site, slug)
    info = site_info(site)
    return f"https://{info['search_host']}/_{SITES[site][4].capitalize()}_{slug}{segments}"


# ---- categories ---------------------------------------------------------------

def resolve_category_id(value):
    """A category id (MLA1055) or a best-sellers / deals link carrying one -> id."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Must not be empty.")
    if _is_link(value):
        url, _ = _site_link(value)
        match = _LINK_BEST_SELLERS_RE.search(url) or _LINK_CATEGORY_PARAM_RE.search(url)
        if match:
            return match.group(1).upper()
        raise ValueError("Must be a category id (MLA1055) or a link carrying one "
                         "(…/mas-vendidos/MLA1055, …/ofertas?category=MLA1055).")
    candidate = value.upper()
    if CATEGORY_RE.match(candidate) and site_from_id(candidate):
        return candidate
    raise ValueError("Must be a Mercado Libre category id (MLA1055).")


def resolve_category(value):
    """Category id OR a category listing link -> {"id" | None, "link" | None, "site"}.
    A bare id is browsed through the site's own category links (the
    department menu), so ids outside the menu need the listing link."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Must not be empty.")
    if _is_link(value):
        url, site = _site_link(value)
        match = _LINK_CATEGORY_PARAM_RE.search(url) or _LINK_BEST_SELLERS_RE.search(url)
        if match:
            ident = match.group(1).upper()
            return {"id": ident, "link": None, "site": site_from_id(ident) or site}
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = parsed.path.strip("/")
        if not path or host.startswith("www.") or "/p/" in parsed.path:
            raise ValueError("Must be a category listing link "
                             "(listado.mercadolibre.com.ar/celulares-telefonos/celulares-smartphones/).")
        return {"id": None, "link": f"https://{host}/{path}" + ("" if _has_filters(path) else "/"), "site": site}
    candidate = value.upper()
    if CATEGORY_RE.match(candidate) and site_from_id(candidate):
        return {"id": candidate, "link": None, "site": site_from_id(candidate)}
    raise ValueError("Must be a category id (MLA1055) or a category listing link.")


# ---- classifieds ---------------------------------------------------------------

def resolve_listing_link(value):
    """A real-estate / vehicle / service listing link -> {"link", "site"}."""
    value = (value or "").strip()
    if not _is_link(value):
        raise ValueError("Must be a Mercado Libre classifieds listing link "
                         "(inmuebles.mercadolibre.com.ar/departamentos/venta/capital-federal/, "
                         "autos.mercadolibre.com.ar/toyota/corolla/).")
    url, site = _site_link(value)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host.startswith("www.") or _LINK_ITEM_RE.search(parsed.path) or "/p/" in parsed.path:
        raise ValueError("Must be a classifieds listing (search) link, not a single listing.")
    path = parsed.path.strip("/")
    return {"link": f"https://{host}/{path}" + ("/" if path and not _has_filters(path) else ""), "site": site}


def _has_filters(path):
    """Listing paths end with filter segments (_Desde_51_NoIndex_True) rather
    than the trailing slash of a plain vertical path."""
    return "_" in path.rsplit("/", 1)[-1]


def resolve_classified(value):
    """A classified listing id (MLA4117637236) or its link -> {"id", "site"}."""
    ref = resolve_product(value)
    if ref["kind"] in ("product", "user_product"):
        raise ValueError("Must be a classified listing id (MLA4117637236) or its link "
                         "(departamento.mercadolibre.com.ar/MLA-4117637236-…-_JM).")
    return {"id": ref["id"], "site": ref["site"]}


# ---- search URL grammar --------------------------------------------------------

SORT_SEGMENTS = {"relevance": None, "price_asc": "_OrderId_PRICE", "price_desc": "_OrderId_PRICE*DESC"}
CONDITION_SEGMENTS = {"new": "_ITEM*CONDITION_2230284", "used": "_ITEM*CONDITION_2230581"}
PAGE_SIZE = 50   # the mobile render's own page size (event_data.limit)


def filter_segments(page=1, sort=None, condition=None, price_min=None, price_max=None,
                    free_shipping=None, page_size=PAGE_SIZE, force_results=False):
    """The site's own URL filter grammar, appended to a query / listing path:
    _Desde_<offset+1> _OrderId_PRICE _ITEM*CONDITION_<id> _PriceRange_<a>-<b>
    _CostoEnvio_Gratis, closed by _NoIndex_True whenever any segment is set.

    force_results: a bare category path renders a product-less landing page
    on the mobile site; any applied filter turns it into the results list,
    and the open price range _PriceRange_0-0 ("*-*") is the one that keeps
    every item (verified 2026-10-24: 26514 results for MLA1055 either way)."""
    segments = []
    if page and page > 1:
        segments.append(f"_Desde_{(page - 1) * page_size + 1}")
    if sort and SORT_SEGMENTS.get(sort):
        segments.append(SORT_SEGMENTS[sort])
    if condition and CONDITION_SEGMENTS.get(condition):
        segments.append(CONDITION_SEGMENTS[condition])
    if price_min is not None or price_max is not None:
        lo = _price_token(price_min) if price_min is not None else "0"
        hi = _price_token(price_max) if price_max is not None else "0"
        segments.append(f"_PriceRange_{lo}-{hi}")
    elif force_results:
        segments.append("_PriceRange_0-0")
    if free_shipping:
        segments.append("_CostoEnvio_Gratis")
    if segments:
        segments.append("_NoIndex_True")
    return "".join(segments)


def _price_token(value):
    return str(int(value)) if float(value).is_integer() else str(value)


def search_url(site, query, **filters):
    """listado.<domain>/<query><filters>; the query is slugified the way the
    site's own search box does (spaces -> dashes)."""
    slug = "-".join(query.strip().split())
    return f"https://{site_info(site)['search_host']}/{slug}{filter_segments(**filters)}"


def listing_page_url(link, **filters):
    """A category / seller / store / classifieds listing link plus filters."""
    segments = filter_segments(**filters)
    if not segments:
        return link
    base = link[:-1] if link.endswith("/") else link
    if link.endswith("/"):
        return f"{base}/{segments}"
    return f"{base}{segments}"


def best_sellers_link(site, category_id=None):
    home = site_info(site)["home"]
    return f"{home}/mas-vendidos/{category_id}" if category_id else f"{home}/mas-vendidos"


def deals_link(site, page=1, category_id=None):
    url = f"{site_info(site)['home']}/ofertas"
    params = []
    if page and page > 1:
        params.append(f"page={page}")
    if category_id:
        params.append(f"category={category_id}")
    return url + ("?" + "&".join(params) if params else "")
