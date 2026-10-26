"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does (minus the flat paging
links the server adds); results are written to output/*.json.
"""
import json
import os

from mercado_libre import api, refs

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # an item id, a catalog product id, a user-product id or any product link
    save("product_MLA1932888020.json", api.product_details(refs.resolve_product("MLA1932888020")))

    # 50 results per page; sort, condition, price range and free shipping filters
    save("search_raspberry_pi.json", api.products_search(
        query="raspberry pi", site="MLA", page=1, sort=None, condition=None,
        price_min=None, price_max=None, free_shipping=None))

    # 30 reviews per page plus the star breakdown
    save("reviews_MLA1040287791.json", api.product_reviews(
        product=refs.resolve_product("MLA1040287791"), page=1, rating=None))
