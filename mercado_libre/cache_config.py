"""Cache TTL per /mercado-libre/* endpoint (cache.py, keyed on the validated
params). Mercado Libre is a live marketplace: prices, stock and deal pages
move within hours, so product-level data caches briefly while reference
data (category tree, store directory) caches for a day. Product details
cache the parsed page ONCE (api._product_record) and the details endpoint
slices it; reviews pages cache their own JSON.
"""
from datetime import timedelta

# Search results reorder and reprice through the day; an hour keeps a
# paging client consistent across its pages.
SEARCH_CACHE = timedelta(hours=1)
# One product page parse per product reference: price and stock move, but
# the same product is typically hit several times in a session.
PRODUCT_CACHE = timedelta(hours=2)
# Reviews accrue slowly; a page of 30 rarely changes within a day.
REVIEWS_CACHE = timedelta(hours=12)
# The department menu and the category API are reference data.
CATEGORIES_CACHE = timedelta(hours=24)
# Category discovery maps text to categories; stable for weeks.
DISCOVER_CACHE = timedelta(hours=24)
# Best-seller rankings are recomputed by the site daily.
BEST_SELLERS_CACHE = timedelta(hours=6)
# Deal pages rotate with lightning offers; keep them short.
DEALS_CACHE = timedelta(minutes=30)
# A seller's or store's listing pages: like search.
SELLER_CACHE = timedelta(hours=1)
STORE_CACHE = timedelta(hours=1)
# The official-store directory changes slowly.
STORES_CACHE = timedelta(hours=24)
# Autosuggest reflects search trends; a day is fine.
SUGGEST_CACHE = timedelta(hours=24)
# Classified listings (real estate / vehicles) turn over slower than core.
CLASSIFIEDS_CACHE = timedelta(hours=3)
