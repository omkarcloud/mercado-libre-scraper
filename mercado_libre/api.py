"""The /mercado-libre/* endpoint functions (route_glue's route_table calls
them with the schema's loaded kwargs).

Every response caches here (cache.cached_call, keyed on the validated
params). products/details caches ONE parsed page per product reference
(_product_record) and reads it back for the review-summary fallback, so a
client hitting details and reviews on the same product pays one page fetch
plus the small reviews XHR.
"""
import math
import re
from urllib.parse import urlparse

from cache import cached_call
from mercado_libre import cache_config as ttl
from mercado_libre import parsers, refs
from mercado_libre.fetch import (MercadoLibreBadRequest, MercadoLibreNotFound, fetch_autosuggest,
                                 fetch_category_api, fetch_category_attributes, fetch_domain_discovery,
                                 fetch_listing, fetch_menu, fetch_product, fetch_reviews, fetch_reviews_summary,
                                 fetch_stores, fetch_stores_landing, get_page)

REVIEWS_PAGE_SIZE = 30
REVIEWS_MAX_PAGES = 11   # the site's own depth limit per review query (330 reviews)
STORES_PAGE_SIZE = 100


def _filters(data):
    return {k: data.get(k) for k in ("page", "sort", "condition", "price_min", "price_max", "free_shipping")}


def _empty_listing(page, site, query, final_url):
    """A search with no matches is an empty page, not an error."""
    return {"site": site, "query": query, "category": None, "vertical": None, "sort": None,
            "sort_options": None, "applied_filters": None, "available_filters": None, "breadcrumb": None,
            "related_searches": None, "header": None, "results": [],
            "pagination": {"page": page, "items_per_page": refs.PAGE_SIZE, "total_pages": 0, "total_count": 0},
            "link": final_url.replace("?skipWebview=true", "").replace("&skipWebview=true", "")}


def _listing(url, label, page, site, not_found_message, query=None, strip_query=False, empty_ok=False):
    """empty_ok: the site's "no results" shell means zero matches (keyword
    and classifieds searches) rather than an unknown category / store /
    seller, which stay a 404."""
    html, final_url = fetch_listing(url, label)
    state = parsers.extract_state(html)
    if parsers.is_no_results_page(state):
        if empty_ok:
            return _empty_listing(page, site, query, final_url)
        raise MercadoLibreNotFound(not_found_message)
    result = parsers.parse_listing(state, page=page, site=site)
    if result is None:
        raise MercadoLibreNotFound(not_found_message)
    if strip_query:
        result["query"] = query
    result["link"] = final_url.replace("?skipWebview=true", "").replace("&skipWebview=true", "")
    return result


# ---- products/search ---------------------------------------------------------------

def _products_search(query, site, page, sort, condition, price_min, price_max, free_shipping):
    url = refs.search_url(site, query, page=page, sort=sort, condition=condition, price_min=price_min,
                         price_max=price_max, free_shipping=free_shipping)
    return _listing(url, f"search {query!r}", page, site, "no results for this search", query=query, empty_ok=True)


def products_search(**data):
    return cached_call("mercado_libre.search", data, _products_search, ttl.SEARCH_CACHE)


# ---- products/details ----------------------------------------------------------------

def _product_record(product):
    html, final_url, kind = fetch_product(product)
    state = parsers.extract_state(html)
    record = parsers.parse_product(state, page_url=final_url.split("?")[0], site=product["site"])
    if record is None:
        raise MercadoLibreNotFound(f"product {product['id']} not found")
    record["requested"] = {"id": product["id"], "kind": kind}
    return record


def _record(product):
    return cached_call("mercado_libre.product", {"product": product}, _product_record, ttl.PRODUCT_CACHE)


def product_details(product):
    record = dict(_record(product))
    record.pop("requested", None)
    return record


# ---- products/reviews ------------------------------------------------------------------

