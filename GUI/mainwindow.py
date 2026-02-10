from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMainWindow, QTabWidget

from Engine.engine import Frame
from GUI.codeeditor import CodeEditorWidget
from GUI.framedisplayer import LedMatrixWidget, deserialize_frame


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

        self.top_tabs = QTabWidget()
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
