from pathlib import Path


class Frame:
    # Frame represents a 64x32 pixel display where each pixel is an RGB565 tuple.
    def __init__(self, start=None, on_change=None):
        if start is None:
            self.display = [[(0, 0, 0) for x in range(64)] for y in range(32)]
        else:
            # TODO: validate start
            self.display = start
        self._on_change = on_change

    def set_on_change(self, on_change) -> None:
        self._on_change = on_change

    def _notify_change(self) -> None:
        if self._on_change is not None:
            self._on_change(self)

    def setRed(self, x, y, value):
        r, g, b = self.display[y][x]
        self.display[y][x] = (value, g, b)
        self._notify_change()

    def setGreen(self, x, y, value):
        r, g, b = self.display[y][x]
        self.display[y][x] = (r, value, b)
        self._notify_change()

    def setBlue(self, x, y, value):
        r, g, b = self.display[y][x]
        self.display[y][x] = (r, g, value)
        self._notify_change()

    def setColor(self, x, y, r, g, b):
        self.display[y][x] = (r, g, b)
        self._notify_change()

    def getPixel(self, x, y):
        return self.display[y][x]

    def getRed(self, x, y):
        r, g, b = self.display[y][x]
        return r

    def getGreen(self, x, y):
        r, g, b = self.display[y][x]
        return g

    def getBlue(self, x, y):
        r, g, b = self.display[y][x]
        return b

    def makeRect(self, x1, y1, x2, y2, r, g, b):
        # NEW
        for y in range(y1, y2 + 1):
            for x in range(x1, x2 + 1):
                self.setColor(x, y, r, g, b)

    def makeLine(self, x1, y1, x2, y2, r, g, b):
        # NEW: Bresenham line
        x1 = int(x1)
        y1 = int(y1)
        x2 = int(x2)
        y2 = int(y2)

        dx = abs(x2 - x1)
        dy = -abs(y2 - y1)
        sx = 1 if x1 < x2 else -1
        sy = 1 if y1 < y2 else -1
        err = dx + dy

        while True:
            if 0 <= x1 < 64 and 0 <= y1 < 32:
                self.setColor(x1, y1, r, g, b)
            if x1 == x2 and y1 == y2:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x1 += sx
            if e2 <= dx:
                err += dx
                y1 += sy

    def makeCurve(self, x1, y1, x2, y2, cx, cy, r, g, b):
        # NEW: Quadratic Bezier curve from (x1,y1) to (x2,y2) with control (cx,cy)
        x1 = float(x1)
        y1 = float(y1)
        x2 = float(x2)
        y2 = float(y2)
        cx = float(cx)
        cy = float(cy)

        steps = int(max(abs(x2 - x1), abs(y2 - y1)) * 3) + 8
        prev_x = None
        prev_y = None
        for i in range(steps + 1):
            t = i / steps
            mt = 1.0 - t
            x = (mt * mt * x1) + (2 * mt * t * cx) + (t * t * x2)
            y = (mt * mt * y1) + (2 * mt * t * cy) + (t * t * y2)
            xi = int(round(x))
            yi = int(round(y))
            if prev_x is not None and prev_y is not None:
                self.makeLine(prev_x, prev_y, xi, yi, r, g, b)
            prev_x, prev_y = xi, yi

    def makeOval(self, x1, y1, x2, y2, r, g, b):
        # NEW: filled ellipse bounded by rectangle (x1,y1)-(x2,y2)
        x1 = int(x1)
        y1 = int(y1)
        x2 = int(x2)
        y2 = int(y2)
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1

        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        rx = max(1.0, (x2 - x1) / 2.0)
        ry = max(1.0, (y2 - y1) / 2.0)
        for y in range(y1, y2 + 1):
            if 0 <= y < 32:
                ny = (y - cy) / ry
                t = 1.0 - (ny * ny)
                if t < 0:
                    continue
                span = rx * (t ** 0.5)
                xa = int(round(cx - span))
                xb = int(round(cx + span))
                for x in range(xa, xb + 1):
                    if 0 <= x < 64:
                        self.setColor(x, y, r, g, b)

    def fill(self, startx, starty, r, g, b):
        # NEW: 4-direction flood fill
        startx = int(startx)
        starty = int(starty)
        if not (0 <= startx < 64 and 0 <= starty < 32):
            return
        target = self.display[starty][startx]
        replacement = (r, g, b)
        if target == replacement:
            return
        stack = [(startx, starty)]
        visited = set()
        while stack:
            x, y = stack.pop()
            if (x, y) in visited:
                continue
            visited.add((x, y))
            if self.display[y][x] != target:
                continue
            self.display[y][x] = replacement
            if x > 0:
                stack.append((x - 1, y))
            if x < 63:
                stack.append((x + 1, y))
            if y > 0:
                stack.append((x, y - 1))
            if y < 31:
                stack.append((x, y + 1))

    def moveSelection(self, pixels, dx, dy):
        # NEW: move a list of ((x,y), (r,g,b)) by (dx,dy)
        dx = int(dx)
        dy = int(dy)
        # clear originals
        for (x, y), _color in pixels:
            if 0 <= x < 64 and 0 <= y < 32:
                self.setColor(x, y, 0, 0, 0)
        # draw moved
        for (x, y), color in pixels:
            nx = x + dx
            ny = y + dy
            if 0 <= nx < 64 and 0 <= ny < 32:
                r, g, b = color
                self.setColor(nx, ny, r, g, b)


