import sys
import os
import json
import zlib
import copy
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
    QShortcut,
    QTabWidget,
    QScrollArea,
)
from PyQt5.QtGui import QKeySequence
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
        self.default_pen = QPen(QColor(30, 30, 30), 1)
        self.selected_pen = QPen(QColor(255, 220, 80), 2)
        self.setPen(self.default_pen)
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
        self._select_preview = None
        self._select_start = None
        self._line_preview = None
        self._line_start = None
        self._line_end = None
        self._action_active = False
        self._bucket_pending = None
        self._selection: set[tuple[int, int]] = set()
        self._select_mode = "rect"  # rect | pen
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

    def set_select_mode(self, mode: str) -> None:
        self._select_mode = mode

    def clear_selection(self) -> None:
        if not self._selection:
            return
        for (x, y) in self._selection:
            self.items_grid[y][x].setPen(self.items_grid[y][x].default_pen)
        self._selection.clear()

    def mousePressEvent(self, event):
        view = self.views()[0] if self.views() else None
        if view is not None:
            tool = getattr(view, "tool_mode", "pen")
            if tool == "pen" and event.button() == Qt.LeftButton:
                self._begin_action(view)
                if self._selection:
                    self._apply_selection_color()
                else:
                    self._paint_at(event.scenePos(), view)
            elif tool == "rect" and event.button() == Qt.LeftButton:
                self._begin_action(view)
                self._rect_start = event.scenePos()
                if self._rect_preview is None:
                    self._rect_preview = self.addRect(
                        QRectF(self._rect_start, self._rect_start),
                        QPen(QColor(220, 220, 220), 2, Qt.DashLine),
                        QBrush(Qt.transparent),
                    )
            elif tool == "line" and event.button() == Qt.LeftButton:
                self._begin_action(view)
                self._line_start = event.scenePos()
                if self._line_preview is None:
                    self._line_preview = self.addLine(
                        self._line_start.x(),
                        self._line_start.y(),
                        self._line_start.x(),
                        self._line_start.y(),
                        QPen(QColor(220, 220, 220), 2, Qt.DashLine),
                    )
            elif tool == "bucket" and event.button() == Qt.LeftButton:
                self._begin_action(view)
                self._bucket_pending = event.scenePos()
            elif tool == "select" and event.button() == Qt.LeftButton:
                if self._select_mode == "rect":
                    self._select_start = event.scenePos()
                    if self._select_preview is None:
                        self._select_preview = self.addRect(
                            QRectF(self._select_start, self._select_start),
                            QPen(QColor(120, 200, 255), 2, Qt.DashLine),
                            QBrush(Qt.transparent),
                        )
                else:
                    self._select_at(event.scenePos(), view)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        view = self.views()[0] if self.views() else None
        if view is not None:
            tool = getattr(view, "tool_mode", "pen")
            if tool == "pen" and self.pen_drag_paint and (event.buttons() & Qt.LeftButton):
                if self._selection:
                    self._apply_selection_color()
                else:
                    self._paint_at(event.scenePos(), view)
            elif tool == "rect" and self._rect_preview is not None and self._rect_start is not None:
                rect = QRectF(self._rect_start, event.scenePos()).normalized()
                if event.modifiers() & Qt.ShiftModifier:
                    rect = self._square_rect(self._rect_start, event.scenePos())
                self._rect_preview.setRect(rect)
            elif tool == "line" and self._line_preview is not None and self._line_start is not None:
                end = event.scenePos()
                if event.modifiers() & Qt.ShiftModifier:
                    end = self._snap_line_end(self._line_start, end)
                self._line_end = end
                self._line_preview.setLine(
                    self._line_start.x(),
                    self._line_start.y(),
                    end.x(),
                    end.y(),
                )
            elif tool == "select" and self._select_mode == "rect" and self._select_preview is not None and self._select_start is not None:
                rect = QRectF(self._select_start, event.scenePos()).normalized()
                self._select_preview.setRect(rect)
            elif tool == "select" and self._select_mode == "pen" and (event.buttons() & Qt.LeftButton):
                self._select_at(event.scenePos(), view)
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
                self._commit_action(view)
            elif tool == "line" and self._line_preview is not None and self._line_start is not None:
                line = self._line_preview.line()
                self.removeItem(self._line_preview)
                self._line_preview = None
                end = self._line_end if self._line_end is not None else line.p2()
                self._apply_line(line.x1(), line.y1(), end.x(), end.y())
                self._line_start = None
                self._line_end = None
                self._commit_action(view)
            elif tool == "bucket" and self._bucket_pending is not None:
                self._apply_bucket(self._bucket_pending)
                self._bucket_pending = None
                self._commit_action(view)
            elif tool == "select" and self._select_mode == "rect" and self._select_preview is not None and self._select_start is not None:
                rect = self._select_preview.rect()
                self.removeItem(self._select_preview)
                self._select_preview = None
                self._apply_select_rect(rect)
                self._select_start = None
            elif tool == "pen" and self._action_active:
                self._commit_action(view)
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

    def _square_rect(self, start, end) -> QRectF:
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        size = min(abs(dx), abs(dy))
        x2 = start.x() + (size if dx >= 0 else -size)
        y2 = start.y() + (size if dy >= 0 else -size)
        return QRectF(start, end.__class__(x2, y2)).normalized()

    def _begin_action(self, view) -> None:
        if self._action_active:
            return
        if hasattr(self, "on_begin_action"):
            self.on_begin_action()
        self._action_active = True

    def _commit_action(self, view) -> None:
        if not self._action_active:
            return
        if hasattr(self, "on_commit_action"):
            self.on_commit_action()
        self._action_active = False

    def _apply_line(self, x1: float, y1: float, x2: float, y2: float) -> None:
        r5, g6, b5 = self.current_color
        gx1, gy1 = self._scene_to_grid(x1, y1)
        gx2, gy2 = self._scene_to_grid(x2, y2)
        self.frame.makeLine(gx1, gy1, gx2, gy2, r5, g6, b5)
        self.refresh_from_frame()

    def _snap_line_end(self, start, end):
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        if dx == 0 and dy == 0:
            return end
        adx = abs(dx)
        ady = abs(dy)
        if adx > ady * 2:
            return end.__class__(end.x(), start.y())
        if ady > adx * 2:
            return end.__class__(start.x(), end.y())
        m = max(adx, ady)
        return end.__class__(start.x() + (m if dx >= 0 else -m), start.y() + (m if dy >= 0 else -m))

    def _apply_bucket(self, pos) -> None:
        gx, gy = self._scene_to_grid(pos.x(), pos.y())
        target = self.frame.display[gy][gx]
        replacement = self.current_color
        if target == replacement:
            return
        w, h = 64, 32
        stack = [(gx, gy)]
        visited = set()
        while stack:
            x, y = stack.pop()
            if (x, y) in visited:
                continue
            visited.add((x, y))
            if self.frame.display[y][x] != target:
                continue
            self.frame.display[y][x] = replacement
            if x > 0:
                stack.append((x - 1, y))
            if x < w - 1:
                stack.append((x + 1, y))
            if y > 0:
                stack.append((x, y - 1))
            if y < h - 1:
                stack.append((x, y + 1))
        self.refresh_from_frame()

    def _apply_selection_color(self) -> None:
        r5, g6, b5 = self.current_color
        for (x, y) in self._selection:
            self.frame.display[y][x] = (r5, g6, b5)
            self.items_grid[y][x].setBrush(QBrush(rgb565_to_qcolor(r5, g6, b5)))

    def _select_at(self, pos, view) -> None:
        item = self.itemAt(pos, view.transform())
        if isinstance(item, PixelItem):
            self._add_to_selection(item.x, item.y)

    def _apply_select_rect(self, rect: QRectF) -> None:
        if rect.isNull():
            return
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
                self._add_to_selection(x, y)

    def _add_to_selection(self, x: int, y: int) -> None:
        if (x, y) in self._selection:
            return
        self._selection.add((x, y))
        self.items_grid[y][x].setPen(self.items_grid[y][x].selected_pen)

    def _scene_to_grid(self, x: float, y: float) -> tuple[int, int]:
        gx = int(x // (self.cell_size + self.margin))
        gy = int(y // (self.cell_size + self.margin))
        gx = max(0, min(63, gx))
        gy = max(0, min(31, gy))
        return gx, gy


class LedMatrixView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.tool_mode = "pen"  # pen | pan | rect | line | bucket | select
        self.setDragMode(QGraphicsView.NoDrag)
        self._temp_pan = False

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space and not self._temp_pan:
            self._temp_pan = True
            if hasattr(self, "on_temp_pan_start"):
                self.on_temp_pan_start()
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and self._temp_pan:
            self._temp_pan = False
            if hasattr(self, "on_temp_pan_end"):
                self.on_temp_pan_end()
        super().keyReleaseEvent(event)

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
        self.setWindowTitle("QGraphic Frame Editor")
        self.setMinimumSize(1200, 720)
        self.resize(1920, 1080)

        self.tabs: list[dict] = []
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self._close_tab)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        self.tab_widget.setMinimumWidth(720)

        self._add_tab("Frame 1", frame)

        controls = self._build_controls()
        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setFrameShape(QFrame.NoFrame)
        controls_scroll.setWidget(controls)
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.addWidget(controls_scroll)
        layout.addWidget(self.tab_widget, 1)
        self.setCentralWidget(root)

        self._apply_styles()
        QTimer.singleShot(0, self._fit_view)

        self._temp_pan_prev_tool: dict | None = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_view()

    def _fit_view(self) -> None:
        view = self.current_view()
        scene = self.current_scene()
        if view and scene:
            view.fitInView(scene.sceneRect(), Qt.KeepAspectRatio)

    def _add_tab(self, title: str, frame: Frame | None = None) -> None:
        frame = frame or Frame()
        scene = LedMatrixScene(frame)
        view = LedMatrixView(scene)
        view.setRenderHint(QPainter.Antialiasing, True)
        view.setFocusPolicy(Qt.StrongFocus)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        view.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        view.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        view.setStyleSheet("background: #121212; border: none;")

        tab = {
            "frame": frame,
            "scene": scene,
            "view": view,
            "undo": [],
            "redo": [],
            "action_before": None,
            "temp_pan_prev_tool": None,
        }
        scene.on_begin_action = lambda t=tab: self.begin_action(t)
        scene.on_commit_action = lambda t=tab: self.commit_action(t)
        view.on_temp_pan_start = lambda t=tab: self._temp_pan_start(t)
        view.on_temp_pan_end = lambda t=tab: self._temp_pan_end(t)

        self.tabs.append(tab)
        self.tab_widget.addTab(view, title)
        self.tab_widget.setCurrentWidget(view)

    def _close_tab(self, index: int) -> None:
        if self.tab_widget.count() <= 1:
            return
        widget = self.tab_widget.widget(index)
        self.tab_widget.removeTab(index)
        for i, tab in enumerate(self.tabs):
            if tab["view"] is widget:
                self.tabs.pop(i)
                break

    def _on_tab_changed(self, index: int) -> None:
        tab = self.current_tab()
        if not tab:
            return
        if hasattr(self, "pen_drag_toggle"):
            self.pen_drag_toggle.setChecked(tab["scene"].pen_drag_paint)
        self._fit_view()

    def _build_controls(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(320)
        panel.setObjectName("controlPanel")
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
        self.line_btn = QPushButton("Line")
        self.bucket_btn = QPushButton("Bucket")
        self.select_btn = QPushButton("Select")
        self.pen_btn.setCheckable(True)
        self.pan_btn.setCheckable(True)
        self.rect_btn.setCheckable(True)
        self.line_btn.setCheckable(True)
        self.bucket_btn.setCheckable(True)
        self.select_btn.setCheckable(True)
        self.pen_btn.setChecked(True)
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_group.addButton(self.pen_btn)
        self.tool_group.addButton(self.pan_btn)
        self.tool_group.addButton(self.rect_btn)
        self.tool_group.addButton(self.line_btn)
        self.tool_group.addButton(self.bucket_btn)
        self.tool_group.addButton(self.select_btn)
        self.pen_btn.clicked.connect(lambda: self._set_tool("pen"))
        self.pan_btn.clicked.connect(lambda: self._set_tool("pan"))
        self.rect_btn.clicked.connect(lambda: self._set_tool("rect"))
        self.line_btn.clicked.connect(lambda: self._set_tool("line"))
        self.bucket_btn.clicked.connect(lambda: self._set_tool("bucket"))
        self.select_btn.clicked.connect(lambda: self._set_tool("select"))

        select_mode_label = QLabel("Select Mode")
        self.select_rect_btn = QPushButton("Rect")
        self.select_pen_btn = QPushButton("Pen")
        self.select_rect_btn.setCheckable(True)
        self.select_pen_btn.setCheckable(True)
        self.select_rect_btn.setChecked(True)
        self.select_group = QButtonGroup(self)
        self.select_group.setExclusive(True)
        self.select_group.addButton(self.select_rect_btn)
        self.select_group.addButton(self.select_pen_btn)
        self.select_rect_btn.clicked.connect(lambda: self._set_select_mode("rect"))
        self.select_pen_btn.clicked.connect(lambda: self._set_select_mode("pen"))

        self.deselect_btn = QPushButton("Deselect")
        self.deselect_btn.clicked.connect(self._deselect)

        self.pen_drag_toggle = QCheckBox("Drag paint")
        self.pen_drag_toggle.setChecked(False)
        self.pen_drag_toggle.toggled.connect(self._set_pen_drag)

        file_label = QLabel("File")
        self.save_btn = QPushButton("Save .qgc")
        self.load_btn = QPushButton("Load .qgc")
        self.new_tab_btn = QPushButton("New Tab")
        self.new_tab_btn.clicked.connect(lambda: self._add_tab(f"Frame {self.tab_widget.count() + 1}"))
        self.save_btn.clicked.connect(self._save_qgc)
        self.load_btn.clicked.connect(self._load_qgc)

        history_label = QLabel("History")
        self.undo_btn = QPushButton("Undo")
        self.redo_btn = QPushButton("Redo")
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn.clicked.connect(self.redo)

        self._install_shortcuts()

        layout.addWidget(title)
        layout.addWidget(self.color_dialog)
        layout.addWidget(rgb_label)
        layout.addWidget(self.rgb_input)
        layout.addWidget(self.preview)
        layout.addWidget(tool_label)
        layout.addWidget(self.pen_btn)
        layout.addWidget(self.pan_btn)
        layout.addWidget(self.rect_btn)
        layout.addWidget(self.line_btn)
        layout.addWidget(self.bucket_btn)
        layout.addWidget(self.select_btn)
        layout.addWidget(select_mode_label)
        layout.addWidget(self.select_rect_btn)
        layout.addWidget(self.select_pen_btn)
        layout.addWidget(self.deselect_btn)
        layout.addWidget(self.pen_drag_toggle)
        layout.addWidget(history_label)
        layout.addWidget(self.undo_btn)
        layout.addWidget(self.redo_btn)
        layout.addWidget(file_label)
        layout.addWidget(self.new_tab_btn)
        layout.addWidget(self.save_btn)
        layout.addWidget(self.load_btn)
        layout.addStretch(1)

        return panel

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget { color: #EDEDED; font-family: Segoe UI, Arial; font-size: 12px; }
            #controlPanel { background: #F4F4F4; }
            #controlPanel QLabel { color: #000000; }
            #panelTitle { font-size: 16px; font-weight: 600; margin-bottom: 4px; }
            QLineEdit { background: #1E1E1E; border: 1px solid #333; padding: 6px; border-radius: 6px; }
            #colorPreview { border: 1px solid #333; border-radius: 8px; }
            QPushButton, QAbstractButton { color: #000000; }
            QTabBar::tab { background: #D6D6D6; color: #000000; padding: 6px 10px; border-top-left-radius: 6px; border-top-right-radius: 6px; }
            QTabBar::tab:selected { background: #E2E2E2; }
            QTabWidget::pane { border: 1px solid #3A3A3A; }
            """
        )

    def _on_qcolor_changed(self, color: QColor) -> None:
        r5, g6, b5 = qcolor_to_rgb565(color)
        scene = self.current_scene()
        if scene:
            scene.set_current_color(r5, g6, b5)
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
        scene = self.current_scene()
        if scene:
            scene.set_current_color(r5, g6, b5)
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

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.undo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, activated=self.redo)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._save_qgc)
        QShortcut(QKeySequence("Ctrl+D"), self, activated=self._deselect)
        QShortcut(QKeySequence("L"), self, activated=lambda: self._set_tool("line"))
        QShortcut(QKeySequence("R"), self, activated=lambda: self._set_tool("rect"))
        QShortcut(QKeySequence("P"), self, activated=lambda: self._set_tool("pen"))
        QShortcut(QKeySequence("B"), self, activated=lambda: self._set_tool("bucket"))
        QShortcut(QKeySequence("S"), self, activated=lambda: self._set_tool("select"))
        QShortcut(QKeySequence("O"), self, activated=self._toggle_pen_drag)

    def _set_tool(self, tool: str) -> None:
        view = self.current_view()
        if not view:
            return
        view.set_tool_mode(tool)
        if tool == "pen":
            self.pen_btn.setChecked(True)
        elif tool == "pan":
            self.pan_btn.setChecked(True)
        elif tool == "rect":
            self.rect_btn.setChecked(True)
        elif tool == "line":
            self.line_btn.setChecked(True)
        elif tool == "bucket":
            self.bucket_btn.setChecked(True)
        elif tool == "select":
            self.select_btn.setChecked(True)

    def _toggle_pen_drag(self) -> None:
        self.pen_drag_toggle.setChecked(not self.pen_drag_toggle.isChecked())

    def _set_pen_drag(self, enabled: bool) -> None:
        scene = self.current_scene()
        if scene:
            scene.set_pen_drag_paint(enabled)

    def _set_select_mode(self, mode: str) -> None:
        scene = self.current_scene()
        if scene:
            scene.set_select_mode(mode)

    def _deselect(self) -> None:
        scene = self.current_scene()
        if scene:
            scene.clear_selection()

    def current_tab(self) -> dict | None:
        idx = self.tab_widget.currentIndex()
        if idx < 0 or idx >= len(self.tabs):
            return None
        return self.tabs[idx]

    def current_scene(self) -> LedMatrixScene | None:
        tab = self.current_tab()
        return tab["scene"] if tab else None

    def current_view(self) -> LedMatrixView | None:
        tab = self.current_tab()
        return tab["view"] if tab else None

    def _temp_pan_start(self, tab: dict) -> None:
        if tab["temp_pan_prev_tool"] is None:
            tab["temp_pan_prev_tool"] = tab["view"].tool_mode
            self._set_tool("pan")

    def _temp_pan_end(self, tab: dict) -> None:
        if tab["temp_pan_prev_tool"] is not None:
            self._set_tool(tab["temp_pan_prev_tool"])
            tab["temp_pan_prev_tool"] = None

    def begin_action(self, tab: dict) -> None:
        if tab["action_before"] is None:
            tab["action_before"] = self._clone_display(tab["frame"].display)

    def commit_action(self, tab: dict) -> None:
        if tab["action_before"] is None:
            return
        after = self._clone_display(tab["frame"].display)
        if after != tab["action_before"]:
            tab["undo"].append((tab["action_before"], after))
            if len(tab["undo"]) > 5:
                tab["undo"] = tab["undo"][-5:]
            tab["redo"].clear()
        tab["action_before"] = None

    def undo(self) -> None:
        tab = self.current_tab()
        if not tab or not tab["undo"]:
            return
        before, after = tab["undo"].pop()
        tab["redo"].append((before, after))
        tab["frame"].display = self._clone_display(before)
        tab["scene"].refresh_from_frame()

    def redo(self) -> None:
        tab = self.current_tab()
        if not tab or not tab["redo"]:
            return
        before, after = tab["redo"].pop()
        tab["undo"].append((before, after))
        tab["frame"].display = self._clone_display(after)
        tab["scene"].refresh_from_frame()

    def _clone_display(self, display):
        return [list(row) for row in display]

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
            tab = self.current_tab()
            if not tab:
                return
            data = serialize_frame(tab["frame"])
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
            tab = self.current_tab()
            if not tab:
                return
            tab["frame"].display = pixels
            tab["scene"].refresh_from_frame()
            tab["undo"].clear()
            tab["redo"].clear()
            tab["action_before"] = None
        except Exception as exc:
            QMessageBox.critical(self, "Load Failed", str(exc))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    frame = Frame()
    w = LedMatrixWidget(frame)
    w.show()
    sys.exit(app.exec_())
