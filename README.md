# 🛒 Mercado Libre Scraper

Mercado Libre Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Mercado Libre data for free.

## ✨ What Can I Get?

- 🛒 **Full details on 146M+ listings in Argentina alone** — price, installments, stock, specs, photos & seller reputation
- 🌎 **Search all 18 country sites** — Argentina, Brazil, Mexico & more; sort by price, filter by condition, price & free shipping
- ⭐ **Reviews, best sellers & live deals** — star breakdown, AI review summary, top-20 rankings & 500 live deals
- 🏬 **10,900+ official stores, any seller, cars & real estate** — full catalogs, seller listings & classifieds with every spec

## 🎥 Example: A Full Mercado Libre Product

```json
{
  "id": "MLA1932888020",
  "site": "MLA",
  "title": "Collar Cadena Dije Inicial En Plata 925 Letras Mujer Regalo",
  "link": "https://articulo.mercadolibre.com.ar/MLA-1932888020-collar-cadena-dije-inicial-en-plata-925-letras-mujer-regalo-_JM",
  "condition": "new",
  "sold_quantity": 1000,
  "price": {
    "current": { "amount": 63988, "currency": "ARS" },
    "previous": { "amount": 69500, "currency": "ARS" },
    "discount_percent": 8,
    "installments": { "quantity": 6, "amount": { "amount": 14269.32, "currency": "ARS" }, "is_interest_free": false }
  },
  "stock": { "has_stock": true, "available_quantity": 6 },
  "shipping": { "is_free": true, "logistic_type": "self_service", "cost": { "amount": 0, "currency": "ARS" } },
  "rating": {
    "average": 4.8,
    "count": 296,
    "stars": { "5": { "count": 254, "percent": 85.81 }, "4": { "count": 26, "percent": 8.78 } }
  },
  "reviews_ai_summary": "Se destaca por su empaque impresionante, que lo hace ideal para regalar. La calidad del producto es duradera, manteniéndose en perfectas condiciones incluso después de varios meses de uso.",
  "images": [{ "link": "https://http2.mlstatic.com/D_NQ_NP_773237-MLA112214581364_062026-O.webp" }],
  "seller": { "id": 19274282, "name": "JOYERÍA TIEMPO", "status": "MercadoLíder Platinum", "reputation_level": "5_green", "sales": "+1000" },
  "category": { "id": "MLA6312", "domain_id": "MLA-CHARMS" },
  "payment_methods": ["Mercado Crédito", "Visa", "American Express", "Mastercard"]
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Mercado Libre Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/mercado-libre-scraper
cd mercado-libre-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/products/details?product=MLA1932888020"
```

```json
{
  "id": "MLA1932888020",
  "title": "Collar Cadena Dije Inicial En Plata 925 Letras Mujer Regalo",
  "condition": "new",
  "sold_quantity": 1000,
  "price": {
    "current": { "amount": 63988, "currency": "ARS" },
    "previous": { "amount": 69500, "currency": "ARS" },
    "discount_percent": 8
  },
  "stock": { "has_stock": true, "available_quantity": 6, "note": "Stock disponible" },
  "rating": { "average": 4.8, "count": 296, "with_comments": 142 },
  "seller": {
    "id": 19274282,
    "name": "JOYERÍA TIEMPO",
    "status": "MercadoLíder Platinum",
    "sales": "+1000",
    "service_notes": ["Buena atención", "Entrega a tiempo"]
  }
}
```

All 14 endpoints are now live at `http://localhost:8000`.

Need search suggestions for Argentina (`site=MLA`)? That one endpoint only answers Argentine IPs, so set `MERCADO_LIBRE_PROXY=http://user:pass@host:port` (a proxy in Argentina) before `python run.py`. Everything else needs no proxy at all.

## 📚 Endpoints

14 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Product Details | `/products/details` | Price, installments, stock, specs, photos, ratings and seller in one call |
| Search Suggestions | `/search/suggest` | What buyers type, as they type it |
| Search Products | `/products/search` | 50 listings per page with price, discount, rating and shipping |
| Product Reviews | `/products/reviews` | 30 reviews per page plus star breakdown and AI summary |
| List Categories | `/categories/list` | Every root category, or one category's path and children |
| Discover Categories | `/categories/discover` | Any product text to category IDs, plus their attributes |
| Category Products | `/categories/products` | Every product in a category, 50 per page, filterable |
| Best Sellers | `/categories/best-sellers` | A category's top 20 best sellers with units sold |
| Deals | `/deals/list` | 500 live deals with price drops, 25 per page |
| Search Official Stores | `/stores/search` | 10,900+ official brand stores with logos and links |
| Store Products | `/stores/products` | An official store's full catalog, 50 per page |
| Seller Products | `/sellers/products` | Every active listing of any seller, 50 per page |
| Search Classifieds | `/classifieds/search` | Cars, apartments and services from any classifieds link |
| Classified Details | `/classifieds/details` | One car or property: price, every spec, map pin, seller |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-mercado-libre-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-mercado-libre-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-mercado-libre-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/products/details",
    params={"product": "MLA1932888020"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Mercado Libre Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Mercado%20Libre%20Scraper%20API.)

[![Ask Us by Email about Mercado Libre Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Mercado%20Libre%20Scraper%20API&body=I%20need%20help%20using%20the%20Mercado%20Libre%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/mercado-libre-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/mercado-libre-scraper)
