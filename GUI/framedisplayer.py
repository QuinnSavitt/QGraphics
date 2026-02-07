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
    QSplitter,
    QToolButton,
    QShortcut,
)
from PyQt5.QtGui import QKeySequence
from PyQt5.QtGui import QColor, QBrush, QPen, QPainter, QPainterPath
from PyQt5.QtCore import Qt, QRectF, QTimer, QFileInfo
from PyQt5.QtWidgets import QSpinBox, QDoubleSpinBox, QComboBox, QRadioButton

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
        self.selected_pen = QPen(QColor(255, 255, 255), 2)
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
        self._oval_preview = None
        self._oval_start = None
        self._select_preview = None
        self._select_start = None
        self._line_preview = None
        self._line_start = None
        self._line_end = None
        self._curve_preview = None
        self._curve_start = None
        self._curve_end = None
        self._curve_control = None
        self._line_mode = "line"  # line | curve
        self._action_active = False
        self._bucket_pending = None
        self._selection: set[tuple[int, int]] = set()
        self._select_mode = "rect"  # rect | pen | fill | move
        self._move_active = False
        self._move_start = None
        self._move_colors: dict[tuple[int, int], tuple[int, int, int]] = {}
        self._move_preview: set[tuple[int, int]] = set()
        self._move_offset = (0, 0)
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

    def set_line_mode(self, mode: str) -> None:
        self._line_mode = mode

    def clear_selection(self) -> None:
        if not self._selection:
            return
        for (x, y) in self._selection:
            self.items_grid[y][x].setPen(self.items_grid[y][x].default_pen)
        self._selection.clear()
        self._clear_move_preview()

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
            elif tool == "oval" and event.button() == Qt.LeftButton:
                self._begin_action(view)
                self._oval_start = event.scenePos()
                if self._oval_preview is None:
                    self._oval_preview = self.addEllipse(
                        QRectF(self._oval_start, self._oval_start),
                        QPen(QColor(220, 220, 220), 2, Qt.DashLine),
                        QBrush(Qt.transparent),
                    )
            elif tool == "line" and event.button() == Qt.LeftButton:
                if self._line_mode == "line":
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
                else:
                    if self._curve_start is None:
                        self._begin_action(view)
                        self._curve_start = event.scenePos()
                        self._curve_end = event.scenePos()
                        if self._curve_preview is None:
                            self._curve_preview = self.addPath(
                                QPainterPath(),
                                QPen(QColor(220, 220, 220), 2, Qt.DashLine),
                            )
                    elif self._curve_end is not None and self._curve_control is None:
                        self._curve_control = event.scenePos()
                        self._apply_curve()
                        self._commit_action(view)
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
                elif self._select_mode == "pen":
                    self._select_at(event.scenePos(), view)
                elif self._select_mode == "fill":
                    self._select_fill(event.scenePos())
                elif self._select_mode == "move":
                    self._start_move(event.scenePos(), view)
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
            elif tool == "oval" and self._oval_preview is not None and self._oval_start is not None:
                rect = QRectF(self._oval_start, event.scenePos()).normalized()
                if event.modifiers() & Qt.ShiftModifier:
                    rect = self._square_rect(self._oval_start, event.scenePos())
                self._oval_preview.setRect(rect)
            elif tool == "line":
                if self._line_mode == "line" and self._line_preview is not None and self._line_start is not None:
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
                elif self._line_mode == "curve" and self._curve_start is not None and self._curve_control is None:
                    if event.buttons() & Qt.LeftButton:
                        # dragging to set end
                        self._curve_end = event.scenePos()
                        self._update_curve_preview(self._curve_end)
                    else:
                        # after drag release: mouse position sets control preview
                        self._update_curve_preview(event.scenePos())
            elif tool == "select" and self._select_mode == "rect" and self._select_preview is not None and self._select_start is not None:
                rect = QRectF(self._select_start, event.scenePos()).normalized()
                self._select_preview.setRect(rect)
            elif tool == "select" and self._select_mode == "pen" and (event.buttons() & Qt.LeftButton):
                self._select_at(event.scenePos(), view)
            elif tool == "select" and self._select_mode == "move" and self._move_active:
                self._update_move_preview(event.scenePos())
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
            elif tool == "oval" and self._oval_preview is not None and self._oval_start is not None:
                rect = self._oval_preview.rect()
                self.removeItem(self._oval_preview)
                self._oval_preview = None
                self._apply_oval(rect)
                self._oval_start = None
                self._commit_action(view)
            elif tool == "line":
                if self._line_mode == "line" and self._line_preview is not None and self._line_start is not None:
                    line = self._line_preview.line()
                    self.removeItem(self._line_preview)
                    self._line_preview = None
                    end = self._line_end if self._line_end is not None else line.p2()
                    self._apply_line(line.x1(), line.y1(), end.x(), end.y())
                    self._line_start = None
                    self._line_end = None
                    self._commit_action(view)
                elif self._line_mode == "curve" and self._curve_start is not None and self._curve_control is None:
                    if self._curve_end is None:
                        self._curve_end = event.scenePos()
                    self._update_curve_preview(event.scenePos())
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
            elif tool == "select" and self._select_mode == "move" and self._move_active:
                self._commit_move()
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

    def _apply_oval(self, rect: QRectF) -> None:
        if rect.isNull():
            return
        r5, g6, b5 = self.current_color
        x1 = int(rect.left() // (self.cell_size + self.margin))
        y1 = int(rect.top() // (self.cell_size + self.margin))
        x2 = int(rect.right() // (self.cell_size + self.margin))
        y2 = int(rect.bottom() // (self.cell_size + self.margin))
        self.frame.makeOval(x1, y1, x2, y2, r5, g6, b5)
        self.refresh_from_frame()

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

    def _apply_curve(self) -> None:
        if self._curve_start is None or self._curve_end is None or self._curve_control is None:
            return
        r5, g6, b5 = self.current_color
        gx1, gy1 = self._scene_to_grid(self._curve_start.x(), self._curve_start.y())
        gx2, gy2 = self._scene_to_grid(self._curve_end.x(), self._curve_end.y())
        gcx, gcy = self._scene_to_grid(self._curve_control.x(), self._curve_control.y())
        self.frame.makeCurve(gx1, gy1, gx2, gy2, gcx, gcy, r5, g6, b5)
        self.refresh_from_frame()
        if self._curve_preview is not None:
            self.removeItem(self._curve_preview)
            self._curve_preview = None
        self._curve_start = None
        self._curve_end = None
        self._curve_control = None

    def _update_curve_preview(self, control_pos) -> None:
        if self._curve_preview is None or self._curve_start is None or self._curve_end is None:
            return
        path = QPainterPath()
        path.moveTo(self._curve_start)
        path.quadTo(control_pos, self._curve_end)
        self._curve_preview.setPath(path)

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

    def _select_fill(self, pos) -> None:
        gx, gy = self._scene_to_grid(pos.x(), pos.y())
        target = self.frame.display[gy][gx]
        stack = [(gx, gy)]
        visited = set()
        while stack:
            x, y = stack.pop()
            if (x, y) in visited:
                continue
            visited.add((x, y))
            if self.frame.display[y][x] != target:
                continue
            self._add_to_selection(x, y)
            if x > 0:
                stack.append((x - 1, y))
            if x < 63:
                stack.append((x + 1, y))
            if y > 0:
                stack.append((x, y - 1))
            if y < 31:
                stack.append((x, y + 1))

    def _start_move(self, pos, view) -> None:
        item = self.itemAt(pos, view.transform())
        if not isinstance(item, PixelItem) or (item.x, item.y) not in self._selection:
            return
        self._begin_action(view)
        self._move_active = True
        self._move_start = pos
        self._move_colors = {coord: self.frame.display[coord[1]][coord[0]] for coord in self._selection}
        self._move_offset = (0, 0)
        self._update_move_preview(pos)

    def _update_move_preview(self, pos) -> None:
        if not self._move_active or self._move_start is None:
            return
        start_gx, start_gy = self._scene_to_grid(self._move_start.x(), self._move_start.y())
        gx, gy = self._scene_to_grid(pos.x(), pos.y())
        dx = gx - start_gx
        dy = gy - start_gy
        if (dx, dy) == self._move_offset:
            return
        self._move_offset = (dx, dy)
        self._clear_move_preview()
        preview = set()
        for (x, y), color in self._move_colors.items():
            nx = x + dx
            ny = y + dy
            if 0 <= nx < 64 and 0 <= ny < 32:
                preview.add((nx, ny))
                qc = rgb565_to_qcolor(*color)
                qc.setAlpha(120)
                self.items_grid[ny][nx].setBrush(QBrush(qc))
        self._move_preview = preview

    def _clear_move_preview(self) -> None:
        if not self._move_preview:
            return
        for (x, y) in self._move_preview:
            r, g, b = self.frame.display[y][x]
            self.items_grid[y][x].setBrush(QBrush(rgb565_to_qcolor(r, g, b)))
        self._move_preview.clear()

    def _commit_move(self) -> None:
        if not self._move_active:
            return
        dx, dy = self._move_offset
        pixels = [((x, y), color) for (x, y), color in self._move_colors.items()]
        self.frame.moveSelection(pixels, dx, dy)
        self.refresh_from_frame()
        new_selection = set()
        for (x, y) in self._selection:
            nx = x + dx
            ny = y + dy
            if 0 <= nx < 64 and 0 <= ny < 32:
                new_selection.add((nx, ny))
        self.clear_selection()
        for (x, y) in new_selection:
            self._add_to_selection(x, y)
        self._move_active = False
        self._move_start = None
        self._move_colors = {}
        self._move_offset = (0, 0)
        self._commit_action(self.views()[0])

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
        self.tool_mode = "pen"  # pen | pan | rect | oval | line | bucket | select
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

        # Style-only: plus button near rightmost tab (keeps existing New Tab behavior)
        self.tab_add_btn = QToolButton()
        self.tab_add_btn.setText("+")
        self.tab_add_btn.clicked.connect(lambda: self._add_tab(f"Frame {self.tab_widget.count() + 1}"))
        self.tab_widget.setCornerWidget(self.tab_add_btn, Qt.TopRightCorner)

        self._add_tab("Frame 1", frame)

        tool_panel, right_panel = self._build_controls()
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setWidget(right_panel)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(tool_panel)
        splitter.addWidget(self.tab_widget)
        splitter.addWidget(right_scroll)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.addWidget(splitter)
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

    def display_frame(self, frame: Frame) -> None:
        tab = self.current_tab()
        if not tab:
            return
        # Copy display data into the current tab's frame.
        tab["frame"].display = [list(row) for row in frame.display]
        tab["scene"].refresh_from_frame()
        tab["undo"].clear()
        tab["redo"].clear()
        tab["action_before"] = None

    def _add_tab(self, title: str, frame: Frame | None = None) -> None:
        frame = frame or Frame()
        scene = LedMatrixScene(frame)
        view = LedMatrixView(scene)
        view.setRenderHint(QPainter.Antialiasing, True)
        view.setFocusPolicy(Qt.StrongFocus)
        view.setMouseTracking(True)
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
            "filename": None,
            "dirty": False,
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
        tab = None
        for i, t in enumerate(self.tabs):
            if t["view"] is widget:
                tab = t
                tab_index = i
                break
        if tab and tab.get("dirty"):
            choice = QMessageBox.question(
                self,
                "Unsaved Changes",
                "This tab has unsaved changes. Save before closing?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if choice == QMessageBox.Cancel:
                return
            if choice == QMessageBox.Yes:
                if not self._save_qgc(forced_tab=tab):
                    return
        self.tab_widget.removeTab(index)
        if tab:
            self.tabs.pop(tab_index)

    def _on_tab_changed(self, index: int) -> None:
        tab = self.current_tab()
        if not tab:
            return
        if hasattr(self, "pen_drag_toggle"):
            self.pen_drag_toggle.setChecked(tab["scene"].pen_drag_paint)
        self._fit_view()

    def _build_controls(self) -> tuple[QWidget, QWidget]:
        tool_panel = QWidget()
        tool_panel.setFixedWidth(84)
        tool_panel.setObjectName("toolPanel")
        tool_layout = QVBoxLayout(tool_panel)
        tool_layout.setSpacing(8)

        panel = QWidget()
        panel.setMinimumWidth(320)
        panel.setObjectName("controlPanel")
        layout = QVBoxLayout(panel)
        layout.setSpacing(12)

        title = QLabel("Color Picker")
        title.setObjectName("panelTitle")

        self.color_dialog = QColorDialog()
        self.color_dialog.setOption(QColorDialog.DontUseNativeDialog, True)
        self.color_dialog.setOption(QColorDialog.NoButtons, True)
        self.color_dialog.currentColorChanged.connect(self._on_qcolor_changed)
        self.color_dialog.setMinimumSize(220, 220)
        self.color_dialog.setMaximumSize(260, 260)
        # Style-only: hide advanced controls (HSV/HTML/etc) for a simple picker
        QTimer.singleShot(0, self._simplify_color_dialog)

        rgb_label = QLabel("RGB565 (r g b)")
        self.rgb_input = QLineEdit("31 63 31")
        self.rgb_input.setPlaceholderText("e.g. 31 63 31")
        self.rgb_input.editingFinished.connect(self._on_rgb_input)
        self.rgb_input.setMaximumWidth(200)

        # Style-only: keep color section minimal (wheel + RGB565 fields)
        self.preview = QFrame()
        self.preview.setFixedHeight(36)
        self.preview.setObjectName("colorPreview")
        self._set_preview_color(31, 63, 31)
        self.preview.setVisible(False)

        tool_label = QLabel("Tool")
        self.pen_btn = QPushButton("Pen")
        self.pan_btn = QPushButton("Pan/Zoom")
        self.rect_btn = QPushButton("Rect")
        self.oval_btn = QPushButton("Oval")
        self.line_btn = QPushButton("Line")
        self.bucket_btn = QPushButton("Bucket")
        self.select_btn = QPushButton("Select")
        self.pen_btn.setCheckable(True)
        self.pan_btn.setCheckable(True)
        self.rect_btn.setCheckable(True)
        self.oval_btn.setCheckable(True)
        self.line_btn.setCheckable(True)
        self.bucket_btn.setCheckable(True)
        self.select_btn.setCheckable(True)
        self.pen_btn.setChecked(True)
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_group.addButton(self.pen_btn)
        self.tool_group.addButton(self.pan_btn)
        self.tool_group.addButton(self.rect_btn)
        self.tool_group.addButton(self.oval_btn)
        self.tool_group.addButton(self.line_btn)
        self.tool_group.addButton(self.bucket_btn)
        self.tool_group.addButton(self.select_btn)
        self.pen_btn.clicked.connect(lambda: self._set_tool("pen"))
        self.pan_btn.clicked.connect(lambda: self._set_tool("pan"))
        self.rect_btn.clicked.connect(lambda: self._set_tool("rect"))
        self.oval_btn.clicked.connect(lambda: self._set_tool("oval"))
        self.line_btn.clicked.connect(lambda: self._set_tool("line"))
        self.bucket_btn.clicked.connect(lambda: self._set_tool("bucket"))
        self.select_btn.clicked.connect(lambda: self._set_tool("select"))

        self.line_mode_label = QLabel("Line Mode")
        self.line_line_btn = QPushButton("Line")
        self.line_curve_btn = QPushButton("Curve")
        self.line_line_btn.setCheckable(True)
        self.line_curve_btn.setCheckable(True)
        self.line_line_btn.setChecked(True)
        self.line_group = QButtonGroup(self)
        self.line_group.setExclusive(True)
        self.line_group.addButton(self.line_line_btn)
        self.line_group.addButton(self.line_curve_btn)
        self.line_line_btn.clicked.connect(lambda: self._set_line_mode("line"))
        self.line_curve_btn.clicked.connect(lambda: self._set_line_mode("curve"))

        self.select_mode_label = QLabel("Select Mode")
        self.select_rect_btn = QPushButton("Rect")
        self.select_pen_btn = QPushButton("Pen")
        self.select_fill_btn = QPushButton("Fill")
        self.select_move_btn = QPushButton("Move")
        self.select_rect_btn.setCheckable(True)
        self.select_pen_btn.setCheckable(True)
        self.select_fill_btn.setCheckable(True)
        self.select_move_btn.setCheckable(True)
        self.select_rect_btn.setChecked(True)
        self.select_group = QButtonGroup(self)
        self.select_group.setExclusive(True)
        self.select_group.addButton(self.select_rect_btn)
        self.select_group.addButton(self.select_pen_btn)
        self.select_group.addButton(self.select_fill_btn)
        self.select_group.addButton(self.select_move_btn)
        self.select_rect_btn.clicked.connect(lambda: self._set_select_mode("rect"))
        self.select_pen_btn.clicked.connect(lambda: self._set_select_mode("pen"))
        self.select_fill_btn.clicked.connect(lambda: self._set_select_mode("fill"))
        self.select_move_btn.clicked.connect(lambda: self._set_select_mode("move"))

        self.deselect_btn = QPushButton("Deselect")
        self.deselect_btn.clicked.connect(self._deselect)

        self.pen_drag_toggle = QCheckBox("Drag")
        self.pen_drag_toggle.setChecked(False)
        self.pen_drag_toggle.toggled.connect(self._set_pen_drag)

        file_label = QLabel("File")
        self.save_btn = QPushButton("Save .qgc")
        self.load_btn = QPushButton("Load .qgc")
        self.save_btn.clicked.connect(self._save_qgc)
        self.load_btn.clicked.connect(self._load_qgc)

        history_label = QLabel("History")
        self.undo_btn = QPushButton("Undo")
        self.redo_btn = QPushButton("Redo")
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn.clicked.connect(self.redo)

        self._install_shortcuts()

        # Left tool strip (layout-only change)
        tool_layout.addWidget(tool_label)
        tool_layout.addWidget(self.pen_btn)
        tool_layout.addWidget(self.pan_btn)
        tool_layout.addWidget(self.rect_btn)
        tool_layout.addWidget(self.oval_btn)
        tool_layout.addWidget(self.line_btn)
        tool_layout.addWidget(self.line_mode_label)
        tool_layout.addWidget(self.line_line_btn)
        tool_layout.addWidget(self.line_curve_btn)
        tool_layout.addWidget(self.bucket_btn)
        tool_layout.addWidget(self.select_btn)
        tool_layout.addWidget(self.select_mode_label)
        tool_layout.addWidget(self.select_rect_btn)
        tool_layout.addWidget(self.select_pen_btn)
        tool_layout.addWidget(self.select_fill_btn)
        tool_layout.addWidget(self.select_move_btn)
        tool_layout.addWidget(self.deselect_btn)
        tool_layout.addWidget(self.pen_drag_toggle)
        tool_layout.addStretch(1)

        # Right control panel (layout-only change)
        layout.addWidget(title)
        layout.addWidget(self.color_dialog)
        layout.addWidget(rgb_label)
        layout.addWidget(self.rgb_input)
        layout.addWidget(history_label)
        layout.addWidget(self.undo_btn)
        layout.addWidget(self.redo_btn)
        layout.addWidget(file_label)
        layout.addWidget(self.save_btn)
        layout.addWidget(self.load_btn)
        layout.addStretch(1)

        self._set_select_ui_visible(False)
        self._set_line_ui_visible(False)

        return tool_panel, panel

    def _apply_styles(self) -> None:
        # Style-only changes: dark theme, muted panels, subtle borders
        self.setStyleSheet(
            """
            QWidget { color: #C9CED6; font-family: Segoe UI, Arial; font-size: 11px; }
            QMainWindow { background: #0B0F14; }
            #toolPanel { background: #10151C; border: 1px solid #1C2330; }
            #controlPanel { background: #10151C; border: 1px solid #1C2330; }
            #panelTitle { font-size: 13px; font-weight: 600; margin-bottom: 4px; color: #E6E9EF; }
            #sectionHeader { font-size: 12px; font-weight: 600; color: #AEB6C2; }
            QLabel { color: #C9CED6; }
            QLineEdit { background: #0F141B; border: 1px solid #1C2330; padding: 6px; border-radius: 6px; color: #E6E9EF; }
            #colorPreview { border: 1px solid #1C2330; border-radius: 8px; }
            QPushButton, QAbstractButton {
                background: #10151C;
                border: 1px solid #1C2330;
                border-radius: 6px;
                padding: 6px;
                color: #C9CED6;
            }
            QPushButton:hover, QAbstractButton:hover { border-color: #2A3345; color: #E6E9EF; }
            QPushButton:pressed, QAbstractButton:pressed { background: #121A24; }
            QPushButton:checked { background: #1A2433; border-color: #3A506B; color: #E6E9EF; }
            QCheckBox { color: #C9CED6; }
            QTabBar::tab {
                background: #121722;
                color: #C9CED6;
                padding: 6px 10px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                border: 1px solid #1C2330;
                margin-right: 4px;
            }
            QTabBar::tab:selected { background: #182234; color: #E6E9EF; }
            QTabWidget::pane { border: 1px solid #1C2330; }
            QScrollArea { background: transparent; }
            QTabWidget QToolButton {
                background: #24324A;
                color: #E6E9EF;
                border: 1px solid #3A506B;
                border-radius: 6px;
                padding: 2px 8px;
            }
            QTabWidget QToolButton:hover { background: #2E3F5E; }
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

    def _simplify_color_dialog(self) -> None:
        # Hide non-essential controls while keeping the color area intact
        for widget_type in (QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox, QRadioButton, QToolButton):
            for w in self.color_dialog.findChildren(widget_type):
                w.setVisible(False)

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.undo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, activated=self.redo)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=lambda: self._save_qgc())
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, activated=lambda: self._save_qgc(save_as=True))
        QShortcut(QKeySequence("Ctrl+D"), self, activated=self._deselect)
        QShortcut(QKeySequence("Ctrl+="), self, activated=lambda: self._zoom_canvas(1.15))
        QShortcut(QKeySequence("Ctrl+-"), self, activated=lambda: self._zoom_canvas(1 / 1.15))
        QShortcut(QKeySequence("L"), self, activated=lambda: self._set_tool("line"))
        QShortcut(QKeySequence("R"), self, activated=lambda: self._set_tool("rect"))
        QShortcut(QKeySequence("C"), self, activated=lambda: self._set_tool("oval"))
        QShortcut(QKeySequence("P"), self, activated=lambda: self._set_tool("pen"))
        QShortcut(QKeySequence("B"), self, activated=lambda: self._set_tool("bucket"))
        QShortcut(QKeySequence("S"), self, activated=lambda: self._set_tool("select"))
        QShortcut(QKeySequence("O"), self, activated=self._toggle_pen_drag)

    def _zoom_canvas(self, factor: float) -> None:
        view = self.current_view()
        if view:
            view.scale(factor, factor)

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
        elif tool == "oval":
            self.oval_btn.setChecked(True)
        elif tool == "line":
            self.line_btn.setChecked(True)
        elif tool == "bucket":
            self.bucket_btn.setChecked(True)
        elif tool == "select":
            self.select_btn.setChecked(True)
        self._set_select_ui_visible(tool == "select")
        self._set_line_ui_visible(tool == "line")

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

    def _set_line_mode(self, mode: str) -> None:
        scene = self.current_scene()
        if scene:
            scene.set_line_mode(mode)

    def _set_line_ui_visible(self, visible: bool) -> None:
        self.line_mode_label.setVisible(visible)
        self.line_line_btn.setVisible(visible)
        self.line_curve_btn.setVisible(visible)

    def _deselect(self) -> None:
        scene = self.current_scene()
        if scene:
            scene.clear_selection()

    def _set_select_ui_visible(self, visible: bool) -> None:
        self.select_mode_label.setVisible(visible)
        self.select_rect_btn.setVisible(visible)
        self.select_pen_btn.setVisible(visible)
        self.select_fill_btn.setVisible(visible)
        self.select_move_btn.setVisible(visible)
        self.deselect_btn.setVisible(visible)

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
            tab["dirty"] = True
            self._update_tab_title(tab)
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

    def _update_tab_title(self, tab: dict) -> None:
        name = "Untitled"
        if tab.get("filename"):
            name = QFileInfo(tab["filename"]).fileName()
        if tab.get("dirty"):
            name = f"{name}*"
        idx = self.tab_widget.indexOf(tab["view"])
        if idx >= 0:
            self.tab_widget.setTabText(idx, name)

    def _save_qgc(self, save_as: bool = False, forced_tab: dict | None = None) -> bool:
        tab = forced_tab or self.current_tab()
        if not tab:
            return False
        filename = tab.get("filename") if not save_as else None
        if not filename:
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "Save Frame",
                "",
                "QGraphic Frame (*.qgc)",
            )
            if not filename:
                return False
            if not filename.lower().endswith(".qgc"):
                filename += ".qgc"
        try:
            data = serialize_frame(tab["frame"])
            with open(filename, "wb") as f:
                f.write(data)
            tab["filename"] = filename
            tab["dirty"] = False
            self._update_tab_title(tab)
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))
            return False

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
            tab["filename"] = filename
            tab["dirty"] = False
            self._update_tab_title(tab)
        except Exception as exc:
            QMessageBox.critical(self, "Load Failed", str(exc))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    frame = Frame()
    w = LedMatrixWidget(frame)
    w.show()
    sys.exit(app.exec_())
