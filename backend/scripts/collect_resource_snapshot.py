#!/usr/bin/env python3
import json
import sys
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = CURRENT_DIR.parent

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from modules.resources import service  # noqa: E402


def main():
    result = service.summary({})
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    if not result.get("is_success"):
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
