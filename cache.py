"""A small in-memory response cache, so repeated calls in one run are free.

`cached_call(namespace, data, fn, ttl)` serves fn(**data) from memory for
`ttl` (a timedelta, or a function (data, result) -> timedelta that decides
once the result is known), else runs it and stores the result. Entries live
only as long as the process; exceptions are never cached.
"""
import json
import threading
import time

_lock = threading.Lock()
_store = {}
MAX_ENTRIES = 2000


def _key(namespace, data):
    return namespace + ":" + json.dumps(data, sort_keys=True, default=str)


def cached_call(namespace, data, fn, ttl, cache=True, refresh=False):
    key = _key(namespace, data)
    if cache and ttl and not refresh:
        with _lock:
            hit = _store.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
    result = fn(**data)
    keep = ttl(data, result) if callable(ttl) else ttl
    seconds = keep.total_seconds() if keep else 0
    if cache and seconds:
        with _lock:
            if len(_store) >= MAX_ENTRIES:
                _store.pop(next(iter(_store)))
            _store[key] = (time.monotonic() + seconds, result)
    return result
