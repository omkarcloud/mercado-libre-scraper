"""Offline tests for the short-link endpoint logic (mercado_libre/api.py),
with the fetch layer and the cache replaced by fakes.

    python -m pytest mercado_libre/test_api.py -q
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mercado_libre import api, cache_config, refs  # noqa: E402
from mercado_libre.fetch import MercadoLibreBlocked, MercadoLibreNotFound  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
ONE, MANY, EXPIRED = "https://meli.la/2CVs2dw", "https://meli.la/13ypyPd", "https://meli.la/2sQj1zj"
SOCIAL = "https://www.mercadolivre.com.br/social/sharer?matt_tool=1&forceInApp=true&ref=BERu%2Bgdp%3D%3D"
PROFILE = "https://www.mercadolivre.com.br/social/sharer?matt_tool=1&ref=x&skipWebview=true"


def page(name):
    """A fixture state as the html the fetch layer returns."""
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return "<script>_n.ctx.r=" + json.dumps(json.load(f)) + ";</script>"


LANDINGS = {
    ONE: (page("short_link_one_product_mlb.state.json"), PROFILE),
    MANY: (page("short_link_collection_mlb.state.json"), PROFILE),
    SOCIAL: (page("short_link_one_product_mlb.state.json"), SOCIAL + "&skipWebview=true"),
    EXPIRED: (page("short_link_expired_share_mlb.state.json"), "https://www.mercadolivre.com.br/social/sharer/lists?skipWebview=true"),
    "https://mercadolivre.com/sec/list": ("<script>_n.ctx.r={};</script>",
                                          "https://www.mercadolivre.com.br/social/sharer/lists/8f90988a?matt_tool=1&skipWebview=true"),
    "https://mercadolivre.com.br/sec/offers": ("<script>_n.ctx.r={};</script>",
                                               "https://www.mercadolivre.com.br/ofertas?matt_tool=1#nav-header&skipWebview=true"),
    "https://meli.la/direct": ("<script>_n.ctx.r={};</script>",
                               "https://www.mercadolivre.com.br/espremedor/p/MLB19307438?skipWebview=true"),
    "https://meli.la/elsewhere": ("<script>_n.ctx.r={};</script>", "https://www.mercadopago.com.br/home?skipWebview=true"),
}


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    """The cache runs the function every time and records (namespace, ttl);
    a short link opens its LANDINGS page; a product record is its reference."""
    seen = {"cache": [], "short": [], "records": [], "gone": set(), "blocked": set()}

    def cached_call(namespace, data, fn, ttl, **kw):
        result = fn(**data)
        seen["cache"].append((namespace, ttl(data, result) if callable(ttl) else ttl))
        return result

    def fetch_short_link(link):
        seen["short"].append(link)
        if link not in LANDINGS:
            raise MercadoLibreNotFound("short link not found")
        return LANDINGS[link]

    def record(product):
        seen["records"].append(product["id"])
        if product["id"] in seen["gone"]:
            raise MercadoLibreNotFound(f"product {product['id']} not found")
        if product["id"] in seen["blocked"]:
            raise MercadoLibreBlocked("challenge page")
        return {"id": product["id"], "site": product["site"], "link": f"https://www.mercadolivre.com.br/p/{product['id']}",
                "requested": {"id": product["id"], "kind": product["kind"]}}

    monkeypatch.setattr(api, "cached_call", cached_call)
    monkeypatch.setattr(api, "fetch_short_link", fetch_short_link)
    monkeypatch.setattr(api, "_record", record)
    monkeypatch.setattr(api, "release_session", lambda: None)
    return seen


def ref(value):
    return refs.resolve_product(value)


def test_one_product_link_answers_a_list_of_one(fakes):
    out = api.product_details(ref(ONE))
    assert out == {"short_link": ONE, "site": "MLB", "count": 1, "collection_link": None,
                   "results": [{"id": "MLB19307438", "site": "MLB", "link": "https://www.mercadolivre.com.br/p/MLB19307438"}]}
    # a link to one product is kept for a month
    assert ("mercado_libre.short_link", cache_config.SHORT_LINK_CACHE) in fakes["cache"]


def test_collection_link_answers_every_shared_product(fakes):
    out = api.product_details(ref(MANY))
    assert out["count"] == 6 and len(out["results"]) == 6
    assert out["collection_link"] == "https://lista.mercadolivre.com.br/_Container_cupom-gamer"
    # in the page's order, each a full record without the internal key
    assert [r["id"] for r in out["results"]] == [p["id"] for p in api._short_link(MANY)["products"]]
    assert all("requested" not in r for r in out["results"])
    # a collection's products change like a search: kept for an hour
    assert ("mercado_libre.short_link", cache_config.SHORT_LINK_COLLECTION_CACHE) in fakes["cache"]


def test_a_social_link_answers_like_its_short_link(fakes):
    """The page a short link opens, given directly: same list, opened as given."""
    out = api.product_details(ref(SOCIAL))
    assert out["short_link"] == SOCIAL and out["count"] == 1
    assert out["results"][0]["id"] == "MLB19307438" and out["site"] == "MLB"
    assert fakes["short"] == [SOCIAL]
    assert api.short_link_products(refs.resolve_short_link(SOCIAL)) == out


def test_the_endpoint_and_details_answer_the_same(fakes):
    for link in (ONE, MANY):
        assert api.short_link_products(refs.resolve_short_link(link)) == api.product_details(ref(link))


def test_an_id_or_product_link_still_answers_one_record(fakes):
    out = api.product_details(ref("MLB19307438"))
    assert out == {"id": "MLB19307438", "site": "MLB", "link": "https://www.mercadolivre.com.br/p/MLB19307438"}
    assert fakes["short"] == []


def test_a_product_no_longer_listed_is_left_out(fakes):
    products = api._short_link(MANY)["products"]
    fakes["gone"].add(products[1]["id"])
    out = api.short_link_products(MANY)
    assert out["count"] == 5 and products[1]["id"] not in [r["id"] for r in out["results"]]
    # every product gone: the link has nothing to show
    fakes["gone"].update(p["id"] for p in products)
    with pytest.raises(MercadoLibreNotFound):
        api.short_link_products(MANY)
    fakes["gone"].add("MLB19307438")
    with pytest.raises(MercadoLibreNotFound):
        api.short_link_products(ONE)


def test_a_failed_product_fails_the_call(fakes):
    """A blocked page must not shorten the list silently."""
    fakes["blocked"].add(api._short_link(MANY)["products"][2]["id"])
    with pytest.raises(MercadoLibreBlocked):
        api.short_link_products(MANY)


@pytest.mark.parametrize("link", [EXPIRED, "https://mercadolivre.com/sec/list", "https://mercadolivre.com.br/sec/offers",
                                  "https://meli.la/elsewhere"])
def test_links_that_share_no_product_are_a_400(link):
    with pytest.raises(ValueError, match="shares no product"):
        api.product_details(ref(link))


def test_unknown_code_is_a_404():
    with pytest.raises(MercadoLibreNotFound):
        api.short_link_products("https://meli.la/zzzzzzz")


def test_a_short_link_straight_to_a_product_page():
    out = api.short_link_products("https://meli.la/direct")
    assert out["count"] == 1 and out["results"][0]["id"] == "MLB19307438" and out["site"] == "MLB"


def test_reviews_take_the_one_product_behind_a_link(fakes, monkeypatch):
    monkeypatch.setattr(api, "fetch_reviews", lambda site, object_id, is_item, **kw: {"site": site, "id": object_id})
    monkeypatch.setattr(api, "fetch_reviews_summary", lambda site, object_id: "")
    monkeypatch.setattr(api.parsers, "parse_reviews_search", lambda payload: ([], None))
    monkeypatch.setattr(api.parsers, "parse_reviews_summary", lambda state: None)
    out = api.product_reviews(product=ref(ONE), page=1, rating=None)
    assert out["object_id"] == "MLB19307438" and out["site"] == "MLB"
    with pytest.raises(ValueError, match="shares 6 products"):
        api.product_reviews(product=ref(MANY), page=1, rating=None)
