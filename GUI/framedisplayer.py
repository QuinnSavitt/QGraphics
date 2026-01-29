import sys
import os
from PyQt5.QtWidgets import QApplication, QWidget, QGridLayout
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtCore import Qt
# Ensure parent directory is in sys.path for import
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Engine.engine import Frame

class LedMatrixWidget(QWidget):
    def __init__(self, frame: Frame, parent=None):
        super().__init__(parent)
        self.frame = frame
        self.cell_size = 20  # Size of each LED circle
        self.margin = 4      # Margin between circles
        self.setMinimumSize(
            64 * (self.cell_size + self.margin),
            32 * (self.cell_size + self.margin)
        )
        self.setWindowTitle('Frame LED Matrix Display')

    def paintEvent(self, event):
        painter = QPainter(self)
        for y in range(32):
            for x in range(64):
                r, g, b = self.frame.display[y][x]
                color = QColor(r << 3, g << 2, b << 3)  # RGB565 to 8-bit
                painter.setBrush(color)
                painter.setPen(Qt.NoPen)
                px = x * (self.cell_size + self.margin)
                py = y * (self.cell_size + self.margin)
                painter.drawEllipse(px, py, self.cell_size, self.cell_size)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    # Example: create a frame with a diagonal line
    frame = Frame()
    for i in range(32):
        if i < 64:
            frame.setRed(i, i, 31)  # Max red for RGB565
    w = LedMatrixWidget(frame)
    w.show()
    sys.exit(app.exec_())
