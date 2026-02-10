from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from PyQt5.QtCore import QRect, QSize, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QTextCharFormat, QTextFormat, QSyntaxHighlighter, QKeySequence
from PyQt5.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QTextEdit,
    QSizePolicy,
    QShortcut,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QStyle,
)


# Chrome color scheme (exact values per spec)
APP_BG = "#0F111A"
TOP_BAR_BG = "#1A1F2E"
ACTIVE_TAB_BG = "#242B3D"
INACTIVE_TAB_TEXT = "#6B7394"
ACTIVE_TAB_TEXT = "#C8D3F5"
EDITOR_BG = "#1C1C1C"
SIDEBAR_BG = "#1E2638"
DIVIDER = "#2A3142"

RUN_BG = "#2ECC71"
RUN_TEXT = "#0F111A"
SAVE_BG = "#2A3142"
SAVE_TEXT = "#C8D3F5"
SAVE_HOVER = "#323B52"

# Load button color is not specified exactly; keep it "blue" while matching the dark chrome.
LOAD_BG = "#3B82F6"
LOAD_TEXT = "#0F111A"
LOAD_HOVER = "#5595FF"
RUN_HOVER = "#3BE07E"

# Syntax colors (exact values per spec)
DEFAULT_TEXT = "#C8D3F5"
PUNCTUATION = "#6B7394"
KEYWORD = "#7AA2F7"
TYPE = "#2AC3DE"
BOOL_OP = "#BB9AF7"
INT_LIT = "#FF9E64"
STRING_LIT = "#9ECE6A"
LITERAL = "#F7768E"
FUNC_NAME = "#7DCFFF"
CONSTANT = "#E0AF68"
OPERATOR = "#89DDFF"
COMMENT = "#565F89"
BLOCK_CLOSER = "#F7768E"

BRACKET_COLORS = ["#89DDFF", "#BB9AF7", "#9ECE6A"]


