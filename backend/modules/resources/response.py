"""Resource API response helpers."""

import time


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _ok(data=None):
    return {
        "is_success": True,
        "msg": "OK",
        "time": _now(),
        "timestamp": int(time.time() * 1000),
        **(data or {}),
    }


def _error(msg, status_code=500, response=None):
    return {
        "is_success": False,
        "msg": msg,
        "http_status_code": status_code,
        "response": response or {},
        "time": _now(),
        "timestamp": int(time.time() * 1000),
    }