def _product_reviews(product, page, rating):
    """Reviews belong to the catalog product; an item id only works through
    the isItem flag and then refuses the rating filter, so every reference
    is first resolved through the (cached) product page record: it names
    the catalog product id, whose reviews object carries the summary too."""
    site = product["site"]
    # an unknown product id is the product page's 404; a known product with
    # no reviews is an empty page
    record = _record(product)
    object_id = record.get("product_id") or record.get("id") or product["id"]
    is_item = not record.get("product_id")
    offset = (page - 1) * REVIEWS_PAGE_SIZE
    payload = fetch_reviews(site, object_id, is_item, offset=offset, limit=REVIEWS_PAGE_SIZE, rating=rating)
    reviews, message = parsers.parse_reviews_search(payload)
    summary = None
    if not is_item:
        summary = parsers.parse_reviews_summary(parsers.extract_state(fetch_reviews_summary(site, object_id)))
    rating_block = (summary or {}).get("rating") or record.get("rating")
    # reviews with text: the summary page and the product page each carry it
    # on some products only (top level vs inside the rating block)
    with_comments = ((summary or {}).get("with_comments") or (rating_block or {}).get("with_comments")
                     or (record.get("rating") or {}).get("with_comments"))
    if rating_block is not None and rating_block.get("with_comments") is None and with_comments is not None:
        rating_block = dict(rating_block, with_comments=with_comments)
    ai_summary = (summary or {}).get("ai_summary")
    if ai_summary is None and record.get("reviews_ai_summary"):
        ai_summary = {"text": record["reviews_ai_summary"], "updated_at": None}
    # Mercado Libre serves the first REVIEWS_MAX_PAGES pages of any review
    # query and empty pages after that (checked 2026-10-26: page 11 = 30 rows,
    # page 12 = 0 for a product with 20k+ text reviews), so totals and the
    # next link stop there rather than promising pages that are always empty.
    if rating:
        pagination = {"page": page, "items_per_page": REVIEWS_PAGE_SIZE,
                      "has_next": len(reviews) == REVIEWS_PAGE_SIZE and page < REVIEWS_MAX_PAGES,
                      "total_pages": None, "total_count": None}
    else:
        total = with_comments if with_comments is not None else (rating_block or {}).get("count")
        if total is None and not reviews:
            total = 0
        if total is None:
            pagination = {"page": page, "items_per_page": REVIEWS_PAGE_SIZE,
                          "has_next": len(reviews) == REVIEWS_PAGE_SIZE and page < REVIEWS_MAX_PAGES,
                          "total_pages": None, "total_count": None}
        else:
            reachable = min(total, REVIEWS_PAGE_SIZE * REVIEWS_MAX_PAGES)
            pagination = {"page": page, "items_per_page": REVIEWS_PAGE_SIZE,
                          "total_pages": math.ceil(reachable / REVIEWS_PAGE_SIZE), "total_count": total}
    return {
        "object_id": object_id,
        "site": site,
        "rating": rating_block,
        "with_comments": with_comments,
        "ai_summary": ai_summary,
        "media": (summary or {}).get("media"),
        "filter_rating": rating,
        "results": reviews,
        "pagination": pagination,
    }


def product_reviews(**data):
    return cached_call("mercado_libre.reviews", data, _product_reviews, ttl.REVIEWS_CACHE)


# ---- categories/list ------------------------------------------------------------------

def _menu(site):
    return cached_call("mercado_libre.menu", {"site": site}, lambda site: fetch_menu(site), ttl.CATEGORIES_CACHE)


def _root_categories(site):
    return cached_call("mercado_libre.root_categories", {"site": site},
                       lambda site: parsers.parse_root_categories(parsers.extract_state(fetch_stores_landing(site))),
                       ttl.CATEGORIES_CACHE)


def _categories_list(site, category):
    if category:
        site = refs.site_from_id(category) or site
        record = parsers.parse_category_api(fetch_category_api(category))
        if record is None:
            raise MercadoLibreNotFound(f"category {category} not found")
        links = parsers.menu_links(_menu(site))
        record["link"] = record.get("link") or links.get(category)
        for child in record.get("children") or []:
            child["link"] = links.get(child["id"])
        record["site"] = site
        return record
    # the root list comes from the official-stores landing (the department
    # menu JSON only covers one department); the menu adds links + children
    # where it has them. Children of any root: categories/list?category=<id>.
    menu = parsers.parse_menu(_menu(site))
    menu_by_id = {c["id"]: c for d in menu for c in d["categories"]}
    roots = []
    for root in _root_categories(site):
        entry = dict(root)
        node = menu_by_id.get(root["id"])
        entry["link"] = node.get("link") if node else None
        entry["children"] = node.get("children") if node else None
        roots.append(entry)
    return {"site": site, "count": len(roots), "categories": roots, "departments": menu}


def categories_list(**data):
    return cached_call("mercado_libre.categories", data, _categories_list, ttl.CATEGORIES_CACHE)


# ---- categories/products ---------------------------------------------------------------

