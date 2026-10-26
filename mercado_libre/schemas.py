"""Marshmallow request schemas for every /mercado-libre/* route.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair):

    product    an item id (MLA1918268342), a catalog product id (MLA39328824),
               a user-product id (MLAU3735180826) OR the product link
    seller     a numeric seller id OR a seller listing link (…/_CustId_<id>)
    store      an official-store slug OR the store link (tienda.<domain>/<slug>)
    category   a category id (MLA1055) OR a category listing link
    listing    a classified listing id OR its link (classifieds/details) /
               a classifieds search link (classifieds/search)
    site       the country site: MLA Argentina (default), MLB Brazil, MLM
               Mexico, MLC Chile, MCO Colombia, MPE Peru, MLU Uruguay, …
               (a 2-letter country code is accepted too). Ids carry their
               site prefix, so `site` only matters for inputs without one
               (query, seller id, store slug).

Site filter grammar (refs.filter_segments, verified 2026-10-24 on the mobile
render): page -> _Desde_<offset+1>, sort price_asc/price_desc, condition
new/used, price range, free shipping. A category filter on search is NOT
offered: the mobile render ignores the _CategoryId_ segment.
"""
from marshmallow import ValidationError, validates_schema

from schema_fields import (BaseSchema, ChoiceField, Flag, LimitField, PageField, Price, PositiveInt,
                           QueryField, RefField, StrippedString)
from mercado_libre import refs

# Search results stop at 2000 (the site's own results_limit) = 40 pages of 50.
MAX_SEARCH_PAGE = 40
# Reviews: offset/limit XHR, 30 per page; the site serves the first 11 pages (330 reviews) of a query.
MAX_REVIEWS_PAGE = 11
# Deals: 500 offers per feed; ?page=N steps the offset by 20 (each page
# carries 25, overlapping), so the last page is 25.
MAX_DEALS_PAGE = 25
# Official stores: offset + limit <= 10000 at 100 per page.
MAX_STORES_PAGE = 100


