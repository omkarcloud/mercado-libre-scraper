"""The 14 Mercado Libre endpoints. Every path is served with and without the
`/mercado-libre` prefix, so code generated against the hosted API on RapidAPI
(paths like /products/details) runs unchanged against this server."""
import json
from urllib.parse import urlencode

from bottle import request, response, route

from mercado_libre import api, schemas
from schema_fields import load_query
from scraper_errors import BadRequest, NotFound

PREFIX = "/mercado-libre"


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The query as unicode strings (bottle 0.12's .get() hands back latin-1
    decoded bytes, so a UTF-8 "Florianópolis" would arrive mangled)."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _page_link(path, params, page):
    if not page:
        return None
    query = {k: v for k, v in params.items() if v not in (None, "", False)}
    query["page"] = page
    return f"{request.urlparts.scheme}://{request.urlparts.netloc}{path}?{urlencode(query, doseq=True)}"


def paginate(result, path, params):
    """Lift the scraper's `pagination` block into the flat shape the hosted
    API returns: count / per_page / current_page / total_pages / next /
    previous. Sources without a total set `has_next` instead."""
    pagination = result.pop("pagination", None) or {}
    result.pop("count", None)
    page = _as_int(pagination.get("page")) or _as_int(params.get("page")) or 1
    if "has_next" in pagination:
        has_next = bool(pagination["has_next"])
        total_pages = pagination.get("total_pages")
        if total_pages is not None:
            total_pages = _as_int(total_pages, None)
    else:
        total_pages = max(_as_int(pagination.get("total_pages")), 0)
        has_next = page < total_pages
    out = {
        "count": pagination.get("total_count"),
        "per_page": pagination.get("items_per_page"),
        "current_page": page,
        "total_pages": total_pages,
        "next": _page_link(path, params, page + 1 if has_next else None),
        "previous": _page_link(path, params, page - 1 if page > 1 else None),
    }
    out.update(result)
    return out


def call(label, schema_cls, impl, paginated):
    """Validate the query, run the endpoint, map failures: bad params -> 400,
    missing record -> 404, retries exhausted / blocked -> 500."""
    params = query_dict()
    data, error = load_query(schema_cls, params)
    if error:
        return json_response(error, 400)
    try:
        result = impl(**data)
    except ValueError as e:
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:
        return json_response({"error": f"mercado libre rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Exception as e:
        return json_response({"error": f"mercado libre {label} failed: {e}"}, 500)
    if paginated:
        result = paginate(result, request.path, params)
    return json_response(result)


def mount(path, schema_cls, impl, paginated=False):
    """Serve one endpoint at /path and /mercado-libre/path."""
    def handler():
        return call(path.strip("/"), schema_cls, impl, paginated)
    handler.__name__ = "mercado_libre_" + path.strip("/").replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route(PREFIX + path, method="GET")(handler)


ENDPOINTS = [
    ("/products/details", schemas.ProductSchema, api.product_details, False),
    ("/search/suggest", schemas.SuggestSchema, api.search_suggest, False),
    ("/products/search", schemas.ProductsSearchSchema, api.products_search, True),
    ("/products/reviews", schemas.ProductReviewsSchema, api.product_reviews, True),
    ("/categories/list", schemas.CategoriesListSchema, api.categories_list, False),
    ("/categories/discover", schemas.CategoriesDiscoverSchema, api.categories_discover, False),
    ("/categories/products", schemas.CategoryProductsSchema, api.category_products, True),
    ("/categories/best-sellers", schemas.BestSellersSchema, api.best_sellers, False),
    ("/deals/list", schemas.DealsSchema, api.deals_list, True),
    ("/stores/search", schemas.StoresSearchSchema, api.stores_search, True),
    ("/stores/products", schemas.StoreProductsSchema, api.store_products, True),
    ("/sellers/products", schemas.SellerProductsSchema, api.seller_products, True),
    ("/classifieds/search", schemas.ClassifiedsSearchSchema, api.classifieds_search, True),
    ("/classifieds/details", schemas.ClassifiedSchema, api.classified_details, False),
]

for _path, _schema, _impl, _paginated in ENDPOINTS:
    mount(_path, _schema, _impl, _paginated)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, *_ in ENDPOINTS]})
