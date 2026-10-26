"""Offline tests for the /mercado-libre/* request schemas and reference
resolvers.

    python -m pytest mercado_libre/test_schemas.py -q
"""
import os
import sys

import pytest
from marshmallow import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mercado_libre import refs, schemas  # noqa: E402


# ---- products -------------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("MLA39328824", {"id": "MLA39328824", "kind": "unknown", "site": "MLA"}),
    ("mla1918268342", {"id": "MLA1918268342", "kind": "unknown", "site": "MLA"}),
    ("MLA-1918268342", {"id": "MLA1918268342", "kind": "item", "site": "MLA"}),
    ("MLAU3735180826", {"id": "MLAU3735180826", "kind": "user_product", "site": "MLA"}),
    ("https://www.mercadolibre.com.ar/motorola-moto-g04s/p/MLA39328824", {"id": "MLA39328824", "kind": "product", "site": "MLA"}),
    ("https://www.mercadolibre.com.ar/p/MLA39328824?pdp_filters=x#origin=share", {"id": "MLA39328824", "kind": "product", "site": "MLA"}),
    ("https://articulo.mercadolibre.com.ar/MLA-1918268342-_JM", {"id": "MLA1918268342", "kind": "item", "site": "MLA"}),
    ("https://produto.mercadolivre.com.br/MLB-5285140690-coin-col-_JM", {"id": "MLB5285140690", "kind": "item", "site": "MLB"}),
    ("https://www.mercadolibre.com.ar/bici/up/MLAU3735180826", {"id": "MLAU3735180826", "kind": "user_product", "site": "MLA"}),
    ("https://www.mercadolibre.com.ar/products/MLA58353028/", {"id": "MLA58353028", "kind": "product", "site": "MLA"}),
    ("//www.mercadolibre.com.mx/p/MLM39328824", {"id": "MLM39328824", "kind": "product", "site": "MLM"}),
])
def test_resolve_product(value, expected):
    assert refs.resolve_product(value) == expected


@pytest.mark.parametrize("value", ["", "iphone", "XYZ123456789", "https://example.com/p/MLA39328824",
                                   "https://www.mercadolibre.com.ar/ofertas"])
def test_resolve_product_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_product(value)


def test_product_schema():
    assert schemas.ProductSchema().load({"product": " MLA39328824 "}) == {
        "product": {"id": "MLA39328824", "kind": "unknown", "site": "MLA"}}
    with pytest.raises(ValidationError) as err:
        schemas.ProductSchema().load({"product": "iphone"})
    assert "product" in err.value.messages
    with pytest.raises(ValidationError):
        schemas.ProductSchema().load({})
    with pytest.raises(ValidationError):   # sibling params are refused
        schemas.ProductSchema().load({"product": "MLA39328824", "url": "https://x"})


def test_reviews_schema():
    loaded = schemas.ProductReviewsSchema().load({"product": "MLA39328824", "page": "2", "rating": "5"})
    assert loaded["page"] == 2 and loaded["rating"] == 5
    with pytest.raises(ValidationError):
        schemas.ProductReviewsSchema().load({"product": "MLA39328824", "rating": "6"})
    with pytest.raises(ValidationError):
        schemas.ProductReviewsSchema().load({"product": "MLA39328824", "page": "0"})


# ---- search ---------------------------------------------------------------------------------

def test_search_schema_defaults_and_filters():
    loaded = schemas.ProductsSearchSchema().load({"query": " iphone  15 "})
    assert loaded == {"query": "iphone 15", "site": "MLA", "page": 1, "sort": None, "condition": None,
                      "price_min": None, "price_max": None, "free_shipping": None}
    loaded = schemas.ProductsSearchSchema().load({"query": "tv", "site": "br", "sort": "Price_Desc", "condition": "USED",
                                                  "price_min": "100", "price_max": "5000.5", "free_shipping": "yes", "page": "40"})
    assert loaded["site"] == "MLB" and loaded["sort"] == "price_desc" and loaded["condition"] == "used"
    assert loaded["price_min"] == 100 and loaded["price_max"] == 5000.5 and loaded["free_shipping"] is True