def _category_link_lookup(site, category_id):
    """The listing link of a category id. The department menu covers the
    top of the tree; below it the site publishes no id -> path mapping, so
    the category's own name is searched and the result's breadcrumb (whose
    nodes line up with event_data.category_path) yields the listing link."""
    menu = _menu(site)
    link = parsers.menu_links(menu).get(category_id)
    if link and not _is_landing_link(link):
        return link
    if link:
        # a root category's menu link is the www.<domain>/c/<slug> landing
        # page, which renders no results with filters (verified 2026-10-26);
        # its listing path is the parent path of its children's listing links
        for department in parsers.parse_menu(menu):
            for node in department["categories"]:
                if node.get("id") != category_id:
                    continue
                for child in node.get("children") or []:
                    if child.get("link") and not _is_landing_link(child["link"]):
                        return child["link"].rstrip("/").rsplit("/", 1)[0] + "/"
    record = parsers.parse_category_api(fetch_category_api(category_id))
    if record is None:
        raise MercadoLibreNotFound(f"category {category_id} not found")
    name = record.get("name") or ""
    # "Smartwatches y Accesorios" finds nothing as a query; its head noun does
    candidates = []
    for candidate in (name, re.split(r"\s+(?:y|e|and)\s+", name)[0], *(c.strip() for c in name.split(","))):
        candidate = candidate.strip()
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    for query in candidates:
        html, _ = fetch_listing(refs.search_url(site, query), f"category {category_id} lookup")
        ist = parsers.initial_state(parsers.extract_state(html)) or {}
        # the "only in <category>" search filter carries the category's own
        # listing path as "<path>/$query"
        for flt in ist.get("search_filters") or []:
            if flt.get("value") == category_id and flt.get("permalink"):
                return flt["permalink"].replace("$query", "").rstrip("/") + "/"
    return None


def _is_landing_link(link):
    """www.<domain>/c/<slug>: a category landing page, not a listing."""
    return (urlparse(link).hostname or "").lower().startswith("www.")


def _category_link(site, category_id):
    return cached_call("mercado_libre.category_link", {"site": site, "category_id": category_id},
                       _category_link_lookup, ttl.CATEGORIES_CACHE)


def _category_products(category, page, sort, condition, price_min, price_max, free_shipping):
    site = category["site"]
    link = category.get("link")
    if not link:
        link = _category_link(site, category["id"])
        if not link:
            raise MercadoLibreBadRequest(
                f"category {category['id']} has no listing page of its own (the site browses it only through "
                "search); pass a category listing link instead")
    # a bare category path is a product-less landing page on the mobile site;
    # the open price range turns it into the full results list (refs.filter_segments)
    url = refs.listing_page_url(link, page=page, sort=sort, condition=condition, price_min=price_min,
                                price_max=price_max, free_shipping=free_shipping, force_results=True)
    result = _listing(url, f"category {category.get('id') or link}", page, site,
                      "category listing not found", strip_query=True)
    result["requested_category"] = category.get("id")
    return result


def category_products(**data):
    return cached_call("mercado_libre.category_products", data, _category_products, ttl.SEARCH_CACHE)


# ---- categories/best-sellers -------------------------------------------------------------

def _best_sellers(category):
    site = refs.site_from_id(category)
    html, final_url = get_page(refs.best_sellers_link(site, category), f"best sellers {category}")
    result = parsers.parse_best_sellers(parsers.extract_state(html), site=site)
    if result is None or not result.get("results"):
        raise MercadoLibreNotFound(f"no best-seller ranking for category {category}")
    result["category_id"] = category
    result["link"] = refs.best_sellers_link(site, category)
    return result


def best_sellers(**data):
    return cached_call("mercado_libre.best_sellers", data, _best_sellers, ttl.BEST_SELLERS_CACHE)


# ---- categories/discover -------------------------------------------------------------------

def _categories_discover(query, site, limit):
    rows = parsers.parse_domain_discovery(fetch_domain_discovery(site, query, limit))
    links = parsers.menu_links(_menu(site)) if rows else {}
    for row in rows:
        row["link"] = links.get(row.get("category_id"))
    attributes = None
    if rows and rows[0].get("category_id"):
        attributes = parsers.parse_category_attributes(fetch_category_attributes(rows[0]["category_id"]))
    return {"query": query, "site": site, "count": len(rows), "results": rows,
            "top_category_attributes": attributes}


def categories_discover(**data):
    return cached_call("mercado_libre.discover", data, _categories_discover, ttl.DISCOVER_CACHE)


# ---- deals/list ------------------------------------------------------------------------------

