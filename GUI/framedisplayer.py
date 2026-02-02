import sys
import os
import json
import zlib
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
    QCheckBox,
    QFileDialog,
    QMessageBox,
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


QGC_MAGIC = b"QGC1"


def serialize_frame(frame: Frame) -> bytes:
    payload = {
        "w": 64,
        "h": 32,
        "pixels": frame.display,
    }
    raw = json.dumps(payload).encode("utf-8")
    compressed = zlib.compress(raw, level=6)
    return QGC_MAGIC + compressed


def deserialize_frame(data: bytes) -> list[list[tuple[int, int, int]]]:
    if not data.startswith(QGC_MAGIC):
        raise ValueError("Invalid .qgc file")
    raw = zlib.decompress(data[len(QGC_MAGIC):])
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("w") != 64 or payload.get("h") != 32:
        raise ValueError("Unsupported frame size")
    return payload["pixels"]


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
        self.pen_drag_paint = False
        self._rect_preview = None
        self._rect_start = None
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

    def refresh_from_frame(self) -> None:
        for y in range(32):
            for x in range(64):
                r, g, b = self.frame.display[y][x]
                self.items_grid[y][x].setBrush(QBrush(rgb565_to_qcolor(r, g, b)))

    def set_current_color(self, r5: int, g6: int, b5: int) -> None:
        self.current_color = (r5, g6, b5)

    def set_pen_drag_paint(self, enabled: bool) -> None:
        self.pen_drag_paint = enabled

    def mousePressEvent(self, event):
        view = self.views()[0] if self.views() else None
        if view is not None:
            tool = getattr(view, "tool_mode", "pen")
            if tool == "pen":
                self._paint_at(event.scenePos(), view)
            elif tool == "rect":
                self._rect_start = event.scenePos()
                if self._rect_preview is None:
                    self._rect_preview = self.addRect(
                        QRectF(self._rect_start, self._rect_start),
                        QPen(QColor(220, 220, 220), 2, Qt.DashLine),
                        QBrush(Qt.transparent),
                    )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        view = self.views()[0] if self.views() else None
        if view is not None:
            tool = getattr(view, "tool_mode", "pen")
            if tool == "pen" and self.pen_drag_paint and (event.buttons() & Qt.LeftButton):
                self._paint_at(event.scenePos(), view)
            elif tool == "rect" and self._rect_preview is not None and self._rect_start is not None:
                rect = QRectF(self._rect_start, event.scenePos()).normalized()
                self._rect_preview.setRect(rect)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        view = self.views()[0] if self.views() else None
        if view is not None:
            tool = getattr(view, "tool_mode", "pen")
            if tool == "rect" and self._rect_preview is not None and self._rect_start is not None:
                rect = self._rect_preview.rect()
                self.removeItem(self._rect_preview)
                self._rect_preview = None
                self._apply_rect(rect)
                self._rect_start = None
        super().mouseReleaseEvent(event)

    def _paint_at(self, pos, view) -> None:
        item = self.itemAt(pos, view.transform())
        if isinstance(item, PixelItem):
            r5, g6, b5 = self.current_color
            self.frame.display[item.y][item.x] = (r5, g6, b5)
            item.setBrush(QBrush(rgb565_to_qcolor(r5, g6, b5)))

    def _apply_rect(self, rect: QRectF) -> None:
        if rect.isNull():
            return
        r5, g6, b5 = self.current_color
        x1 = int(rect.left() // (self.cell_size + self.margin))
        y1 = int(rect.top() // (self.cell_size + self.margin))
        x2 = int(rect.right() // (self.cell_size + self.margin))
        y2 = int(rect.bottom() // (self.cell_size + self.margin))
        x1 = max(0, min(63, x1))
        x2 = max(0, min(63, x2))
        y1 = max(0, min(31, y1))
        y2 = max(0, min(31, y2))
        for y in range(min(y1, y2), max(y1, y2) + 1):
            for x in range(min(x1, x2), max(x1, x2) + 1):
                self.frame.display[y][x] = (r5, g6, b5)
                self.items_grid[y][x].setBrush(QBrush(rgb565_to_qcolor(r5, g6, b5)))


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
        self.rect_btn = QPushButton("Rect")
        self.pen_btn.setCheckable(True)
        self.pan_btn.setCheckable(True)
        self.rect_btn.setCheckable(True)
        self.pen_btn.setChecked(True)
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_group.addButton(self.pen_btn)
        self.tool_group.addButton(self.pan_btn)
        self.tool_group.addButton(self.rect_btn)
        self.pen_btn.clicked.connect(lambda: self.view.set_tool_mode("pen"))
        self.pan_btn.clicked.connect(lambda: self.view.set_tool_mode("pan"))
        self.rect_btn.clicked.connect(lambda: self.view.set_tool_mode("rect"))

        self.pen_drag_toggle = QCheckBox("Drag paint")
        self.pen_drag_toggle.setChecked(False)
        self.pen_drag_toggle.toggled.connect(self.scene.set_pen_drag_paint)

        file_label = QLabel("File")
        self.save_btn = QPushButton("Save .qgc")
        self.load_btn = QPushButton("Load .qgc")
        self.save_btn.clicked.connect(self._save_qgc)
        self.load_btn.clicked.connect(self._load_qgc)

        layout.addWidget(title)
        layout.addWidget(self.color_dialog)
        layout.addWidget(rgb_label)
        layout.addWidget(self.rgb_input)
        layout.addWidget(self.preview)
        layout.addWidget(tool_label)
        layout.addWidget(self.pen_btn)
        layout.addWidget(self.pan_btn)
        layout.addWidget(self.rect_btn)
        layout.addWidget(self.pen_drag_toggle)
        layout.addWidget(file_label)
        layout.addWidget(self.save_btn)
        layout.addWidget(self.load_btn)
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

    def _save_qgc(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Frame",
            "",
            "QGraphic Frame (*.qgc)",
        )
        if not filename:
            return
        if not filename.lower().endswith(".qgc"):
            filename += ".qgc"
        try:
            data = serialize_frame(self.frame)
            with open(filename, "wb") as f:
                f.write(data)
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))

    def _load_qgc(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Load Frame",
            "",
            "QGraphic Frame (*.qgc)",
        )
        if not filename:
            return
        try:
            with open(filename, "rb") as f:
                data = f.read()
            pixels = deserialize_frame(data)
            self.frame.display = pixels
            self.scene.refresh_from_frame()
        except Exception as exc:
            QMessageBox.critical(self, "Load Failed", str(exc))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    frame = Frame()
    w = LedMatrixWidget(frame)
    w.showMaximized()
    w.show()
    sys.exit(app.exec_())
