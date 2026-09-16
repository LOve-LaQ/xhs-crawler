from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Qt, Signal
from PySide6.QtWidgets import QSplitter, QSplitterHandle


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(int, str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.function(*self.args, **self.kwargs)
            self.signals.result.emit(result)
        except Exception as exc:  # Qt worker boundary must forward errors to the UI.
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()


class DragSplitterHandle(QSplitterHandle):
    """A splitter handle that updates pane sizes directly while dragging."""

    def __init__(self, orientation: Qt.Orientation, parent: QSplitter) -> None:
        super().__init__(orientation, parent)
        self._drag_origin = None
        self._initial_sizes: list[int] = []
        self.setCursor(
            Qt.CursorShape.SizeVerCursor
            if orientation == Qt.Orientation.Vertical
            else Qt.CursorShape.SizeHorCursor
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override name
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._drag_origin = event.globalPosition().toPoint()
        self._initial_sizes = self.splitter().sizes()
        self.grabMouse()
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt override name
        if self._drag_origin is None or len(self._initial_sizes) != 2:
            super().mouseMoveEvent(event)
            return
        current = event.globalPosition().toPoint()
        delta = (
            current.y() - self._drag_origin.y()
            if self.orientation() == Qt.Orientation.Vertical
            else current.x() - self._drag_origin.x()
        )
        total = sum(self._initial_sizes)
        first = max(1, min(self._initial_sizes[0] + delta, total - 1))
        self.splitter().setSizes([first, total - first])
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override name
        if self._drag_origin is not None:
            self.releaseMouse()
            self._drag_origin = None
            self._initial_sizes = []
            event.accept()
            return
        super().mouseReleaseEvent(event)


class DragSplitter(QSplitter):
    def createHandle(self) -> QSplitterHandle:  # noqa: N802 - Qt override name
        return DragSplitterHandle(self.orientation(), self)
