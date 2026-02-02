import sys
import os
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QFrame,
    QColorDialog,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsEllipseItem,
    QPushButton,
    QButtonGroup,
)
from PyQt5.QtGui import QColor, QBrush, QPen, QPainter
from PyQt5.QtCore import Qt, QRectF, QTimer

# Ensure parent directory is in sys.path for import
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from Engine.engine import Frame


def rgb565_to_qcolor(r5: int, g6: int, b5: int) -> QColor:
    r = (r5 << 3) | (r5 >> 2)
    g = (g6 << 2) | (g6 >> 4)
    b = (b5 << 3) | (b5 >> 2)
    return QColor(r, g, b)


def qcolor_to_rgb565(color: QColor) -> tuple[int, int, int]:
    r5 = int(round(color.red() / 255 * 31))
    g6 = int(round(color.green() / 255 * 63))
    b5 = int(round(color.blue() / 255 * 31))
    return r5, g6, b5


class PixelItem(QGraphicsEllipseItem):
    def __init__(self, x: int, y: int, rect: QRectF, parent=None):
        super().__init__(rect, parent)
        self.x = x
        self.y = y
        self.setPen(QPen(QColor(30, 30, 30), 1))
        self.setBrush(QBrush(QColor(0, 0, 0)))


class LedMatrixScene(QGraphicsScene):
    def __init__(self, frame: Frame, cell_size: int = 18, margin: int = 4):
        super().__init__()
        self.frame = frame
        self.cell_size = cell_size
        self.margin = margin
        self.current_color = (31, 63, 31)
        self.items_grid: list[list[PixelItem]] = []
        self._build_grid()

    def _build_grid(self) -> None:
        self.clear()
        self.items_grid = []
        width = 64 * (self.cell_size + self.margin) - self.margin
        height = 32 * (self.cell_size + self.margin) - self.margin
        self.setSceneRect(0, 0, width, height)

        for y in range(32):
            row: list[PixelItem] = []
            for x in range(64):
                px = x * (self.cell_size + self.margin)
                py = y * (self.cell_size + self.margin)
                rect = QRectF(px, py, self.cell_size, self.cell_size)
                item = PixelItem(x, y, rect)
                r, g, b = self.frame.display[y][x]
                item.setBrush(QBrush(rgb565_to_qcolor(r, g, b)))
                self.addItem(item)
                row.append(item)
            self.items_grid.append(row)

    def set_current_color(self, r5: int, g6: int, b5: int) -> None:
        self.current_color = (r5, g6, b5)

    def mousePressEvent(self, event):
        view = self.views()[0] if self.views() else None
        if view is not None and getattr(view, "tool_mode", "pen") == "pen":
            item = self.itemAt(event.scenePos(), view.transform())
            if isinstance(item, PixelItem):
                r5, g6, b5 = self.current_color
                self.frame.display[item.y][item.x] = (r5, g6, b5)
                item.setBrush(QBrush(rgb565_to_qcolor(r5, g6, b5)))
        super().mousePressEvent(event)


class LedMatrixView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.tool_mode = "pen"  # pen | pan
        self.setDragMode(QGraphicsView.NoDrag)

    def set_tool_mode(self, mode: str) -> None:
        self.tool_mode = mode
        if mode == "pan":
            self.setDragMode(QGraphicsView.ScrollHandDrag)
        else:
            self.setDragMode(QGraphicsView.NoDrag)

    def wheelEvent(self, event):
        if self.tool_mode != "pan":
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.2 if delta > 0 else 1 / 1.2
        self.scale(factor, factor)


