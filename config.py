"""Configuration for the Mercado Libre Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT                  port the API listens on (default 8000)
    MERCADO_LIBRE_PROXY   proxy URL for every request, e.g. http://user:pass@host:port
                          (default: none — direct). Product, search, category,
                          store, seller, deal, review and classifieds pages all
                          answer a plain connection. The one exception is
                          search/suggest on the Argentina site (MLA): its CDN
                          only answers Argentine IPs, so set a proxy in
                          Argentina if you need that endpoint for MLA.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

MERCADO_LIBRE_PROXY = os.environ.get("MERCADO_LIBRE_PROXY") or None


def mercado_libre_proxy():
    """The proxy for every page and JSON request (None = direct)."""
    return os.environ.get("MERCADO_LIBRE_PROXY") or None


def mercado_libre_suggest_proxy(site):
    """The proxy for search/suggest on `site` (MLA, MLB, ...). Same knob:
    the Argentina suggest CDN needs an Argentine IP, the other sites don't."""
    return os.environ.get("MERCADO_LIBRE_PROXY") or None