class SiteField(ChoiceField):
    """Site id (MLA, MLB, …) or ISO country code (AR, BR, …) -> site id."""

    def __init__(self, **kwargs):
        kwargs.setdefault("load_default", refs.DEFAULT_SITE)
        kwargs.setdefault("metadata", {"description": "country site: MLA Argentina (default), MLB Brazil, MLM Mexico, MLC Chile, "
                                                      "MCO Colombia, MPE Peru, MLU Uruguay, MEC Ecuador, MLV Venezuela… "
                                                      "(or the ISO country code: AR, BR, MX)"})
        super().__init__(list(refs.SITE_IDS), **kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = StrippedString._deserialize(self, value, attr, data, **kwargs)
        if value is None:
            return None
        try:
            return refs.resolve_site(value)
        except ValueError as e:
            raise ValidationError(str(e))


class ProductRefField(RefField):
    resolver = staticmethod(refs.resolve_product)


class SellerRefField(RefField):
    resolver = staticmethod(refs.resolve_seller)


class StoreRefField(RefField):
    resolver = staticmethod(refs.resolve_store)


class CategoryRefField(RefField):
    resolver = staticmethod(refs.resolve_category)


class CategoryIdField(RefField):
    resolver = staticmethod(refs.resolve_category_id)


class ListingLinkField(RefField):
    resolver = staticmethod(refs.resolve_listing_link)


class ClassifiedRefField(RefField):
    resolver = staticmethod(refs.resolve_classified)


class _ListingFilters(BaseSchema):
    """The filters every listing route shares (search / category / seller / store)."""
    page = PageField(max_page=MAX_SEARCH_PAGE, metadata={"description": "page number, 50 results per page (max 40: the site stops at 2000 results)"})
    sort = ChoiceField(list(refs.SORT_SEGMENTS), metadata={"description": "relevance (default), price_asc or price_desc"})
    condition = ChoiceField(list(refs.CONDITION_SEGMENTS), metadata={"description": "new or used"})
    price_min = Price(metadata={"description": "minimum price in the site's currency"})
    price_max = Price(metadata={"description": "maximum price in the site's currency"})
    free_shipping = Flag(metadata={"description": "true = only listings with free shipping"})

    @validates_schema
    def _price_order(self, data, **kwargs):
        lo, hi = data.get("price_min"), data.get("price_max")
        if lo is not None and hi is not None and lo > hi:
            raise ValidationError("price_min must not exceed price_max.", "price_max")


class ProductsSearchSchema(_ListingFilters):
    query = QueryField(metadata={"description": "search terms, e.g. iphone 15 128gb"})
    site = SiteField()


class ProductSchema(BaseSchema):
    product = ProductRefField(metadata={
        "description": "item id (MLA1918268342), catalog product id (MLA39328824), user-product id (MLAU3735180826) or the product link"})


class ProductReviewsSchema(BaseSchema):
    product = ProductRefField(metadata={
        "description": "item id, catalog product id or the product link (an item resolves to its catalog product's reviews)"})
    page = PageField(max_page=MAX_REVIEWS_PAGE, metadata={"description": "page number, 30 reviews per page (Mercado Libre serves the first 330 reviews of a query)"})
    rating = PositiveInt(max_value=5, metadata={"description": "only reviews with this star rating (1-5)"})


class CategoriesListSchema(BaseSchema):
    site = SiteField()
    category = CategoryIdField(required=False, load_default=None, metadata={
        "description": "a category id (MLA1055) for that category's record and children; omit for the site's department tree"})


class CategoryProductsSchema(_ListingFilters):
    category = CategoryRefField(metadata={
        "description": "category id (MLA1055; must be a category the site menu links to, see categories/list) or a category listing link"})


class BestSellersSchema(BaseSchema):
    category = CategoryIdField(metadata={"description": "category id (MLA1055) or a …/mas-vendidos/<id> link"})


class CategoriesDiscoverSchema(BaseSchema):
    query = QueryField(metadata={"description": "product text to classify, e.g. notebook gamer"})
    site = SiteField()
    limit = LimitField(default=5, max_size=8, metadata={"description": "number of category suggestions (max 8)"})


class DealsSchema(BaseSchema):
    site = SiteField()
    page = PageField(max_page=MAX_DEALS_PAGE, metadata={"description": "page number, 25 deals per page (max 25)"})
    category = CategoryIdField(required=False, load_default=None, metadata={"description": "restrict to a category id (MLA1055)"})


class SellerProductsSchema(_ListingFilters):
    seller = SellerRefField(metadata={"description": "numeric seller id (71229887) or a seller listing link (…/_CustId_71229887)"})
    site = SiteField()


class StoresSearchSchema(BaseSchema):
    query = StrippedString(required=False, load_default=None, metadata={"description": "store name to search; omit to list every official store"})
    site = SiteField()
    page = PageField(max_page=MAX_STORES_PAGE, metadata={"description": "page number, 100 stores per page"})


class StoreProductsSchema(_ListingFilters):
    store = StoreRefField(metadata={"description": "official store slug (samsung) or the store link (tienda.mercadolibre.com.ar/samsung)"})
    site = SiteField()


class SuggestSchema(BaseSchema):
    query = QueryField(max_length=100, metadata={"description": "text typed so far, e.g. ipho"})
    site = SiteField()
    limit = LimitField(default=6, max_size=10, metadata={"description": "number of suggestions (max 10)"})


class ClassifiedsSearchSchema(BaseSchema):
    listing = ListingLinkField(metadata={
        "description": "a classifieds listing link: inmuebles.mercadolibre.com.ar/departamentos/venta/capital-federal/, autos.mercadolibre.com.ar/toyota/corolla/, …"})
    page = PageField(max_page=MAX_SEARCH_PAGE, metadata={"description": "page number, 50 results per page"})
    sort = ChoiceField(list(refs.SORT_SEGMENTS), metadata={"description": "relevance (default), price_asc or price_desc"})
    price_min = Price(metadata={"description": "minimum price"})
    price_max = Price(metadata={"description": "maximum price"})


class ClassifiedSchema(BaseSchema):
    listing = ClassifiedRefField(metadata={"description": "classified listing id (MLA4117637236) or its link (departamento./auto.<domain>/MLA-…-_JM)"})