@pytest.mark.parametrize("query", [
    {"query": "tv", "page": "41"},
    {"query": "tv", "sort": "newest"},
    {"query": "tv", "condition": "refurbished"},
    {"query": "tv", "site": "XX"},
    {"query": "tv", "price_min": "500", "price_max": "100"},
    {"query": "tv", "category": "MLA1055"},
    {"page": "1"},
])
def test_search_schema_rejects(query):
    with pytest.raises(ValidationError):
        schemas.ProductsSearchSchema().load(query)


def test_site_field_accepts_country_codes():
    assert schemas.SuggestSchema().load({"query": "ipho", "site": "mx"})["site"] == "MLM"
    assert schemas.SuggestSchema().load({"query": "ipho"})["limit"] == 6
    with pytest.raises(ValidationError):
        schemas.SuggestSchema().load({"query": "ipho", "limit": "11"})


# ---- sellers / stores -------------------------------------------------------------------------

def test_resolve_seller():
    assert refs.resolve_seller("71229887") == {"id": 71229887, "site": None}
    assert refs.resolve_seller("https://listado.mercadolibre.com.ar/_CustId_71229887?item_id=MLA1") == {"id": 71229887, "site": "MLA"}
    assert refs.resolve_seller("https://lista.mercadolivre.com.br/x?seller_id=3294078235") == {"id": 3294078235, "site": "MLB"}
    for bad in ("", "PRONTOTEC", "https://www.mercadolibre.com.ar/perfil/PRONTOTEC"):
        with pytest.raises(ValueError):
            refs.resolve_seller(bad)


def test_seller_schema():
    loaded = schemas.SellerProductsSchema().load({"seller": "71229887", "site": "AR", "sort": "price_asc"})
    assert loaded["seller"] == {"id": 71229887, "site": None} and loaded["site"] == "MLA"
    with pytest.raises(ValidationError) as err:
        schemas.SellerProductsSchema().load({"seller": "https://www.mercadolibre.com.ar/perfil/PRONTOTEC"})
    assert "nickname" in str(err.value.messages["seller"])


def test_resolve_store():
    assert refs.resolve_store("Samsung") == {"slug": "samsung", "site": None}
    assert refs.resolve_store("https://tienda.mercadolibre.com.ar/samsung?x=1") == {"slug": "samsung", "site": "MLA"}
    assert refs.resolve_store("https://www.mercadolibre.com.ar/tienda/electro-outlet?client=x") == {"slug": "electro-outlet", "site": "MLA"}
    assert refs.resolve_store("https://www.mercadolivre.com.br/loja/samsung") == {"slug": "samsung", "site": "MLB"}
    for bad in ("", "sam sung", "https://www.mercadolibre.com.ar/ofertas", "https://example.com/tienda/x"):
        with pytest.raises(ValueError):
            refs.resolve_store(bad)


def test_stores_search_schema():
    assert schemas.StoresSearchSchema().load({}) == {"query": None, "site": "MLA", "page": 1}
    assert schemas.StoresSearchSchema().load({"query": "samsung", "page": "3"})["page"] == 3
    with pytest.raises(ValidationError):
        schemas.StoresSearchSchema().load({"page": "101"})


# ---- categories ----------------------------------------------------------------------------------

def test_resolve_category():
    assert refs.resolve_category("mla1055") == {"id": "MLA1055", "link": None, "site": "MLA"}
    link = "https://listado.mercadolibre.com.ar/celulares-telefonos/celulares-smartphones/"
    assert refs.resolve_category(link) == {"id": None, "link": link, "site": "MLA"}
    assert refs.resolve_category("https://www.mercadolibre.com.ar/ofertas?category=MLA1055") == {"id": "MLA1055", "link": None, "site": "MLA"}
    for bad in ("", "1055", "celulares", "https://www.mercadolibre.com.ar/p/MLA39328824", "https://example.com/x/"):
        with pytest.raises(ValueError):
            refs.resolve_category(bad)


def test_category_id_field():
    assert schemas.BestSellersSchema().load({"category": "https://www.mercadolibre.com.ar/mas-vendidos/MLA1055"}) == {"category": "MLA1055"}
    assert schemas.CategoriesListSchema().load({}) == {"site": "MLA", "category": None}
    assert schemas.CategoriesListSchema().load({"category": "MLB1051"})["category"] == "MLB1051"
    with pytest.raises(ValidationError):
        schemas.BestSellersSchema().load({"category": "https://listado.mercadolibre.com.ar/celulares-telefonos/"})
    with pytest.raises(ValidationError):
        schemas.BestSellersSchema().load({})


