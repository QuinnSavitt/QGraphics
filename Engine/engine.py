class Frame:
    # Frame represents a 64x32 pixel display where each pixel is an RGB565 tuple.
    def __init__(self, start=None):
        if start is None:
            self.display = [[(0, 0, 0) for x in range(64)] for y in range(32)]
        else:
            # TODO: validate start
            self.display = start

    def setRed(self, x, y, value):
        r, g, b = self.display[y][x]
        self.display[y][x] = (value, g, b)

    def setGreen(self, x, y, value):
        r, g, b = self.display[y][x]
        self.display[y][x] = (r, value, b)

    def setBlue(self, x, y, value):
        r, g, b = self.display[y][x]
        self.display[y][x] = (r, g, value)

    def setColor(self, x, y, r, g, b):
        self.display[y][x] = (r, g, b)

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