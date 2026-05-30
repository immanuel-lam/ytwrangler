#!/usr/bin/env python3
"""ytwrangler entry point."""

import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        sys.stderr.write(
            "PySide6 is not installed.\n"
            "Install dependencies with:  pip install -r requirements.txt\n")
        return 1

    from ytwrangler.session import AppState
    from ytwrangler.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("ytwrangler")
    state = AppState()
    window = MainWindow(state)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
