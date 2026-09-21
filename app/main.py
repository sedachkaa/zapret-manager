"""
Точка входа приложения Zapret Manager.

Запуск из исходников:
    python -m app.main

При сборке PyInstaller этот файл становится точкой входа exe.
"""

from __future__ import annotations

import sys

from app.core.config import Config
from app.gui.main_window import MainWindow


def main() -> int:
    cfg = Config()
    app = MainWindow(cfg)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())