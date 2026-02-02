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