class LedMatrixWidget(QMainWindow):
    def __init__(self, frame: Frame, parent=None):
        super().__init__(parent)
        self.frame = frame
        self.setWindowTitle("QGraphic Frame Editor")
        self.setMinimumSize(1200, 720)

        self.scene = LedMatrixScene(frame)
        self.view = LedMatrixView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing, True)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        self.view.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.view.setStyleSheet("background: #121212; border: none;")

        controls = self._build_controls()
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.addWidget(controls)
        layout.addWidget(self.view, 1)
        self.setCentralWidget(root)

        self._apply_styles()
        QTimer.singleShot(0, self._fit_view)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_view()

    def _fit_view(self) -> None:
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def _build_controls(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(320)
        layout = QVBoxLayout(panel)
        layout.setSpacing(12)

        title = QLabel("Color Picker")
        title.setObjectName("panelTitle")

        self.color_dialog = QColorDialog()
        self.color_dialog.setOption(QColorDialog.DontUseNativeDialog, True)
        self.color_dialog.setOption(QColorDialog.NoButtons, True)
        self.color_dialog.currentColorChanged.connect(self._on_qcolor_changed)

        rgb_label = QLabel("RGB565 (r g b)")
        self.rgb_input = QLineEdit("31 63 31")
        self.rgb_input.setPlaceholderText("e.g. 31 63 31")
        self.rgb_input.editingFinished.connect(self._on_rgb_input)

        self.preview = QFrame()
        self.preview.setFixedHeight(48)
        self.preview.setObjectName("colorPreview")
        self._set_preview_color(31, 63, 31)

        tool_label = QLabel("Tool")
        self.pen_btn = QPushButton("Pen")
        self.pan_btn = QPushButton("Pan/Zoom")
        self.pen_btn.setCheckable(True)
        self.pan_btn.setCheckable(True)
        self.pen_btn.setChecked(True)
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_group.addButton(self.pen_btn)
        self.tool_group.addButton(self.pan_btn)
        self.pen_btn.clicked.connect(lambda: self.view.set_tool_mode("pen"))
        self.pan_btn.clicked.connect(lambda: self.view.set_tool_mode("pan"))

        layout.addWidget(title)
        layout.addWidget(self.color_dialog)
        layout.addWidget(rgb_label)
        layout.addWidget(self.rgb_input)
        layout.addWidget(self.preview)
        layout.addWidget(tool_label)
        layout.addWidget(self.pen_btn)
        layout.addWidget(self.pan_btn)
        layout.addStretch(1)

        return panel

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget { color: #EDEDED; font-family: Segoe UI, Arial; font-size: 12px; }
            #panelTitle { font-size: 16px; font-weight: 600; margin-bottom: 4px; }
            QLineEdit { background: #1E1E1E; border: 1px solid #333; padding: 6px; border-radius: 6px; }
            #colorPreview { border: 1px solid #333; border-radius: 8px; }
            QPushButton, QAbstractButton { color: #000000; }
            """
        )

    def _on_qcolor_changed(self, color: QColor) -> None:
        r5, g6, b5 = qcolor_to_rgb565(color)
        self.scene.set_current_color(r5, g6, b5)
        self._set_preview_color(r5, g6, b5)
        self._set_rgb_input(r5, g6, b5)

    def _on_rgb_input(self) -> None:
        text = self.rgb_input.text().strip()
        parts = [p for p in text.replace(",", " ").split() if p]
        if len(parts) != 3:
            return
        try:
            r5, g6, b5 = (int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError:
            return
        r5 = max(0, min(31, r5))
        g6 = max(0, min(63, g6))
        b5 = max(0, min(31, b5))
        self.scene.set_current_color(r5, g6, b5)
        self._set_preview_color(r5, g6, b5)
        self.color_dialog.setCurrentColor(rgb565_to_qcolor(r5, g6, b5))

    def _set_rgb_input(self, r5: int, g6: int, b5: int) -> None:
        self.rgb_input.blockSignals(True)
        self.rgb_input.setText(f"{r5} {g6} {b5}")
        self.rgb_input.blockSignals(False)

    def _set_preview_color(self, r5: int, g6: int, b5: int) -> None:
        color = rgb565_to_qcolor(r5, g6, b5)
        self.preview.setStyleSheet(
            f"background: rgb({color.red()}, {color.green()}, {color.blue()});"
        )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    frame = Frame()
    w = LedMatrixWidget(frame)
    w.showMaximized()
    w.show()
    sys.exit(app.exec_())
