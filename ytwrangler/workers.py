"""Qt thread-pool workers wrapping the pipeline. Signals are delivered to the
GUI thread via Qt's queued connections, so slots can touch widgets safely."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from . import pipeline


class WorkerSignals(QObject):
    progress = Signal(int, int, str)   # row, percent, status
    log = Signal(str)
    finished = Signal(int, bool, str)  # row, ok, message


class DownloadWorker(QRunnable):
    """Downloads + converts one item. `row` identifies the table row (-1 for the
    single-download tab)."""

    def __init__(self, row: int, job: dict, ctx: dict,
                 should_cancel: Callable[[], bool]) -> None:
        super().__init__()
        self.row = row
        self.job = job
        self.ctx = ctx
        self.should_cancel = should_cancel
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        def on_prog(pct: float, status: str) -> None:
            self.signals.progress.emit(self.row, int(pct), status)

        def on_log(line: str) -> None:
            self.signals.log.emit(line)

        try:
            outputs = pipeline.process_item(
                self.ctx,
                url=self.job["url"],
                mode=self.job["mode"],
                force_h264=self.job.get("force_h264", False),
                fmt=self.job.get("fmt"),
                on_progress=on_prog,
                on_log=on_log,
                should_cancel=self.should_cancel,
            )
            names = ", ".join(p.name for p in outputs)
            self.signals.finished.emit(self.row, True, f"Done: {names}")
        except pipeline.CancelledError:
            self.signals.finished.emit(self.row, False, "Cancelled")
        except Exception as e:  # noqa: BLE001 — surface any failure to the UI
            self.signals.finished.emit(self.row, False, f"Error: {e}")


class FnSignals(QObject):
    done = Signal(object, str)  # result, error-message


class FnWorker(QRunnable):
    """Runs an arbitrary callable off the GUI thread (e.g. fetching formats)."""

    def __init__(self, fn: Callable[[], object]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = FnSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            self.signals.done.emit(self.fn(), "")
        except Exception as e:  # noqa: BLE001
            self.signals.done.emit(None, str(e))
