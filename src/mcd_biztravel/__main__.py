"""允许 ``python -m mcd_biztravel``。"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
