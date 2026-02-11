from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QPoint, QRect, Qt
from PyQt5.QtWidgets import QApplication, QMainWindow, QTabBar, QTabWidget

from Engine.engine import Frame
from GUI.codeeditor import CodeEditorWidget
from GUI.framedisplayer import LedMatrixWidget, deserialize_frame


class DetachableTabBar(QTabBar):
    def __init__(self, host_tabs: QTabWidget, main_window: "QGraphicMainWindow", is_main: bool):
        super().__init__(host_tabs)
        self._host_tabs = host_tabs
        self._main_window = main_window
        self._is_main = is_main
        self._drag_start_pos: QPoint | None = None
        self._drag_index: int | None = None
        self._dragging = False
        self._detached = False

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.pos()
            self._drag_index = self.tabAt(event.pos())
            self._dragging = False
            self._detached = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start_pos is not None:
            if (event.pos() - self._drag_start_pos).manhattanLength() >= QApplication.startDragDistance():
                self._dragging = True
            if self._dragging and self._is_main and not self._detached:
                global_pos = self.mapToGlobal(event.pos())
                if not self._main_window._is_over_main_window(global_pos):
                    if self._drag_index is not None:
                        self._main_window._detach_tab(self._drag_index)
                        self._detached = True
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._dragging:
            index = self.tabAt(event.pos())
            if index != -1:
                global_pos = self.mapToGlobal(event.pos())
                if self._is_main:
                    if not self._main_window._is_over_main_tabs(global_pos):
                        self._main_window._detach_tab(index)
                else:
                    if self._main_window._is_over_main_tabs(global_pos):
                        self._main_window._attach_tab(self._host_tabs, index)
        self._drag_start_pos = None
        self._drag_index = None
        self._dragging = False
        self._detached = False
        super().mouseReleaseEvent(event)


class DockableTabWidget(QTabWidget):
    def __init__(self, main_window: "QGraphicMainWindow", is_main: bool, parent=None):
        super().__init__(parent)
        self.setTabBar(DetachableTabBar(self, main_window, is_main))
        self.tabBar().setMovable(True)


class FloatingTabWindow(QMainWindow):
    def __init__(self, main_window: "QGraphicMainWindow", title: str, widget, parent=None):
        super().__init__(parent)
        self._main_window = main_window
        self.tabs = DockableTabWidget(main_window, is_main=False)
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(QTabWidget.North)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.addTab(widget, title)
        self.setCentralWidget(self.tabs)
        self.setWindowTitle(f"QGraphic - {title}")
        self.resize(1000, 720)

    def closeEvent(self, event):
        self._main_window._attach_all_from_floating(self)
        event.accept()


class QGraphicMainWindow(QMainWindow):
    def __init__(self, frame: Frame | None = None, canvas_file: Path | None = None, parent=None):
        super().__init__(parent)

        self.setWindowTitle("QGraphic")
        self.setMinimumSize(1200, 720)
        self.resize(1600, 900)

        if frame is None:
            frame = Frame()

        if canvas_file is not None:
            data = canvas_file.read_bytes()
            frame.display = deserialize_frame(data)

        self._floating_windows: list[FloatingTabWindow] = []

        self.top_tabs = DockableTabWidget(self, is_main=True)
        self.top_tabs.setDocumentMode(True)
        self.top_tabs.setTabPosition(QTabWidget.North)
        self.top_tabs.setObjectName("topTabs")
        self.top_tabs.tabBar().setExpanding(True)
        self.top_tabs.tabBar().setDrawBase(False)

        self.canvas = LedMatrixWidget(frame)
        self.code = CodeEditorWidget()
        self.code.set_publish_handler(self._on_publish)
        self.code.set_send_handler(self._on_send)

        self.top_tabs.addTab(self.canvas, "Canvas")
        self.top_tabs.addTab(self.code, "Code")

        self.setCentralWidget(self.top_tabs)

        # Top-level tab chrome should match the app aesthetic.
        self.setStyleSheet(
            """
            QMainWindow { background: #0F111A; }

            /* Top-level Canvas/Code tabs */
            #topTabs::pane { border: none; }
            #topTabs > QWidget { background: #0F111A; }

            #topTabs QTabBar {
                background: #1A1F2E;
                border-bottom: 1px solid #2A3142;
            }
            #topTabs QTabBar::tab {
                background: #1A1F2E;
                color: #6B7394;
                padding: 10px 18px;
                border: none;
                margin: 0px;
            }
            #topTabs QTabBar::tab:selected {
                background: #242B3D;
                color: #C8D3F5;
            }
            """
        )

    def _on_publish(self, frame: Frame) -> None:
        self.canvas.display_frame(frame)
        self.top_tabs.setCurrentWidget(self.canvas)

    def _on_send(self, path: str) -> None:
        self.canvas.send_qgc_file(path)

    def _global_rect(self, widget) -> QRect:
        top_left = widget.mapToGlobal(QPoint(0, 0))
        bottom_right = widget.mapToGlobal(QPoint(widget.width(), widget.height()))
        return QRect(top_left, bottom_right)

    def _is_over_main_tabs(self, global_pos: QPoint) -> bool:
        return self._global_rect(self.top_tabs.tabBar()).contains(global_pos)

    def _is_over_main_window(self, global_pos: QPoint) -> bool:
        return self._global_rect(self).contains(global_pos)

    def _detach_tab(self, index: int) -> None:
        widget = self.top_tabs.widget(index)
        if widget is None:
            return
        title = self.top_tabs.tabText(index)
        self.top_tabs.removeTab(index)
        floating = FloatingTabWindow(self, title, widget, parent=None)
        self._floating_windows.append(floating)
        floating.show()

    def _floating_for_tabs(self, tabs: QTabWidget) -> FloatingTabWindow | None:
        for window in self._floating_windows:
            if window.tabs is tabs:
                return window
        return None

    def _attach_tab(self, source_tabs: QTabWidget, index: int) -> None:
        widget = source_tabs.widget(index)
        if widget is None:
            return
        title = source_tabs.tabText(index)
        source_tabs.removeTab(index)
        self.top_tabs.addTab(widget, title)
        self.top_tabs.setCurrentWidget(widget)
        floating = self._floating_for_tabs(source_tabs)
        if floating and source_tabs.count() == 0:
            self._floating_windows.remove(floating)
            floating.close()

    def _attach_all_from_floating(self, floating: FloatingTabWindow) -> None:
        tabs = floating.tabs
        while tabs.count() > 0:
            widget = tabs.widget(0)
            title = tabs.tabText(0)
            tabs.removeTab(0)
            if widget is not None:
                self.top_tabs.addTab(widget, title)
                self.top_tabs.setCurrentWidget(widget)
        if floating in self._floating_windows:
            self._floating_windows.remove(floating)
