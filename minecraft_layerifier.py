from __future__ import annotations

import logging
import traceback

import tkinter as tk

from layerifier.app import LayerifierApp
from layerifier.constants import setup_logging


def main() -> int:
    setup_logging()
    try:
        root = tk.Tk()
        LayerifierApp(root)
        root.mainloop()
        return 0
    except Exception:
        setup_logging()
        logging.critical("Fatal application error\n%s", traceback.format_exc())
        raise


if __name__ == "__main__":
    raise SystemExit(main())