def test_deals_schema():
    assert schemas.DealsSchema().load({"page": "25"}) == {"site": "MLA", "page": 25, "category": None}
    with pytest.raises(ValidationError):
        schemas.DealsSchema().load({"page": "26"})


def test_discover_schema():
    loaded = schemas.CategoriesDiscoverSchema().load({"query": "notebook gamer"})
    assert loaded == {"query": "notebook gamer", "site": "MLA", "limit": 5}
    with pytest.raises(ValidationError):
        schemas.CategoriesDiscoverSchema().load({"query": "x", "limit": "9"})


# ---- classifieds -----------------------------------------------------------------------------------

def test_resolve_listing_link():
    assert refs.resolve_listing_link("https://inmuebles.mercadolibre.com.ar/departamentos/venta/capital-federal/") == {
        "link": "https://inmuebles.mercadolibre.com.ar/departamentos/venta/capital-federal/", "site": "MLA"}
    assert refs.resolve_listing_link("https://autos.mercadolibre.com.ar/toyota/corolla")["link"] == "https://autos.mercadolibre.com.ar/toyota/corolla/"
    for bad in ("", "departamentos", "https://auto.mercadolibre.com.ar/MLA-4006670502-toyota-_JM", "https://example.com/x/"):
        with pytest.raises(ValueError):
            refs.resolve_listing_link(bad)


def test_classified_schema():
    assert schemas.ClassifiedSchema().load({"listing": "MLA4117637236"}) == {"listing": {"id": "MLA4117637236", "site": "MLA"}}
    loaded = schemas.ClassifiedSchema().load({"listing": "https://departamento.mercadolibre.com.ar/MLA-4117637236-valle-510-_JM"})
    assert loaded["listing"] == {"id": "MLA4117637236", "site": "MLA"}
    with pytest.raises(ValidationError):
        schemas.ClassifiedSchema().load({"listing": "https://www.mercadolibre.com.ar/p/MLA39328824"})
    loaded = schemas.ClassifiedsSearchSchema().load({"listing": "https://autos.mercadolibre.com.ar/toyota/corolla/", "sort": "price_asc"})
    assert loaded["page"] == 1 and loaded["sort"] == "price_asc"


# ---- URL grammar -------------------------------------------------------------------------------------

def test_search_url_grammar():
    assert refs.search_url("MLA", "iphone 15") == "https://listado.mercadolibre.com.ar/iphone-15"
    assert refs.search_url("MLB", "tv", page=2) == "https://lista.mercadolivre.com.br/tv_Desde_51_NoIndex_True"
    url = refs.search_url("MLA", "tv", page=3, sort="price_desc", condition="used", price_min=1000, price_max=5000.5, free_shipping=True)
    assert url == ("https://listado.mercadolibre.com.ar/tv_Desde_101_OrderId_PRICE*DESC_ITEM*CONDITION_2230581"
                   "_PriceRange_1000-5000.5_CostoEnvio_Gratis_NoIndex_True")
    assert refs.filter_segments(price_max=500) == "_PriceRange_0-500_NoIndex_True"
    assert refs.listing_page_url("https://autos.mercadolibre.com.ar/toyota/corolla/", page=2) == \
        "https://autos.mercadolibre.com.ar/toyota/corolla/_Desde_51_NoIndex_True"
    # a filtered store page is a search segment on the search host: the
    # tienda.<domain>/<slug>_OrderId_… form is read as another store's slug
    assert refs.store_listing_url("MLA", "samsung") == "https://tienda.mercadolibre.com.ar/samsung"
    assert refs.store_listing_url("MLA", "samsung", sort="price_asc") == \
        "https://listado.mercadolibre.com.ar/_Tienda_samsung_OrderId_PRICE_NoIndex_True"
    assert refs.store_listing_url("MLB", "samsung", page=2) == "https://lista.mercadolivre.com.br/_Loja_samsung_Desde_51_NoIndex_True"
    assert refs.item_link("MLB", "MLB5285140690") == "https://produto.mercadolivre.com.br/MLB-5285140690-_JM"
    assert refs.deals_link("MLA", 3, "MLA1055") == "https://www.mercadolibre.com.ar/ofertas?page=3&category=MLA1055"
    assert refs.best_sellers_link("MLM", "MLM1055") == "https://www.mercadolibre.com.mx/mas-vendidos/MLM1055"

