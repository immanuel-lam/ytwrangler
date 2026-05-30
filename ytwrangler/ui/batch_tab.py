"""Batch tab: paste many links, set per-link mode, hit Start."""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..session import AppState
from ..workers import DownloadWorker

MODES = ["both", "video", "audio"]
MODE_TOOLTIP = ("both = video + audio in one MP4\n"
                "video = video only, no audio (MP4)\n"
                "audio = audio only (MP3)")
COL_URL, COL_MODE, COL_FORCE, COL_STATUS = range(4)


class BatchTab(QWidget):
    def __init__(self, state: AppState, log_fn) -> None:
        super().__init__()
        self.state = state
        self.log = log_fn
        self.pool = QThreadPool()
        self.cancel_event = threading.Event()
        self._total = 0
        self._done = 0
        self._build_ui()
        self._load_items()

    # ---------------------------------------------------------------- UI -- #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # paste box + default mode + add
        add_row = QHBoxLayout()
        self.paste = QPlainTextEdit()
        self.paste.setPlaceholderText("Paste links here, one per line, then click Add…")
        self.paste.setFixedHeight(70)
        add_row.addWidget(self.paste, 1)

        side = QVBoxLayout()
        self.default_mode = QComboBox()
        self.default_mode.addItems(MODES)
        self.default_mode.setToolTip(MODE_TOOLTIP)
        side.addWidget(QLabel("New links as:"))
        side.addWidget(self.default_mode)
        add_btn = QPushButton("Add ↓")
        add_btn.clicked.connect(self._add_links)
        side.addWidget(add_btn)
        add_row.addLayout(side)
        root.addLayout(add_row)

        # table
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["URL", "Mode", "Force H.264", "Status"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(COL_URL, QHeaderView.Stretch)
        hdr.setSectionResizeMode(COL_MODE, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_FORCE, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_STATUS, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        # row actions
        tools = QHBoxLayout()
        rm_btn = QPushButton("Remove selected")
        rm_btn.clicked.connect(self._remove_selected)
        clr_btn = QPushButton("Clear all")
        clr_btn.clicked.connect(self._clear_all)
        tools.addWidget(rm_btn)
        tools.addWidget(clr_btn)
        tools.addStretch(1)
        root.addLayout(tools)

        # output + concurrency
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output:"))
        self.out_label = QLabel(self.state.data["out_dir"])
        self.out_label.setStyleSheet("color:#3a7afe;")
        out_row.addWidget(self.out_label, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._choose_out)
        out_row.addWidget(browse)
        out_row.addWidget(QLabel("Parallel:"))
        self.conc = QSpinBox()
        self.conc.setRange(1, 5)
        self.conc.setValue(int(self.state.data.get("concurrency", 1)))
        self.conc.valueChanged.connect(self._persist)
        out_row.addWidget(self.conc)
        self.playlist_cb = QCheckBox("Allow playlists")
        self.playlist_cb.setChecked(bool(self.state.data.get("allow_playlist")))
        self.playlist_cb.stateChanged.connect(self._persist)
        out_row.addWidget(self.playlist_cb)
        root.addLayout(out_row)

        # start/stop
        run_row = QHBoxLayout()
        self.start_btn = QPushButton("▶  Start")
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        run_row.addWidget(self.start_btn, 2)
        run_row.addWidget(self.stop_btn, 1)
        root.addLayout(run_row)

    # ------------------------------------------------------------- items -- #
    def _add_row_widget(self, url: str, mode: str, force: bool) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, COL_URL, QTableWidgetItem(url))

        combo = QComboBox()
        combo.addItems(MODES)
        combo.setCurrentText(mode if mode in MODES else "both")
        combo.setToolTip(MODE_TOOLTIP)
        combo.currentTextChanged.connect(self._persist)
        self.table.setCellWidget(r, COL_MODE, combo)

        cb = QCheckBox()
        cb.setChecked(force)
        cb.stateChanged.connect(self._persist)
        cb.setToolTip("Re-encode to H.264 even if the source is already MP4-friendly")
        self.table.setCellWidget(r, COL_FORCE, cb)

        bar = QProgressBar()
        bar.setValue(0)
        bar.setFormat("queued")
        self.table.setCellWidget(r, COL_STATUS, bar)

    def _add_links(self) -> None:
        text = self.paste.toPlainText()
        mode = self.default_mode.currentText()
        added = 0
        for line in text.splitlines():
            url = line.strip()
            if not url or url.startswith("#"):
                continue
            self._add_row_widget(url, mode, False)
            added += 1
        if added:
            self.paste.clear()
            self._persist()
            self.log(f"Added {added} link(s).")

    def _remove_selected(self) -> None:
        for idx in sorted({i.row() for i in self.table.selectedIndexes()},
                          reverse=True):
            self.table.removeRow(idx)
        self._persist()

    def _clear_all(self) -> None:
        self.table.setRowCount(0)
        self._persist()

    def _load_items(self) -> None:
        for it in self.state.data.get("items", []):
            self._add_row_widget(it.get("url", ""), it.get("mode", "video"),
                                 it.get("force_h264", False))

    def _collect_items(self) -> list[dict]:
        items = []
        for r in range(self.table.rowCount()):
            url_item = self.table.item(r, COL_URL)
            combo = self.table.cellWidget(r, COL_MODE)
            cb = self.table.cellWidget(r, COL_FORCE)
            if not url_item:
                continue
            items.append({
                "url": url_item.text(),
                "mode": combo.currentText() if combo else "video",
                "force_h264": cb.isChecked() if cb else False,
            })
        return items

    # --------------------------------------------------------- settings -- #
    def _choose_out(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose output folder",
                                             self.state.data["out_dir"])
        if d:
            self.out_label.setText(d)
            self._persist()

    def _persist(self) -> None:
        self.state.data["items"] = self._collect_items()
        self.state.data["out_dir"] = self.out_label.text()
        self.state.data["concurrency"] = self.conc.value()
        self.state.data["allow_playlist"] = self.playlist_cb.isChecked()
        self.state.save()

    # -------------------------------------------------------------- run -- #
    def _set_status(self, row: int, pct: int, text: str) -> None:
        bar = self.table.cellWidget(row, COL_STATUS)
        if isinstance(bar, QProgressBar):
            bar.setValue(max(0, min(100, pct)))
            bar.setFormat(text)

    def _start(self) -> None:
        ok, msg = self.state.binaries_ok()
        if not ok:
            self.log(f"Cannot start — {msg}")
            return
        items = self._collect_items()
        if not items:
            self.log("Nothing to download — add some links first.")
            return
        self._persist()
        self.state.refresh_binaries()  # pick up any path changes

        self.cancel_event = threading.Event()
        self.pool.setMaxThreadCount(self.conc.value())
        self._total = len(items)
        self._done = 0
        ctx = self.state.ctx(self.out_label.text())

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.log(f"Starting {self._total} download(s), "
                 f"{self.conc.value()} at a time…")

        for row, job in enumerate(items):
            self._set_status(row, 0, "queued")
            worker = DownloadWorker(row, job, ctx, self.cancel_event.is_set)
            worker.signals.progress.connect(self._set_status)
            worker.signals.log.connect(self.log)
            worker.signals.finished.connect(self._on_finished)
            self.pool.start(worker)

    def _stop(self) -> None:
        self.cancel_event.set()
        self.pool.clear()  # drop queued-but-not-started workers
        self.log("Stop requested — finishing/cancelling in-flight items…")
        self.stop_btn.setEnabled(False)

    def _on_finished(self, row: int, ok: bool, message: str) -> None:
        self._set_status(row, 100 if ok else 0, "✓ " + message if ok else message)
        self.log(f"[row {row + 1}] {message}")
        self._done += 1
        if self._done >= self._total:
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.log("Batch complete.")