def _deals(site, page, category):
    if category:
        site = refs.site_from_id(category) or site
    html, final_url = get_page(refs.deals_link(site, page, category), f"deals {site} page {page}")
    result = parsers.parse_deals(parsers.extract_state(html), page=page, site=site)
    if result is None:
        raise MercadoLibreNotFound("deals page not found")
    result["link"] = refs.deals_link(site, page, category)
    return result


def deals_list(**data):
    return cached_call("mercado_libre.deals", data, _deals, ttl.DEALS_CACHE)


# ---- sellers/products ---------------------------------------------------------------------------

def _seller_products(seller, site, page, sort, condition, price_min, price_max, free_shipping):
    site = seller.get("site") or site
    link = refs.seller_items_link(site, seller["id"])
    url = refs.listing_page_url(link, page=page, sort=sort, condition=condition, price_min=price_min,
                                price_max=price_max, free_shipping=free_shipping)
    result = _listing(url, f"seller {seller['id']}", page, site,
                      f"seller {seller['id']} has no active listings or does not exist", strip_query=True)
    result["seller"] = {"id": seller["id"], "link": link}
    return result


def seller_products(**data):
    return cached_call("mercado_libre.seller_products", data, _seller_products, ttl.SELLER_CACHE)


# ---- stores/search --------------------------------------------------------------------------------

def _stores_search(query, site, page):
    offset = (page - 1) * STORES_PAGE_SIZE
    payload = fetch_stores(site, query=query, offset=offset, limit=STORES_PAGE_SIZE)
    result = parsers.parse_stores(payload, page=page, limit=STORES_PAGE_SIZE)
    if result is None:
        raise MercadoLibreNotFound("store directory unavailable")
    result["site"] = site
    result["query"] = query
    return result


def stores_search(**data):
    return cached_call("mercado_libre.stores", data, _stores_search, ttl.STORES_CACHE)


# ---- stores/products ------------------------------------------------------------------------------

def _store_products(store, site, page, sort, condition, price_min, price_max, free_shipping):
    site = store.get("site") or site
    link = refs.store_link(site, store["slug"])
    url = refs.store_listing_url(site, store["slug"], page=page, sort=sort, condition=condition, price_min=price_min,
                                 price_max=price_max, free_shipping=free_shipping)
    result = _listing(url, f"store {store['slug']}", page, site,
                      f"official store {store['slug']!r} not found", strip_query=True)
    header = result.pop("header", None) or {}
    result["store"] = {"slug": store["slug"], "name": header.get("title"), "subtitle": header.get("subtitle"),
                       "logo": header.get("logo"), "link": header.get("link") or link}
    return result


def store_products(**data):
    return cached_call("mercado_libre.store_products", data, _store_products, ttl.STORE_CACHE)


# ---- search/suggest ---------------------------------------------------------------------------------

def _suggest(query, site, limit):
    rows = parsers.parse_autosuggest(fetch_autosuggest(site, query, limit))[:limit]
    return {"query": query, "site": site, "count": len(rows), "results": rows}


def search_suggest(**data):
    return cached_call("mercado_libre.suggest", data, _suggest, ttl.SUGGEST_CACHE)


# ---- classifieds/search ---------------------------------------------------------------------------------

def _classifieds_search(listing, page, sort, price_min, price_max):
    url = refs.listing_page_url(listing["link"], page=page, sort=sort, price_min=price_min, price_max=price_max)
    result = _listing(url, f"classifieds {listing['link']}", page, listing["site"],
                      "no listings at this link", strip_query=True, empty_ok=True)
    result["requested_link"] = listing["link"]
    return result


def classifieds_search(**data):
    return cached_call("mercado_libre.classifieds", data, _classifieds_search, ttl.CLASSIFIEDS_CACHE)


# ---- classifieds/details ----------------------------------------------------------------------------------

def _classified_details(listing):
    site = listing["site"]
    html, final_url = get_page(refs.item_link(site, listing["id"]), f"listing {listing['id']}")
    state = parsers.extract_state(html)
    record = parsers.parse_classified(state, page_url=final_url.split("?")[0], site=site)
    if record is None:
        raise MercadoLibreNotFound(f"listing {listing['id']} not found")
    if record.get("vertical") in (None, "core", "CORE"):
        # a core marketplace item landed here: serve it as a product record
        product = parsers.parse_product(state, page_url=final_url.split("?")[0], site=site)
        if product:
            return product
    return record


def classified_details(**data):
    return cached_call("mercado_libre.classified", data, _classified_details, ttl.CLASSIFIEDS_CACHE)
