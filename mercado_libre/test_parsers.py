"""Offline tests for the Mercado Libre parsers against the captured fixtures.

    python -m pytest mercado_libre/test_parsers.py -q

Fixtures (mercado_libre/fixtures/) were captured 2026-10-24 through the app
webview route (fetch.py): `*.html` are complete raw pages, `*.state.json` the
page's own `_n.ctx.r` state object, `*.json` raw JSON responses. They cover
the happy path (a search, a catalog product, a user product, a classified,
reviews), sparse pages (no-stock MLB product, deals past the end) and the
not-found shells (unknown product / seller / store / category, reviews of an
unknown id). No network.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mercado_libre import parsers as P  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return json.load(f) if name.endswith(".json") else f.read()


def state(name):
    return P.extract_state(fixture(name)) if name.endswith(".html") else fixture(name)


# ---- state extraction ----------------------------------------------------------------------------

def test_extract_state_is_brace_and_string_aware():
    st = P.extract_state(fixture("search_iphone_mla.html"))
    assert st["mainEntry"] == "___search-index.mobile"
    assert P.initial_state(st)["query"] == "iphone"
    assert P.extract_state("<html>no state</html>") is None
    assert P.extract_state('<script>_n.ctx.r={"a":"}{","b":{"c":1}};</script>') == {"a": "}{", "b": {"c": 1}}
    assert P.extract_state("") is None


def test_number_locale_rules():
    assert P._number("4.9") == 4.9
    assert P._number("1.299.999") == 1299999
    assert P._number("1.299.999,50") == 1299999.5
    assert P._number("+1000 vendidos") == 1000
    assert P._number("-34.6") == -34.6
    assert P._number(None) is None and P._number("") is None
    assert P._coordinate("-34.6245503") == -34.6245503 and P._coordinate("1.000.000") is None


# ---- listings ----------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def search():
    return P.parse_listing(state("search_iphone_mla.html"), page=1)


def test_search_listing(search):
    assert search["site"] == "MLA" and search["query"] == "iphone"
    assert search["category"] == {"id": "MLA1055", "path": ["MLA1051", "MLA1055"]}
    assert search["pagination"] == {"page": 1, "items_per_page": 50, "total_pages": 40, "total_count": 6203}
    assert len(search["results"]) == 50
    assert search["sort"] == "relevance"
    assert [s["id"] for s in search["sort_options"]] == ["relevance", "price_asc", "price_desc"]
    assert search["applied_filters"] == [{"id": "BRAND", "name": "Marca", "value_id": "9344", "value": "Apple"}]
    assert search["breadcrumb"][1]["name"] == "Celulares y Smartphones"
    assert "iphone 2" in search["related_searches"]


def test_search_polycard(search):
    card = search["results"][0]
    assert card["id"] == "MLA2395141386" and card["product_id"] == "MLA1040287791"
    assert card["title"].startswith("Apple iPhone 16 (128 GB)")
    assert card["link"] == "https://www.mercadolibre.com.ar/apple-iphone-16-128-gb-blanco-distribuidor-autorizado/p/MLA1040287791"
    assert card["price"]["current"] == {"amount": 1999999, "currency": "ARS"}
    assert card["price"]["previous"] == {"amount": 2459999, "currency": "ARS"}
    assert card["price"]["discount_percent"] == 18
    assert card["price"]["installments"]["quantity"] == 18 and card["price"]["installments"]["is_interest_free"] is True
    assert card["seller"] == {"name": "Apple", "is_official_store": True}
    assert card["rating"] == 4.9 and card["sold_quantity"] == 1000
    # "Llega gratis hoy por ser tu primera compra": free for a first purchase only
    assert card["shipping"]["is_free"] is False and card["shipping"]["is_free_for_first_purchase"] is True
    assert card["shipping"]["is_fulfillment"] is True
    assert card["deal_ends_at"] == "2026-10-24T14:59:00Z"
    assert card["variations"] == ["Blanco", "Negro"]
    assert card["image"].startswith("https://http2.mlstatic.com/D_NQ_NP_") and card["image"].endswith("-O.webp")
    assert card["is_ad"] is False and card["position"] == 1


def test_search_page_two_positions_and_sort():
    page = P.parse_listing(state("search_iphone_page2_price_asc_mla.state.json"), page=2)
    assert page["pagination"]["page"] == 2 and page["sort"] == "price_asc"
    assert page["results"][0]["position"] == 51


def test_search_used_condition():
    page = P.parse_listing(state("search_used_mla.state.json"), page=1)
    assert page["results"][0]["condition"] == "used"
    assert page["results"][0]["link"].endswith("/up/MLAU5642751210")


def test_search_available_filters_from_filters_page():
    page = P.parse_listing(state("search_iphone_filters_mla.state.json"), page=1)
    names = [f["id"] for f in page["available_filters"]]
    assert "shipping_time_highlighted_sameday" in names
    first = page["available_filters"][0]["values"][0]
    assert first["results"] == 130 and first["link"].startswith("https://listado.mercadolibre.com.ar/")


def test_category_listing_marks_ads():
    page = P.parse_listing(state("category_smartphones_mla.state.json"), page=1)
    ad = page["results"][0]
    assert ad["is_ad"] is True
    assert ad["link"] == "https://www.mercadolibre.com.ar/p/MLA62765000"
    assert ad["highlight"] == "OFERTA IMPERDIBLE"
    assert ad["price"]["discount_percent"] == 25


def test_brazil_listing_parses_the_same_way():
    page = P.parse_listing(state("search_iphone_mlb.state.json"), page=1)
    assert page["site"] == "MLB" and page["results"][0]["id"].startswith("MLB")
    assert page["results"][0]["shipping"]["is_free_for_first_purchase"] is True   # "grátis ... por ser sua primeira compra"
    assert page["results"][0]["price"]["current"]["currency"] == "BRL"


def test_store_listing_header():
    page = P.parse_listing(state("store_samsung_mla.html"), page=1)
    assert page["header"]["title"] == "Samsung" and page["header"]["link"] == "https://tienda.mercadolibre.com.ar/samsung"
    assert page["pagination"]["total_count"] == 311 and page["pagination"]["total_pages"] == 7


def test_seller_listing():
    page = P.parse_listing(state("seller_items_71229887_mla.state.json"), page=1)
    assert page["pagination"]["total_count"] == 1865 and len(page["results"]) == 50
    assert page["results"][0]["seller"]["is_official_store"] is True


def test_classifieds_listing():
    page = P.parse_listing(state("classifieds_apartments_caba_mla.state.json"), page=1)
    assert page["vertical"] == "RES" and page["pagination"]["total_count"] == 65274
    card = page["results"][0]
    assert card["price"] == {"current": {"amount": 114402, "currency": "USD"}, "previous": None, "discount_percent": None,
                             "prefix": "Desde", "installments": None, "discount_note": None, "notes": None}
    assert card["attributes"] == ["1 a 2 ambs.", "1 baño", "30 - 74 m² cubiertos"]
    assert card["location"].endswith("Capital Federal") and card["label"] == "EMPRENDIMIENTO"
    assert card["availability"] == "48 unidades disponibles"
    cars = P.parse_listing(state("classifieds_cars_corolla_mla.state.json"), page=1)
    assert cars["vertical"] == "MOT" and cars["results"][0]["attributes"] == ["2026", "0 Km"]
    assert cars["results"][0]["price"]["notes"] == ["Anticipo de 20,742,900 ARS"]


def test_no_results_shells():
    assert P.is_no_results_page(state("seller_items_unknown_mla.state.json")) is True
    assert P.is_no_results_page(state("store_unknown_mla.state.json")) is True
    assert P.is_no_results_page(state("category_by_id_mla.state.json")) is True
    assert P.is_no_results_page(state("search_used_mla.state.json")) is False
    assert P.parse_listing(state("store_unknown_mla.state.json"), page=1) is None


# ---- product pages --------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def product():
    return P.parse_product(state("product_moto_g04s_mla.html"))


def test_product_identity_and_price(product):
    assert product["id"] == "MLA1988557292" and product["product_id"] == "MLA39328824"
    assert product["parent_product_id"] == "MLA39328662" and product["site"] == "MLA"
    assert product["title"] == "Motorola Moto G04s Sunrise Orange 64gb 4gb"
    assert product["link"] == "https://www.mercadolibre.com.ar/motorola-moto-g04s-sunrise-orange-64gb-4gb/p/MLA39328824"
    assert product["condition"] == "new" and product["sold_quantity"] == 5000
    assert product["price"]["current"] == {"amount": 377789, "currency": "ARS"}
    assert product["price"]["installments"]["quantity"] == 6
    assert product["price"]["notes"] == ["Precio sin impuestos nacionales: 312,222 ARS"]
    assert [o["type"] for o in product["offers"]] == ["BEST_INSTALLMENTS", "BEST_PRICE"]
    assert product["offers"][0]["price"]["current"]["amount"] == 439538


def test_product_stock_shipping_rating(product):
    assert product["stock"] == {"has_stock": True, "available_quantity": 2, "note": "Stock disponible", "type": "normal"}
    assert product["shipping"]["is_free"] is True and product["shipping"]["logistic_type"] == "self_service"
    assert product["shipping"]["cost"] == {"amount": 0, "currency": "ARS"}
    assert product["rating"]["average"] == 4.7 and product["rating"]["count"] == 6490
    assert product["rating"]["stars"]["5"]["count"] == 5323
    assert product["rating"]["with_comments"] == 2447   # from the track event, the component has no count
    assert product["reviews_ai_summary"].startswith("El dispositivo ofrece")
    assert product["availability"] == "InStock" and product["price_valid_until"] == "2026-10-27"


def test_product_specs_variations_seller(product):
    assert product["highlights"][1] == "Memoria interna de 64GB."
    assert product["specs"]["Memoria interna"] == "64 GB"
    assert product["spec_groups"][0] == {"group": "Características generales", "attributes": [
        {"name": "Marca", "value": "Motorola"}, {"name": "Línea", "value": "Moto G"},
        {"name": "Modelo", "value": "Moto G04S"}, {"name": "Color", "value": "Sunrise Orange"}]}
    picker = product["variations"][0]
    assert picker["name"] == "Color" and picker["selected"] == "Sunrise Orange"
    assert picker["options"][0]["id"] == "MLA39356676" and picker["options"][0]["price"]["amount"] == 240000
    seller = product["seller"]
    assert seller["id"] == 41617028 and seller["name"] == "ELECTRO OUTLET"
    assert seller["is_official_store"] is True and seller["official_store_id"] == 201686
    assert seller["status"] == "MercadoLíder Platinum" and seller["sales"] == "+10 mil"
    assert seller["link"] == "https://www.mercadolibre.com.ar/tienda/electro-outlet"
    assert len(product["images"]) == 5 and product["images"][0]["width"] == 776
    assert product["description"].startswith("1. Cámara de 50 MP1")
    assert "Visa" in product["payment_methods"]
    assert product["benefits"][0].startswith("Devolución gratis.")
    assert product["category"]["id"] == "MLA1055" and product["category"]["breadcrumb"][2]["name"] == "Motorola"


def test_user_product_page():
    record = P.parse_product(state("product_user_product_mla.state.json"))
    assert record["id"] == "MLA2784602896" and record["user_product_id"] == "MLAU3735180826"
    assert record["condition"] == "used" and record["price"]["current"]["amount"] == 4900000
    assert record["seller"]["name"] == "PLAYKING2020" and record["seller"]["is_official_store"] is False
    assert record["seller"]["status"] == "MercadoLíder Gold"
    assert record["stock"]["available_quantity"] == 1 and record["rating"] is None


def test_item_redirects_to_its_catalog_product():
    record = P.parse_product(state("item_redirect_mla.state.json"))
    assert record["id"] == "MLA1988557292" and record["product_id"] == "MLA39328824"


def test_no_stock_product_has_no_price():
    record = P.parse_product(state("product_mlb.state.json"))
    assert record["site"] == "MLB" and record["price"] is None
    assert record["stock"]["has_stock"] is False and record["seller"] is None
    assert record["rating"]["count"] == 12922


def test_not_found_shells_have_no_state():
    for name in ("product_not_found_mla.state.json", "item_not_found_mla.state.json", "classified_not_found_mla.state.json"):
        assert P.parse_product(state(name)) is None
        assert P.parse_classified(state(name)) is None
    assert P.parse_best_sellers(state("best_sellers_unknown_mla.state.json")) is None


# ---- classifieds ------------------------------------------------------------------------------------

def test_classified_apartment():
    record = P.parse_classified(state("classified_apartment_mla.html"))
    assert record["id"] == "MLA4117637236" and record["vertical"] == "real_estate"
    assert record["title"] == "VALLE 510" and record["subtitle"].startswith("Emprendimiento")
    assert record["link"] == "https://departamento.mercadolibre.com.ar/MLA-4117637236-valle-y-jose-m-moreno-3-y-4-ambientes-premium-_JM"
    assert record["price"]["current"] == {"amount": 359000, "currency": "USD"} and record["price"]["label"] == "Emprendimiento desde"
    assert record["location"]["address"].startswith("Valle 510, Caballito")
    assert record["location"]["coordinates"] == {"latitude": -34.6245503, "longitude": -58.4347562}
    assert record["attributes"][0]["group"] == "Características del inmueble"
    assert {"name": "Dormitorios", "value": "2 a 3"} in record["attributes"][0]["attributes"]
    assert record["models"][0]["description"] == "3 ambientes | 3 baños | 107 m² cubiertos"
    assert record["points_of_interest"][0]["category"] == "Transporte"
    assert record["seller"]["name"] == "Irujoinmuebles" and record["seller"]["is_verified"] is True
    assert record["seller"]["type"] == "real_estate_agency" and record["seller"]["id"] == 183311746
    assert record["category"]["id"] == "MLA401806" and record["condition"] == "new"
    assert len(record["images"]) == 18


def test_classified_car():
    record = P.parse_classified(state("classified_car_mla.state.json"))
    assert record["vertical"] == "motors" and record["price"]["current"] == {"amount": 14000, "currency": "USD"}
    assert record["price_reference"]["low"] == "US$ 10.863"
    assert record["location"]["address"] == "Mar de Ajo, Bs.As. Costa Atlántica"
    assert {"name": "Año", "value": "2015"} in record["attributes"][1]["attributes"]
    assert record["seller"]["type"] == "car_dealer" and record["seller"]["link"].startswith("https://perfil.mercadolibre.com.ar/")
    assert record["description"].startswith("Toyota Corolla 2015")


# ---- reviews -------------------------------------------------------------------------------------------

def test_reviews_search_json():
    reviews, message = P.parse_reviews_search(fixture("reviews_search_moto_offset15_mla.json"))
    assert len(reviews) == 30 and message is None
    with_media = next(r for r in reviews if r["media"])
    assert with_media["id"] == 1649131524 and with_media["date"] == "2024-11-25" and with_media["likes"] == 10
    assert with_media["media"] == [{"type": "photo", "link": "https://http2.mlstatic.com/D_NQ_NP_635238-MLA80679340500_112024-O.webp"}]
    assert all(r["rating"] == 1 for r in P.parse_reviews_search(fixture("reviews_search_moto_rating1_mla.json"))[0])
    reviews, message = P.parse_reviews_search(fixture("reviews_search_unknown_mla.json"))
    assert reviews == [] and message == "¡Nada por acá!"


def test_reviews_summary_page():
    summary = P.parse_reviews_summary(state("reviews_summary_moto_mla.html"))
    assert summary["object_id"] == "MLA39328824" and summary["object_type"] == "product"
    assert summary["rating"]["average"] == 4.7 and summary["rating"]["count"] == 6490
    assert summary["rating"]["stars"]["1"] == {"count": 125, "percent": 1.93}
    assert summary["rating"]["photos"] == 299 and summary["with_comments"] == 2447
    assert len(summary["reviews"]) == 15 and summary["reviews"][0]["country"] == "Argentina"
    unknown = P.parse_reviews_summary(state("reviews_summary_unknown_mla.state.json"))
    assert unknown["rating"] is None and unknown["reviews"] == []
    assert unknown["message"] == "Este producto aún no tiene comentarios."


# ---- categories -----------------------------------------------------------------------------------------

def test_menu_and_category_api():
    menu = P.parse_menu(fixture("menu_departments_mla.json"))
    assert menu[0]["categories"][0]["id"] == "MLA1051"
    links = P.menu_links(fixture("menu_departments_mla.json"))
    assert links["MLA1055"] == "https://listado.mercadolibre.com.ar/celulares-telefonos/celulares-smartphones/"
    assert P.menu_links(fixture("menu_departments_mlb.json"))["MLB1051"].startswith("https://www.mercadolivre.com.br/")
    category = P.parse_category_api(fixture("api_category_MLA1055.json"))
    assert category["name"] == "Celulares y Smartphones" and category["total_items"] == 117735
    assert category["path"] == [{"id": "MLA1051", "name": "Celulares y Teléfonos"}, {"id": "MLA1055", "name": "Celulares y Smartphones"}]
    assert P.parse_category_api(fixture("api_category_unknown.json")) is None
    attributes = P.parse_category_attributes(fixture("api_category_attributes_MLA1055.json"))
    assert attributes[0]["id"] == "BRAND" and attributes[0]["is_required"] is True and len(attributes) == 197


def test_root_categories_from_stores_landing():
    roots = P.parse_root_categories(state("store_samsung_www_mla.state.json"))
    assert len(roots) == 26
    assert roots[0]["id"] == "MLA1574" and roots[0]["name"] == "Hogar, Muebles y Jardín"
    assert isinstance(roots[0]["official_stores"], int) and roots[0]["official_stores"] > 1000
    assert P.parse_root_categories(state("store_unknown_mla.state.json")) == []


def test_domain_discovery():
    rows = P.parse_domain_discovery(fixture("api_domain_discovery_notebook_mla.json"))
    assert rows[0] == {"category_id": "MLA1652", "category_name": "Notebooks", "domain_id": "MLA-NOTEBOOKS",
                       "domain_name": "Notebooks", "attributes": None}
    assert P.parse_domain_discovery(fixture("api_domain_discovery_nomatch_mla.json")) == []


# ---- best sellers / deals -----------------------------------------------------------------------------------

def test_best_sellers():
    page = P.parse_best_sellers(state("best_sellers_smartphones_mla.state.json"))
    assert page["title"] == "Los más vendidos en Mercado Libre" and len(page["results"]) == 20
    assert page["breadcrumb"][-1] == {"id": "MLA1055", "name": "Celulares y Smartphones", "link": "https://www.mercadolibre.com.ar/mas-vendidos/MLA1055"}
    top = page["results"][0]
    assert top["position"] == 1 and top["link"] == "https://www.mercadolibre.com.ar/p/MLA58353028"
    assert top["price"]["discount_percent"] == 40 and top["sold_quantity"] == 1000


def test_deals_pages():
    page = P.parse_deals(state("deals_page1_mla.state.json"), page=1)
    # ?page=N steps the offset by data.limit (20) while each page carries 25:
    # 500 offers take 25 pages, not 20
    assert page["pagination"] == {"page": 1, "items_per_page": 25, "total_pages": 25, "total_count": 500}
    assert len(page["results"]) == 25 and page["results"][0]["price"]["discount_percent"] == 23
    page3 = P.parse_deals(state("deals_page3_category_mla.state.json"), page=3)
    assert page3["category"] == "MLA1055" and page3["results"][0]["position"] == 41
    # cards whose url is "products/MLAU…/" (a user product, no catalog id)
    # must link to the /up/ page — the products/ path 404s
    user_product_cards = [r for r in page["results"] if r["product_id"] is None and r.get("user_product_id")]
    assert user_product_cards
    assert all(r["link"] == f"https://www.mercadolibre.com.ar/up/{r['user_product_id']}" for r in user_product_cards)
    assert not any("/products/" in (r["link"] or "") for r in page["results"])
    past = P.parse_deals(state("deals_page999_mla.state.json"), page=999)
    assert past["results"] == [] and past["pagination"]["total_pages"] == 25


# ---- stores / suggest -------------------------------------------------------------------------------------------

def test_stores():
    page = P.parse_stores(fixture("stores_all_offset0_mla.json"))
    assert page["pagination"] == {"page": 1, "items_per_page": 100, "total_pages": 110, "total_count": 10964}
    assert page["results"][0] == {
        "id": 361864, "name": "0800 GROWSHOP", "slug": "0800-growshop",
        "link": "https://www.mercadolibre.com.ar/tienda/0800-growshop",
        "logo": "https://http2.mlstatic.com/D_NQ_NP_747662-MLA110951278657_042026-F.jpg",
        "background": "https://http2.mlstatic.com/D_NQ_NP_796478-MLA110950876953_042026-OO.jpg",
        "category_ids": ["MLA1574"], "storefront_id": "4134df7a5c244d00b667c93607fa48d2102550583", "relevance_position": 10000}
    search = P.parse_stores(fixture("stores_search_samsung_mla.json"))
    assert search["query"] == "samsung" and search["results"][0]["slug"] == "samsung-smart-home"
    assert P.parse_stores(fixture("stores_search_nomatch_mla.json"))["pagination"]["total_count"] == 0
    assert P.parse_stores(fixture("stores_search_samsung_mlb.json"))["results"][0]["link"] == "https://www.mercadolivre.com.br/loja/samsung"


def test_autosuggest():
    rows = P.parse_autosuggest(fixture("autosuggest_iphone_mla.json"))
    assert rows[0]["query"] == "Iphone" and rows[0]["is_verified_store"] is False
    assert P.parse_autosuggest({"q": "x", "suggested_queries": []}) == []
    assert P.parse_autosuggest(None) == []


# ---- fixes found while building the Apify actors (2026-10-26) ---------------------------------

def test_promotion_placeholders_are_filled():
    page = P.parse_listing(state("category_smartphones_mla.state.json"), page=1)
    promos = [p for card in page["results"] for p in card["promotions"] or []]
    assert "858,853.65 ARS con Cupón" in promos
    assert not any("{" in p for p in promos)
    brazil = P.parse_listing(state("search_iphone_mlb.state.json"), page=1)
    assert not any("{" in p for card in brazil["results"] for p in card["promotions"] or [])


def test_plain_free_shipping_stays_free():
    deals = P.parse_deals(state("deals_page1_mla.state.json"), page=1)
    shipping = deals["results"][0]["shipping"]
    assert shipping["text"] == ["Llega gratis hoy"]
    assert shipping["is_free"] is True and shipping["is_free_for_first_purchase"] is False


def test_cards_always_carry_user_product_id():
    for name in ("search_iphone_mla.html", "classifieds_apartments_caba_mla.state.json", "search_used_mla.state.json"):
        page = P.parse_listing(state(name), page=1)
        assert all("user_product_id" in card for card in page["results"])


def test_item_page_variation_options_have_no_repeated_ids():
    record = P.parse_product(state("item_necklace_variations_mla.state.json"))
    assert record["id"] == "MLA1932888020" and record["product_id"] is None
    letter = record["variations"][0]
    assert letter["name"] == "Color" and letter["selected"] == "A"
    assert [o["id"] for o in letter["options"]] == [None] * len(letter["options"])
    assert [o["name"] for o in letter["options"] if o["is_selected"]] == ["A"]
    length = record["variations"][1]
    assert [o["name"] for o in length["options"]] == ["x40cm", "x45cm", "x50cm"]
    # catalog pages keep each option's own product id
    catalog = P.parse_product(state("product_moto_g04s_mla.html"))
    assert catalog["variations"][0]["options"][0]["id"] == "MLA39356676"


def test_ordinary_classified_reads_location_and_points():
    record = P.parse_classified(state("classified_apartment_rent_mla.state.json"))
    assert record["location"]["address"] == "Rodriguez Peña Al 1800, Recoleta, Capital Federal, Capital Federal"
    assert record["location"]["coordinates"] == {"latitude": -34.5900065, "longitude": -58.3881185}
    assert record["points_of_interest"][0] == {"category": "Transporte", "summary": "5 estaciones de metro", "places": None}
    groups = [g["group"] for g in record["attributes"]]
    assert groups.count("highlights") == 1 and groups[-1] == "summary"