QGC_MAGIC = b"QGC1"


def saveQGC(frame: Frame, path: str) -> None:
    import json
    import zlib

    payload = {
        "w": 64,
        "h": 32,
        "pixels": frame.display,
    }
    raw = json.dumps(payload).encode("utf-8")
    compressed = zlib.compress(raw, level=6)
    with open(path, "wb") as f:
        f.write(QGC_MAGIC + compressed)


def loadQGC(path: str) -> Frame:
    import json
    import zlib

    data = open(path, "rb").read()
    if not data.startswith(QGC_MAGIC):
        raise ValueError("Invalid .qgc file")
    raw = zlib.decompress(data[len(QGC_MAGIC):])
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("w") != 64 or payload.get("h") != 32:
        raise ValueError("Unsupported frame size")
    return Frame(payload.get("pixels"))


def frame_to_rgb565_bytes(frame: Frame) -> bytes:
    if len(frame.display) != 32:
        raise ValueError("Frame must have 32 rows")
    for row in frame.display:
        if len(row) != 64:
            raise ValueError("Frame rows must have 64 pixels")

    data = bytearray(64 * 32 * 2)
    idx = 0
    for y in range(32):
        row = frame.display[y]
        for x in range(64):
            r, g, b = row[x]
            value = ((int(r) & 0x1F) << 11) | ((int(g) & 0x3F) << 5) | (int(b) & 0x1F)
            data[idx] = value & 0xFF
            data[idx + 1] = (value >> 8) & 0xFF
            idx += 2
    return bytes(data)


def _default_send_target() -> tuple[str, int]:
    import os
    from Networking.sendfile import DEFAULT_PORT

    host = os.getenv("QGRAPHIC_HOST", "127.0.0.1")
    port_text = os.getenv("QGRAPHIC_PORT")
    if port_text:
        try:
            return host, int(port_text)
        except ValueError:
            return host, DEFAULT_PORT
    return host, DEFAULT_PORT


def sendQGC(
    path: str,
    out_path: str | Path | None = None,
) -> None:
    from Networking.sendfile import default_frame_path, send_frame_bytes

    frame = loadQGC(path)
    frame_bytes = frame_to_rgb565_bytes(frame)
    resolved_out_path = default_frame_path() if out_path is None else out_path
    send_frame_bytes(frame_bytes, out_path=resolved_out_path)
