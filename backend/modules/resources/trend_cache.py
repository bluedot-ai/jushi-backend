"""In-process stale-while-revalidate cache for expensive trend ranges."""

from copy import deepcopy
from datetime import datetime
import threading
import time

from .settings import (
    _trend_cache_24h_refresh_seconds,
    _trend_cache_7d_refresh_seconds,
    _trend_cache_enabled,
    _trend_cache_warmup_delay_seconds,
)


CACHED_TREND_RANGES = ("24h", "7d")

_cache_lock = threading.RLock()
_refresh_locks = {range_value: threading.Lock() for range_value in CACHED_TREND_RANGES}
_refresh_query_lock = threading.Lock()
_cache_state = {
    range_value: {
        "data": None,
        "generated_at": None,
        "refreshing": False,
        "last_error": None,
        "last_duration_seconds": None,
    }
    for range_value in CACHED_TREND_RANGES
}
_cache_builder = None
_refresher_started = False
_refresher_start_lock = threading.Lock()


def _refresh_seconds(range_value):
    if range_value == "24h":
        return _trend_cache_24h_refresh_seconds()
    return _trend_cache_7d_refresh_seconds()


def is_trend_cache_enabled():
    return _trend_cache_enabled()


def _cache_metadata(range_value, state, now=None):
    now = now or datetime.now()
    generated_at = state.get("generated_at")
    age_seconds = None
    if generated_at:
        age_seconds = max(int((now - generated_at).total_seconds()), 0)

    return {
        "cache_hit": state.get("data") is not None,
        "cache_ready": state.get("data") is not None,
        "cache_status": "refreshing" if state.get("refreshing") else (
            "ready" if state.get("data") is not None else "warming"
        ),
        "cache_generated_at": (
            generated_at.strftime("%Y-%m-%d %H:%M:%S") if generated_at else None
        ),
        "cache_age_seconds": age_seconds,
        "cache_refresh_seconds": _refresh_seconds(range_value),
        "cache_refreshing": bool(state.get("refreshing")),
        "cache_last_error": bool(state.get("last_error")),
        "cache_last_duration_seconds": state.get("last_duration_seconds"),
    }


def get_cached_trend(range_value):
    if range_value not in CACHED_TREND_RANGES or not is_trend_cache_enabled():
        return None

    with _cache_lock:
        state = _cache_state[range_value]
        if state.get("data") is None:
            return None
        payload = deepcopy(state["data"])
        metadata = _cache_metadata(range_value, state)

    now = datetime.now()
    payload.update(metadata)
    payload["time"] = now.strftime("%Y-%m-%d %H:%M:%S")
    payload["timestamp"] = int(now.timestamp() * 1000)
    return payload


def get_trend_cache_status(range_value):
    if range_value not in CACHED_TREND_RANGES:
        return None
    with _cache_lock:
        return _cache_metadata(range_value, deepcopy(_cache_state[range_value]))


def _refresh_trend_cache(range_value):
    builder = _cache_builder
    if (
        not is_trend_cache_enabled()
        or range_value not in CACHED_TREND_RANGES
        or builder is None
    ):
        return False

    refresh_lock = _refresh_locks[range_value]
    if not refresh_lock.acquire(blocking=False):
        return False
    if not _refresh_query_lock.acquire(blocking=False):
        refresh_lock.release()
        return False

    started_at = time.monotonic()
    with _cache_lock:
        _cache_state[range_value]["refreshing"] = True

    try:
        payload = builder(range_value)
        if not payload or not payload.get("is_success"):
            message = (payload or {}).get("msg") or "trend cache builder returned no data"
            raise RuntimeError(message)

        duration = round(time.monotonic() - started_at, 3)
        with _cache_lock:
            state = _cache_state[range_value]
            state["data"] = deepcopy(payload)
            state["generated_at"] = datetime.now()
            state["last_error"] = None
            state["last_duration_seconds"] = duration
        print(
            f"[Jushi] Resource trend cache: refreshed range={range_value} "
            f"duration={duration}s"
        )
        return True
    except Exception as exc:
        duration = round(time.monotonic() - started_at, 3)
        with _cache_lock:
            state = _cache_state[range_value]
            state["last_error"] = str(exc)
            state["last_duration_seconds"] = duration
        print(
            f"[Jushi] Resource trend cache: refresh failed range={range_value} "
            f"duration={duration}s error_type={type(exc).__name__}"
        )
        return False
    finally:
        with _cache_lock:
            _cache_state[range_value]["refreshing"] = False
        _refresh_query_lock.release()
        refresh_lock.release()


def trigger_trend_cache_refresh(range_value):
    if range_value not in CACHED_TREND_RANGES or not is_trend_cache_enabled():
        return False
    with _cache_lock:
        if _cache_state[range_value]["refreshing"]:
            return False

    thread = threading.Thread(
        target=_refresh_trend_cache,
        args=(range_value,),
        name=f"jushi-resource-trend-cache-{range_value}",
        daemon=True,
    )
    thread.start()
    return True


def _trend_cache_refresher_loop():
    warmup_delay = _trend_cache_warmup_delay_seconds()
    if warmup_delay:
        time.sleep(warmup_delay)

    # Warm sequentially so the two expensive SQL statements never compete.
    for range_value in CACHED_TREND_RANGES:
        _refresh_trend_cache(range_value)

    next_refresh = {
        range_value: time.monotonic() + _refresh_seconds(range_value)
        for range_value in CACHED_TREND_RANGES
    }
    while True:
        now = time.monotonic()
        due_ranges = [
            range_value
            for range_value in CACHED_TREND_RANGES
            if now >= next_refresh[range_value]
        ]
        for range_value in due_ranges:
            _refresh_trend_cache(range_value)
            next_refresh[range_value] = time.monotonic() + _refresh_seconds(range_value)

        wait_seconds = max(min(next_refresh.values()) - time.monotonic(), 0.1)
        time.sleep(min(wait_seconds, 30))


def start_resource_trend_cache_refresher(builder):
    global _cache_builder, _refresher_started

    if not is_trend_cache_enabled():
        return False

    with _refresher_start_lock:
        _cache_builder = builder
        if _refresher_started:
            return False

        thread = threading.Thread(
            target=_trend_cache_refresher_loop,
            name="jushi-resource-trend-cache-refresher",
            daemon=True,
        )
        thread.start()
        _refresher_started = True
        return True

