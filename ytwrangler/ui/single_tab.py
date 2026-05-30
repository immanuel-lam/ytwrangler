"""Single tab: fetch a URL's formats and fine-tune one download."""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QProgressBar, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..session import AppState
from ..pipeline import fetch_info
from ..workers import DownloadWorker, FnWorker


def _human_size(n: int) -> str:
    if not n:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


class SingleTab(QWidget):
    def __init__(self, state: AppState, log_fn) -> None:
        super().__init__()
        self.state = state
        self.log = log_fn
        self.pool = QThreadPool()
        self.cancel_event = threading.Event()
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        url_row = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText("Paste a single URL…")
        url_row.addWidget(self.url, 1)
        self.fetch_btn = QPushButton("Fetch formats")
        self.fetch_btn.clicked.connect(self._fetch)
        url_row.addWidget(self.fetch_btn)
        root.addLayout(url_row)

        self.title = QLabel("")
        self.title.setStyleSheet("font-weight:bold;")
        root.addWidget(self.title)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["id", "ext", "resolution", "fps", "vcodec", "acodec", "size"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_select)
        root.addWidget(self.table, 1)

        # output options
        opt = QHBoxLayout()
        opt.addWidget(QLabel("Output:"))
        self.kind = QComboBox()
        self.kind.addItems(["Video (MP4)", "Audio (MP3)"])
        opt.addWidget(self.kind)
        opt.addWidget(QLabel("Format selector:"))
        self.fmt = QLineEdit("bv*+ba/b")
        self.fmt.setToolTip("yt-dlp -f value. Select a row above to fill it, "
                            "or type your own (e.g. 137+140).")
        opt.addWidget(self.fmt, 1)
        self.force = QCheckBox("Force H.264")
        opt.addWidget(self.force)
        root.addLayout(opt)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Folder:"))
        self.out_label = QLabel(self.state.data["out_dir"])
        self.out_label.setStyleSheet("color:#3a7afe;")
        out_row.addWidget(self.out_label, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._choose_out)
        out_row.addWidget(browse)
        root.addLayout(out_row)

        self.bar = QProgressBar()
        self.bar.setFormat("idle")
        root.addWidget(self.bar)

        self.dl_btn = QPushButton("▶  Download")
        self.dl_btn.clicked.connect(self._download)
        root.addWidget(self.dl_btn)

    # ---------------------------------------------------------- fetch -- #
    def _fetch(self) -> None:
        url = self.url.text().strip()
        if not url:
            return
        ok, msg = self.state.binaries_ok()
        if not ok:
            self.log(f"Cannot fetch — {msg}")
            return
        self.state.refresh_binaries()
        self.fetch_btn.setEnabled(False)
        self.title.setText("Fetching…")
        ctx = self.state.ctx(self.out_label.text())
        worker = FnWorker(lambda: fetch_info(ctx, url))
        worker.signals.done.connect(self._on_fetched)
        self.pool.start(worker)

    def _on_fetched(self, result, error: str) -> None:
        self.fetch_btn.setEnabled(True)
        if error or not result:
            self.title.setText("")
            self.log(f"Fetch failed: {error}")
            return
        self.title.setText(result["title"])
        formats = result["formats"]
        self.table.setRowCount(0)
        for f in formats:
            r = self.table.rowCount()
            self.table.insertRow(r)
            vals = [f["format_id"], f["ext"], f["resolution"], str(f["fps"]),
                    f["vcodec"], f["acodec"], _human_size(f["filesize"])]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.log(f"Loaded {len(formats)} formats for: {result['title']}")

    def _on_select(self) -> None:
        rows = {i.row() for i in self.table.selectedIndexes()}
        if not rows:
            return
        fmt_id = self.table.item(min(rows), 0).text()
        acodec = self.table.item(min(rows), 5).text()
        # If the chosen format has no audio, pair it with best audio.
        if acodec in ("", "none"):
            self.fmt.setText(f"{fmt_id}+ba/b")
        else:
            self.fmt.setText(fmt_id)

    # --------------------------------------------------------- output -- #
    def _choose_out(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose output folder",
                                             self.state.data["out_dir"])
        if d:
            self.out_label.setText(d)

    # ------------------------------------------------------- download -- #
    def _download(self) -> None:
        url = self.url.text().strip()
        if not url:
            return
        ok, msg = self.state.binaries_ok()
        if not ok:
            self.log(f"Cannot download — {msg}")
            return
        self.state.refresh_binaries()
        self.cancel_event = threading.Event()
        # "Video (MP4)" keeps audio (combined); the format selector below still
        # lets you pick a video-only stream if that's what you want.
        mode = "audio" if self.kind.currentText().startswith("Audio") else "both"
        job = {"url": url, "mode": mode, "force_h264": self.force.isChecked(),
               "fmt": None if mode == "audio" else self.fmt.text().strip()}
        ctx = self.state.ctx(self.out_label.text())
        self.dl_btn.setEnabled(False)
        worker = DownloadWorker(-1, job, ctx, self.cancel_event.is_set)
        worker.signals.progress.connect(
            lambda _row, pct, status: (self.bar.setValue(pct),
                                       self.bar.setFormat(status)))
        worker.signals.log.connect(self.log)
        worker.signals.finished.connect(self._on_done)
        self.pool.start(worker)

    def _on_done(self, _row: int, ok: bool, message: str) -> None:
        self.dl_btn.setEnabled(True)
        self.bar.setValue(100 if ok else 0)
        self.bar.setFormat(message)
        self.log(message)
