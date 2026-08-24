"""Background resource snapshot scheduling."""

import threading
import time

from .settings import _auto_snapshot_enabled, _auto_snapshot_interval_seconds, _snapshot_enabled
from .views import summary


_snapshot_collector_lock = threading.Lock()
_snapshot_collector_started = False


def _snapshot_collector_loop():
    while True:
        try:
            summary({})
        except Exception:
            pass
        time.sleep(_auto_snapshot_interval_seconds())


def start_resource_snapshot_collector():
    global _snapshot_collector_started

    if not _snapshot_enabled() or not _auto_snapshot_enabled():
        return False

    with _snapshot_collector_lock:
        if _snapshot_collector_started:
            return False

        thread = threading.Thread(
            target=_snapshot_collector_loop,
            name="jushi-resource-snapshot-collector",
            daemon=True,
        )
        thread.start()
        _snapshot_collector_started = True
        return True