class QGHighlighter(QSyntaxHighlighter):
    STATE_IN_COMMENT = 0x1
    STATE_DEPTH_SHIFT = 1
    STATE_DEPTH_MASK = 0x6

    def __init__(self, document):
        super().__init__(document)

        self.keyword_set = {
            "Do",
            "Publish",
            "Send",
            "return",
            "While",
            "For",
            "in",
            "if",
            "and",
            "or",
            "xor",
            "not",
            "true",
            "false",
            "none",
        }
        self.type_set = {"Frame", "int", "color", "pixel", "bool", "string", "list", "None"}
        self.bool_ops = {"and", "or", "xor", "not"}
        self.literal_set = {"true", "false", "none"}

        self.fmt_default = self._make_format(DEFAULT_TEXT)
        self.fmt_punct = self._make_format(PUNCTUATION)
        self.fmt_keyword = self._make_format(KEYWORD)
        self.fmt_type = self._make_format(TYPE)
        self.fmt_bool = self._make_format(BOOL_OP)
        self.fmt_int = self._make_format(INT_LIT)
        self.fmt_string = self._make_format(STRING_LIT)
        self.fmt_literal = self._make_format(LITERAL)
        self.fmt_func = self._make_format(FUNC_NAME)
        self.fmt_const = self._make_format(CONSTANT)
        self.fmt_op = self._make_format(OPERATOR)
        self.fmt_comment = self._make_format(COMMENT, italic=True)
        self.fmt_block_closer = self._make_format(BLOCK_CLOSER)

        self.fmt_brackets = [self._make_format(c) for c in BRACKET_COLORS]

        self._re_ident = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
        self._re_const = re.compile(r"[A-Z][A-Z0-9_]*")

    def _make_format(self, color_hex: str, italic: bool = False) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color_hex))
        fmt.setFontItalic(italic)
        return fmt

    def highlightBlock(self, text: str) -> None:
        prev_state = self.previousBlockState()
        if prev_state < 0:
            prev_state = 0
        in_comment = bool(prev_state & self.STATE_IN_COMMENT)
        depth_mod = (prev_state >> self.STATE_DEPTH_SHIFT) & 0x3

        func_decl_ranges = self._find_func_decl_ranges(text)
        func_call_ranges = self._find_func_call_ranges(text)

        i = 0
        length = len(text)

        def is_in_ranges(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
            for a, b in ranges:
                if start >= a and end <= b:
                    return True
            return False

        while i < length:
            if in_comment:
                end = text.find("%", i)
                if end == -1:
                    self.setFormat(i, length - i, self.fmt_comment)
                    self.setCurrentBlockState(self.STATE_IN_COMMENT | (depth_mod << self.STATE_DEPTH_SHIFT))
                    return
                self.setFormat(i, end - i + 1, self.fmt_comment)
                i = end + 1
                in_comment = False
                continue

            ch = text[i]

            # Comment start
            if ch == "%":
                end = text.find("%", i + 1)
                if end == -1:
                    self.setFormat(i, length - i, self.fmt_comment)
                    self.setCurrentBlockState(self.STATE_IN_COMMENT | (depth_mod << self.STATE_DEPTH_SHIFT))
                    return
                self.setFormat(i, end - i + 1, self.fmt_comment)
                i = end + 1
                continue

            # String literal
            if ch == '"':
                j = i + 1
                while j < length:
                    if text[j] == "\\" and j + 1 < length:
                        j += 2
                        continue
                    if text[j] == '"':
                        j += 1
                        break
                    j += 1
                self.setFormat(i, j - i, self.fmt_string)
                i = j
                continue

            # Integer literal
            if ch.isdigit():
                j = i + 1
                while j < length and text[j].isdigit():
                    j += 1
                self.setFormat(i, j - i, self.fmt_int)
                i = j
                continue

            # Identifier / keyword / type
            if ch.isalpha() or ch == "_":
                m = self._re_ident.match(text, i)
                if m:
                    word = m.group(0)
                    start, end = m.start(), m.end()
                    if is_in_ranges(start, end, func_decl_ranges) or is_in_ranges(start, end, func_call_ranges):
                        self.setFormat(start, end - start, self.fmt_func)
                    elif word in self.literal_set:
                        self.setFormat(start, end - start, self.fmt_literal)
                    elif word in self.bool_ops:
                        self.setFormat(start, end - start, self.fmt_bool)
                    elif word in self.type_set:
                        self.setFormat(start, end - start, self.fmt_type)
                    elif word in self.keyword_set:
                        self.setFormat(start, end - start, self.fmt_keyword)
                    elif self._re_const.fullmatch(word):
                        self.setFormat(start, end - start, self.fmt_const)
                    else:
                        self.setFormat(start, end - start, self.fmt_default)
                    i = end
                    continue

            # Operators and delimiters
            two = text[i : i + 2]
            if two in {"->", "==", "<=", ">=", "!?"}:
                if two == "!?":
                    self.setFormat(i, 1, self.fmt_block_closer)
                    self.setFormat(i + 1, 1, self.fmt_punct)
                else:
                    self.setFormat(i, 2, self.fmt_op)
                i += 2
                continue

            if ch in "(){}[]<>":
                if ch in "([{<":
                    self.setFormat(i, 1, self.fmt_brackets[depth_mod])
                    depth_mod = (depth_mod + 1) % 3
                else:
                    depth_mod = (depth_mod - 1) % 3
                    self.setFormat(i, 1, self.fmt_brackets[depth_mod])
                i += 1
                continue

            if ch == "!":
                self.setFormat(i, 1, self.fmt_block_closer)
                i += 1
                continue

            if ch == ".":
                self.setFormat(i, 1, self.fmt_default)
                i += 1
                continue

            if ch == ":":
                self.setFormat(i, 1, self.fmt_punct)
                i += 1
                continue

            if ch in "=+-*&|~<>?":
                self.setFormat(i, 1, self.fmt_op)
                i += 1
                continue

            i += 1

        self.setCurrentBlockState((self.STATE_IN_COMMENT if in_comment else 0) | (depth_mod << self.STATE_DEPTH_SHIFT))

    def _find_func_decl_ranges(self, text: str) -> list[tuple[int, int]]:
        ranges: list[tuple[int, int]] = []
        m = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\{[^}]*\}\s*=>\s*[A-Za-z_][A-Za-z0-9_]*\s*:", text)
        if m:
            start = m.start(1)
            end = m.end(1)
            ranges.append((start, end))
        return ranges

    def _find_func_call_ranges(self, text: str) -> list[tuple[int, int]]:
        ranges: list[tuple[int, int]] = []
        for m in re.finditer(r"\bDo\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{", text):
            ranges.append((m.start(1), m.end(1)))
        return ranges


class LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self._editor = editor
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self._editor.paint_line_number_area(event)


class CodeEditor(QPlainTextEdit):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._line_number_area = LineNumberArea(self)
        self._highlighter = QGHighlighter(self.document())

        QShortcut(QKeySequence("Ctrl+="), self, activated=self._zoom_in)
        QShortcut(QKeySequence("Ctrl+-"), self, activated=self._zoom_out)

        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self.cursorPositionChanged.connect(self._highlight_current_line)

        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(16)
        self.setFont(font)

        self.setWordWrapMode(False)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))

        self._update_line_number_area_width(0)
        self._highlight_current_line()

        self.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background: {EDITOR_BG};
                color: {ACTIVE_TAB_TEXT};
                border: 1px solid {DIVIDER};
            }}
            """
        )

    def _zoom_in(self) -> None:
        self.zoomIn(1)

    def _zoom_out(self) -> None:
        self.zoomOut(1)

    def keyPressEvent(self, event):
        key = event.key()

        if event.modifiers() & Qt.ControlModifier:
            if key in (Qt.Key_Equal, Qt.Key_Plus):
                self._zoom_in()
                return
            if key == Qt.Key_Minus:
                self._zoom_out()
                return

        if key in (Qt.Key_Return, Qt.Key_Enter):
            if self._handle_smart_enter():
                return

        if key == Qt.Key_Exclam and self._handle_block_closer():
            return

        if key == Qt.Key_Question and self._handle_else_marker():
            return

        if event.text():
            ch = event.text()
            if ch in "([{\"":
                if self._handle_auto_pair(ch):
                    return
            if ch == "<":
                if self._handle_angle_pair():
                    return
            if ch == "%":
                if self._handle_percent_pair():
                    return

        super().keyPressEvent(event)

    def _handle_auto_pair(self, opener: str) -> bool:
        pairs = {"(": ")", "[": "]", "{": "}", '"': '"'}
        if opener not in pairs:
            return False

        cursor = self.textCursor()
        if cursor.hasSelection():
            selected = cursor.selectedText()
            cursor.insertText(f"{opener}{selected}{pairs[opener]}")
            return True

        closer = pairs[opener]
        cursor.insertText(opener + closer)
        cursor.movePosition(cursor.Left)
        self.setTextCursor(cursor)
        return True

    def _handle_angle_pair(self) -> bool:
        cursor = self.textCursor()
        pos = cursor.position()
        prev = self._prev_non_space_char(pos - 1)
        if prev and (prev.isalnum() or prev == "_" or prev in ")]"):
            cursor.insertText("<>")
            cursor.movePosition(cursor.Left)
            self.setTextCursor(cursor)
            return True
        return False

    def _handle_percent_pair(self) -> bool:
        cursor = self.textCursor()
        block = cursor.block()
        col = cursor.positionInBlock()
        text = block.text()
        if "%" in text[col:]:
            return False
        cursor.insertText("%%")
        cursor.movePosition(cursor.Left)
        self.setTextCursor(cursor)
        return True

    def _handle_block_closer(self) -> bool:
        cursor = self.textCursor()
        block = cursor.block()
        if cursor.positionInBlock() != 0 and block.text()[: cursor.positionInBlock()].strip():
            return False

        indent = self._find_matching_opener_indent(cursor.blockNumber())
        self._replace_line_indent(cursor, indent)
        cursor.insertText("!")
        return True

    def _handle_else_marker(self) -> bool:
        cursor = self.textCursor()
        block = cursor.block()
        prefix = block.text()[: cursor.positionInBlock()]
        if prefix.strip() != "!":
            return False

        indent = self._find_matching_if_indent(cursor.blockNumber())
        self._replace_line_indent(cursor, indent)
        cursor.insertText("?")
        return True

    def _handle_smart_enter(self) -> bool:
        cursor = self.textCursor()
        block = cursor.block()
        line = block.text()
        col = cursor.positionInBlock()
        before = line[:col]
        after = line[col:]

        if after.strip():
            return False

        base_indent = self._leading_spaces(line)
        trimmed = before.rstrip()

        opener = self._is_block_opener(trimmed)
        continuation = self._is_continuation(trimmed)

        if trimmed.endswith("."):
            next_indent = base_indent
        elif opener or continuation:
            next_indent = base_indent + 4
        else:
            next_indent = base_indent

        cursor.beginEditBlock()
        cursor.insertText("\n" + " " * next_indent)

        if opener and not continuation:
            cursor.insertText("\n" + " " * base_indent + "!")
            cursor.movePosition(cursor.Up)
            cursor.movePosition(cursor.EndOfLine)

        cursor.endEditBlock()
        self.setTextCursor(cursor)
        return True

    def _is_block_opener(self, text: str) -> bool:
        if not text:
            return False
        if text.endswith(":") or text.endswith("?"):
            return True
        if re.match(r"^\s*While\b.*\)\s*$", text):
            return True
        if text.lstrip().startswith("!?"):
            return True
        return False

    def _is_continuation(self, text: str) -> bool:
        if not text:
            return False
        if re.search(r"(=|->|\+|-|\*|&|\||==|<=|>=|<|>)\s*$", text):
            return True
        if text.rstrip().endswith(("(", "{", "[", "<")):
            return True
        return False

    def _leading_spaces(self, text: str) -> int:
        return len(text) - len(text.lstrip(" "))

    def _replace_line_indent(self, cursor, indent: int) -> None:
        block = cursor.block()
        line = block.text()
        current = self._leading_spaces(line)
        if current == indent:
            return
        c = self.textCursor()
        c.setPosition(block.position())
        c.setPosition(block.position() + current, c.KeepAnchor)
        c.insertText(" " * indent)
        self.setTextCursor(c)

    def _find_matching_opener_indent(self, block_number: int) -> int:
        doc = self.document()
        depth = 0
        for i in range(block_number - 1, -1, -1):
            block = doc.findBlockByNumber(i)
            line = block.text()
            stripped = line.strip()
            if not stripped:
                continue
            if stripped == "!":
                depth += 1
                continue
            if stripped.startswith("!?"):
                if depth == 0:
                    return self._leading_spaces(line)
                depth -= 1
                continue
            if self._is_block_opener(stripped):
                if depth == 0:
                    return self._leading_spaces(line)
                depth -= 1
        return 0

    def _find_matching_if_indent(self, block_number: int) -> int:
        doc = self.document()
        depth = 0
        for i in range(block_number - 1, -1, -1):
            block = doc.findBlockByNumber(i)
            line = block.text()
            stripped = line.strip()
            if not stripped:
                continue
            if stripped == "!":
                depth += 1
                continue
            if stripped.startswith("!?"):
                depth += 1
                continue
            if stripped.endswith("?"):
                if depth == 0:
                    return self._leading_spaces(line)
                depth -= 1
        return 0

    def _prev_non_space_char(self, pos: int) -> str:
        if pos < 0:
            return ""
        doc = self.document()
        while pos >= 0:
            ch = doc.characterAt(pos)
            if ch and not ch.isspace():
                return ch
            pos -= 1
        return ""

    def line_number_area_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        # padding + digit width
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_line_number_area_width(self, _new_block_count: int) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(), self._line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def paint_line_number_area(self, event) -> None:
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), QColor(EDITOR_BG))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())

        line_color = QColor(INACTIVE_TAB_TEXT)
        current_line = self.textCursor().blockNumber()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                if block_number == current_line:
                    painter.setPen(QColor(ACTIVE_TAB_TEXT))
                else:
                    painter.setPen(line_color)

                painter.drawText(
                    0,
                    top,
                    self._line_number_area.width() - 6,
                    self.fontMetrics().height(),
                    Qt.AlignRight,
                    number,
                )

            block = block.next()
            block_number += 1
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())

    def _highlight_current_line(self) -> None:
        extra = []
        if not self.isReadOnly():
            # In PyQt5, ExtraSelection is exposed on QTextEdit.
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor("#202020"))
            selection.format.setProperty(QTextFormat.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extra.append(selection)
        self.setExtraSelections(extra)


@dataclass
class CodeTab:
    editor: CodeEditor
    path: Path | None = None

class CodeEditorWidget(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self._tabs: list[CodeTab] = []
        self._publish_handler = None
        self._send_handler = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar with file tabs + plus button
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self._close_tab)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        self.tab_add_btn = QToolButton()
        self.tab_add_btn.setText("+")
        self.tab_add_btn.clicked.connect(self._new_tab)
        self.tab_widget.setCornerWidget(self.tab_add_btn, Qt.TopRightCorner)

        QShortcut(QKeySequence("Ctrl+="), self, activated=self._zoom_active_in).setContext(Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Ctrl+-"), self, activated=self._zoom_active_out).setContext(Qt.WidgetWithChildrenShortcut)

        # Toolbar
        toolbar = QWidget()
        toolbar.setObjectName("codeToolbar")
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(10, 8, 10, 8)
        tb.setSpacing(8)

        self.run_btn = QToolButton()
        self.run_btn.setObjectName("runButton")
        self.run_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.run_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.run_btn.setText("Run")
        self.run_btn.clicked.connect(self._run_program)

        self.save_btn = QPushButton("Save")
        self.save_btn.setObjectName("saveButton")
        self.save_btn.clicked.connect(self.save)

        self.load_btn = QPushButton("Load")
        self.load_btn.setObjectName("loadButton")
        self.load_btn.clicked.connect(self.load)

        tb.addWidget(self.run_btn)
        tb.addWidget(self.save_btn)
        tb.addWidget(self.load_btn)
        tb.addStretch(1)

        # Main split view
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(1)

        self.editor_host = QWidget()
        self.editor_layout = QVBoxLayout(self.editor_host)
        self.editor_layout.setContentsMargins(10, 10, 10, 10)
        self.editor_layout.setSpacing(10)
        self.editor_layout.addWidget(self.tab_widget)

        self.api_panel = QFrame()
        self.api_panel.setObjectName("apiPanel")
        self.api_panel_layout = QVBoxLayout(self.api_panel)
        self.api_panel_layout.setContentsMargins(12, 12, 12, 12)
        self.api_panel_layout.setSpacing(10)

        api_title = QLabel("API")
        api_title.setObjectName("apiTitle")
        api_body = QLabel(
            "Placeholder panel.\n\n"
            "Planned:\n"
            "- Docs browser\n"
            "- Snippets\n"
            "- Autocomplete hints\n"
        )
        api_body.setWordWrap(True)
        api_body.setObjectName("apiBody")

        self.api_panel_layout.addWidget(api_title)
        self.api_panel_layout.addWidget(api_body)
        self.api_panel_layout.addStretch(1)

        self.splitter.addWidget(self.editor_host)
        self.splitter.addWidget(self.api_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([1200, 360])

        root.addWidget(toolbar)
        root.addWidget(self.splitter, 1)

        self._apply_styles()
        self._new_tab()

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            f"""
            QWidget {{
                background: {APP_BG};
                color: {ACTIVE_TAB_TEXT};
                font-family: Segoe UI, Arial;
                font-size: 11px;
            }}

            /* Tabs (top bar) */
            QTabWidget::pane {{
                border: none;
            }}
            QTabBar {{
                background: {TOP_BAR_BG};
            }}
            QTabBar::tab {{
                background: {TOP_BAR_BG};
                color: {INACTIVE_TAB_TEXT};
                padding: 8px 12px;
                margin-right: 2px;
                border: 1px solid {DIVIDER};
                border-bottom: none;
            }}
            QTabBar::tab:selected {{
                background: {ACTIVE_TAB_BG};
                color: {ACTIVE_TAB_TEXT};
            }}
            QTabBar::close-button {{
                image: none;
            }}
            QTabWidget QToolButton {{
                background: {TOP_BAR_BG};
                color: {ACTIVE_TAB_TEXT};
                border: 1px solid {DIVIDER};
                padding: 4px 10px;
            }}
            QTabWidget QToolButton:hover {{
                background: {ACTIVE_TAB_BG};
            }}

            /* Toolbar */
            #codeToolbar {{
                background: {TOP_BAR_BG};
                border-bottom: 1px solid {DIVIDER};
            }}
            #runButton {{
                background: {RUN_BG};
                color: {RUN_TEXT};
                border: 1px solid {DIVIDER};
                padding: 6px 10px;
            }}
            #runButton:hover {{
                background: {RUN_HOVER};
            }}
            #saveButton {{
                background: {SAVE_BG};
                color: {SAVE_TEXT};
                border: 1px solid {DIVIDER};
                padding: 6px 12px;
            }}
            #saveButton:hover {{
                background: {SAVE_HOVER};
            }}
            #loadButton {{
                background: {LOAD_BG};
                color: {LOAD_TEXT};
                border: 1px solid {DIVIDER};
                padding: 6px 12px;
            }}
            #loadButton:hover {{
                background: {LOAD_HOVER};
            }}

            /* Splitter divider */
            QSplitter::handle {{
                background: {DIVIDER};
            }}

            /* API panel */
            #apiPanel {{
                background: {SIDEBAR_BG};
                border-left: 1px solid {DIVIDER};
                min-width: 280px;
            }}
            #apiTitle {{
                font-size: 13px;
                font-weight: 600;
                color: {ACTIVE_TAB_TEXT};
            }}
            #apiBody {{
                color: {INACTIVE_TAB_TEXT};
            }}
            """
        )

    def _tab_label_for(self, path: Path | None, index: int) -> str:
        if path is not None:
            return path.name
        return f"script{index}.qgk"

    def _new_tab(self) -> None:
        editor = CodeEditor()
        editor.textChanged.connect(self._update_current_tab_title)
        tab = CodeTab(editor=editor, path=None)
        self._tabs.append(tab)

        idx = len(self._tabs)
        self.tab_widget.addTab(editor, self._tab_label_for(None, idx))
        self.tab_widget.setCurrentWidget(editor)

    def _close_tab(self, index: int) -> None:
        if self.tab_widget.count() <= 1:
            return

        editor = self.tab_widget.widget(index)
        if editor is None:
            return

        # We do not track per-tab dirty state yet; ask only if non-empty.
        if isinstance(editor, QPlainTextEdit) and editor.document().isModified():
            choice = QMessageBox.question(
                self,
                "Unsaved Changes",
                "This tab has unsaved changes. Close anyway?",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if choice != QMessageBox.Yes:
                return

        self.tab_widget.removeTab(index)
        try:
            self._tabs.pop(index)
        except IndexError:
            pass

    def _on_tab_changed(self, _index: int) -> None:
        self._update_current_tab_title()

    def _active_tab(self) -> CodeTab | None:
        idx = self.tab_widget.currentIndex()
        if idx < 0 or idx >= len(self._tabs):
            return None
        return self._tabs[idx]

    def _update_current_tab_title(self) -> None:
        idx = self.tab_widget.currentIndex()
        tab = self._active_tab()
        if tab is None or idx < 0:
            return
        label = self._tab_label_for(tab.path, idx + 1)
        editor = tab.editor
        if editor.document().isModified():
            label = f"*{label}"
        self.tab_widget.setTabText(idx, label)

    def set_publish_handler(self, handler) -> None:
        self._publish_handler = handler

    def set_send_handler(self, handler) -> None:
        self._send_handler = handler

    def _run_program(self) -> None:
        tab = self._active_tab()
        if tab is None:
            return
        source = tab.editor.toPlainText()
        try:
            from Interpreter.interpreter import Interpreter, RuntimeErrorWithLine

            interp = Interpreter(
                publish_handler=self._publish_handler,
                send_handler=self._send_handler,
            )
            interp.run_source(source)
        except RuntimeErrorWithLine as exc:
            QMessageBox.critical(self, "Runtime Error", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "Run Failed", str(exc))

    def _zoom_active_in(self) -> None:
        tab = self._active_tab()
        if tab:
            tab.editor.zoomIn(1)

    def _zoom_active_out(self) -> None:
        tab = self._active_tab()
        if tab:
            tab.editor.zoomOut(1)

    def load(self) -> None:
        tab = self._active_tab()
        if tab is None:
            return

        file_name, _filter = QFileDialog.getOpenFileName(
            self,
            "Load Script",
            "",
            "QGraphic script (*.qgk *.txt);;All files (*.*)",
        )
        if not file_name:
            return

        path = Path(file_name)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="latin-1")

        tab.editor.blockSignals(True)
        tab.editor.setPlainText(text)
        tab.editor.document().setModified(False)
        tab.editor.blockSignals(False)

        tab.path = path
        self._update_current_tab_title()

    def save(self) -> None:
        tab = self._active_tab()
        if tab is None:
            return

        path = tab.path
        if path is None:
            file_name, _filter = QFileDialog.getSaveFileName(
                self,
                "Save Script",
                "script1.qgk",
                "QGraphic script (*.qgk);;Text (*.txt);;All files (*.*)",
            )
            if not file_name:
                return
            path = Path(file_name)
            tab.path = path

        path.write_text(tab.editor.toPlainText(), encoding="utf-8")
        tab.editor.document().setModified(False)
        self._update_current_tab_title()
