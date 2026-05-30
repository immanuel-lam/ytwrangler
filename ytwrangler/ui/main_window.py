"""Main window: tabs + a shared log pane + binary settings dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QPlainTextEdit, QPushButton, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt

from ..session import AppState
from .batch_tab import BatchTab
from .single_tab import SingleTab


class SettingsDialog(QDialog):
    def __init__(self, state: AppState, parent=None) -> None:
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("Binary settings")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Leave blank to auto-detect from PATH."))

        self.ytdlp = self._path_row(lay, "yt-dlp path:",
                                    state.data.get("ytdlp_path", ""))
        self.ffmpeg = self._path_row(lay, "ffmpeg path:",
                                     state.data.get("ffmpeg_path", ""))

        btns = QHBoxLayout()
        btns.addStretch(1)
        save = QPushButton("Save")
        save.clicked.connect(self._save)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(save)
        btns.addWidget(cancel)
        lay.addLayout(btns)

    def _path_row(self, parent_layout, label: str, value: str) -> QLineEdit:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        edit = QLineEdit(value)
        row.addWidget(edit, 1)
        browse = QPushButton("…")
        browse.clicked.connect(lambda: self._pick(edit))
        row.addWidget(browse)
        parent_layout.addLayout(row)
        return edit

    def _pick(self, edit: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select binary")
        if path:
            edit.setText(path)

    def _save(self) -> None:
        self.state.data["ytdlp_path"] = self.ytdlp.text().strip()
        self.state.data["ffmpeg_path"] = self.ffmpeg.text().strip()
        self.state.refresh_binaries()
        self.state.save()
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self.setWindowTitle("ytwrangler")
        self.resize(900, 680)

        self.log_pane = QPlainTextEdit()
        self.log_pane.setReadOnly(True)
        self.log_pane.setMaximumBlockCount(5000)

        tabs = QTabWidget()
        tabs.addTab(BatchTab(state, self.log), "Batch")
        tabs.addTab(SingleTab(state, self.log), "Single")

        split = QSplitter(Qt.Vertical)
        split.addWidget(tabs)
        split.addWidget(self.log_pane)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)

        container = QWidget()
        outer = QVBoxLayout(container)
        outer.addWidget(self._top_bar())
        outer.addWidget(split, 1)
        self.setCentralWidget(container)

        ok, msg = state.binaries_ok()
        self.log(msg if ok else f"⚠ {msg} — set paths via Settings.")

    def _top_bar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        ok, msg = self.state.binaries_ok()
        self.status_label = QLabel(msg)
        self.status_label.setStyleSheet(
            "color:#1f9d55;" if ok else "color:#d23;")
        row.addWidget(self.status_label, 1)
        settings = QPushButton("Settings…")
        settings.clicked.connect(self._open_settings)
        row.addWidget(settings)
        return bar

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.state, self)
        if dlg.exec():
            ok, msg = self.state.binaries_ok()
            self.status_label.setText(msg)
            self.status_label.setStyleSheet(
                "color:#1f9d55;" if ok else "color:#d23;")
            self.log("Settings saved. " + msg)

    def log(self, text: str) -> None:
        self.log_pane.appendPlainText(text)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.state.save()
        super().closeEvent(event)
