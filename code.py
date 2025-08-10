# SPDX-FileCopyrightText: 2025 Cooper Dalrymple (@relic-se)
#
# SPDX-License-Identifier: GPLv3
import asyncio
import board
from displayio import Group, TileGrid, OnDiskBitmap, Palette
from keypad import Keys
from random import randint
import supervisor
import sys
import terminalio

from adafruit_display_text.label import Label
from adafruit_fruitjam.peripherals import request_display_config
import adafruit_imageload

request_display_config(640, 480)
display = supervisor.runtime.display

TILE_SIZE = 8
SCALE = 2 if display.width > 360 else 1
SCREEN_WIDTH = display.width // SCALE // TILE_SIZE
SCREEN_HEIGHT = display.height // SCALE // TILE_SIZE
GRID_WIDTH = 10
GRID_HEIGHT = 24
TETROMINO_SIZE = 4
GAME_SPEED_START = 1
GAME_SPEED_MOD = 0.98  # modifies the game speed when line is cleared
WINDOW_GAP = 2
WINDOW_WIDTH = (SCREEN_WIDTH - GRID_WIDTH - 2) // 2 - WINDOW_GAP * 2
FONT_HEIGHT = terminalio.FONT.get_bounding_box()[1]

TETROMINOS = [
    {
        "tile": 3, # yellow
        "pattern": [
            [0, 0, 1, 0],
            [0, 0, 1, 0],
            [0, 0, 1, 0],
            [0, 0, 1, 0]
        ],
    },
    {
        "tile": 1, # red
        "pattern": [
            [0, 0, 1, 0],
            [0, 1, 1, 0],
            [0, 1, 0, 0],
            [0, 0, 0, 0]
        ],
    },
    {
        "tile": 2, # orange
        "pattern": [
            [0, 1, 0, 0],
            [0, 1, 1, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 0]
        ],
    },
    {
        "tile": 6, # blue
        "pattern": [
            [0, 0, 0, 0],
            [0, 1, 1, 0],
            [0, 1, 1, 0],
            [0, 0, 0, 0]
        ],
    },
    {
        "tile": 4, # green
        "pattern": [
            [0, 0, 1, 0],
            [0, 1, 1, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 0]
        ],
    },
    {
        "tile": 5, # light blue
        "pattern": [
            [0, 0, 1, 0],
            [0, 0, 1, 0],
            [0, 1, 1, 0],
            [0, 0, 0, 0]
        ],
    },
    {
        "tile": 7, # purple
        "pattern": [
            [0, 1, 0, 0],
            [0, 1, 0, 0],
            [0, 1, 1, 0],
            [0, 0, 0, 0]
        ]
    }
]

def copy_palette(palette:Palette) -> Palette:
    clone = Palette(len(palette))
    for i, color in enumerate(palette):
        # Add color to new_palette
        clone[i] = color
        # Set new_palette color index transparency
        if palette.is_transparent(i):
            clone.make_transparent(i)
    return clone

# load background tiles
bg_tiles, bg_palette = adafruit_imageload.load("bitmaps/bg.bmp")

# load window border tiles
window_tiles, window_palette = adafruit_imageload.load("bitmaps/window.bmp")
window_palette.make_transparent(2)

# load tetromino tiles
tiles, tiles_palette = adafruit_imageload.load("bitmaps/tetromino.bmp")
tiles_palette.make_transparent(27)

class TileGroup(Group):

    @property
    def tile_x(self) -> int:
        return self.x // TILE_SIZE
    
    @tile_x.setter
    def tile_x(self, value:int) -> None:
        self.x = value * TILE_SIZE
    
    @property
    def tile_y(self) -> int:
        return self.y // TILE_SIZE
    
    @tile_y.setter
    def tile_y(self, value:int) -> None:
        self.y = value * TILE_SIZE
    
class Window(TileGroup):

    def __init__(self, text:str="", width:int=WINDOW_WIDTH, height:int=3, x:int=0, y:int=0, background_color=0x000000, border_color=0xffffff, title_color=0xffffff):
        global window_tiles, window_palette
        super().__init__(
            x=x * TILE_SIZE,
            y=y * TILE_SIZE,
        )

        if width < 3 or height < 3:
            raise ValueError("width/height must be at least 3 tiles")
        
        palette = copy_palette(window_palette)
        palette[1] = background_color
        palette[3] = border_color

        # load grid border tiles, setup palette and tilegrid
        self._tg = TileGrid(
            window_tiles, pixel_shader=palette,
            width=width, height=height,
            tile_width=TILE_SIZE, tile_height=TILE_SIZE,
            default_tile=4,  # center tile
        )
        self._update_tiles()
        self.append(self._tg)

        if len(text):
            global text_group
            self._text = Label(terminalio.FONT, text=text, color=title_color)
            self._text.anchor_point = (0, 0)
            self._text.anchored_position = ((self.x + TILE_SIZE) * SCALE + 1, (self.y + TILE_SIZE) * SCALE - 1)
            text_group.append(self._text)
    
    def _update_tiles(self) -> None:
        # set corner tiles
        self._tg[0, 0] = 0
        self._tg[self._tg.width - 1, 0] = 2
        self._tg[0, self._tg.height - 1] = 6
        self._tg[self._tg.width - 1, self._tg.height - 1] = 8

        # set edge tiles
        for i in range(1, self._tg.width - 1):
            self._tg[i, 0] = 1
            self._tg[i, self._tg.height - 1] = 7
        for i in range(1, self._tg.height - 1):
            self._tg[0, i] = 3
            self._tg[self._tg.width - 1, i] = 5

    @property
    def tile_width(self) -> int:
        return self._tg.width
    
    @tile_width.setter
    def tile_width(self, value:int) -> None:
        self._tg.width = value
        self._update_tiles()
    
    @property
    def tile_height(self) -> int:
        return self._tg.height
    
    @tile_height.setter
    def tile_height(self, value:int) -> None:
        self._tg.height = value
        self._update_tiles()

    @property
    def width(self) -> int:
        return self._tg.width * TILE_SIZE
    
    @property
    def height(self) -> int:
        return self._tg.height * TILE_SIZE
    
class ScoreWindow(Window):
    
    def __init__(self, high_score:int=0, **args):
        super().__init__(
            text="High{:s}{:s}Score".format(" Score" if SCALE - 1 else "", "\n" * SCALE),
            height=(FONT_HEIGHT * 2) // TILE_SIZE + 2,
            **args
        )
        self._score = Label(terminalio.FONT, text="0\n0", color=0xffffff)
        self._score.anchor_point = (1, 0)
        self._score.anchored_position = (self.width - TILE_SIZE - 1, TILE_SIZE - 1)
        self.append(self._score)

        self.high_score = high_score
        self.score = 0

    @property
    def values(self) -> tuple:
        return tuple([int(x) for x in self._score.text.split("\n")])
    
    @values.setter
    def values(self, value:tuple) -> None:
        self._score.text = "\n".join([str(x) for x in value])

    @property
    def score(self) -> int:
        return self.values[0]
    
    @score.setter
    def score(self, value:int) -> None:
        current = self.values[0]
        self.values = (value if value > current else current, value)

    @property
    def high_score(self) -> int:
        return self.values[0]
    
    @high_score.setter
    def high_score(self, value:int) -> None:
        self.values = (value, self.values[1])

def get_random_tetromino_index() -> int:
    return randint(0, len(TETROMINOS) - 1)

class Tetromino(TileGroup):

    def __init__(self, index:int=None, offset:bool=True):
        super().__init__()

        # setup tilegrid
        self._tilegrid = TileGrid(
            tiles, pixel_shader=tiles_palette,
            width=TETROMINO_SIZE, height=TETROMINO_SIZE,
            tile_width=TILE_SIZE, tile_height=TILE_SIZE,
        )

        # update grid tiles (use random tetromino if not specified)
        self.tetromino_index = index if index is not None else get_random_tetromino_index()

        # move tetromino to top depending on pattern
        if offset:
            for i in range(TETROMINO_SIZE * TETROMINO_SIZE):
                x, y = i % TETROMINO_SIZE, i // TETROMINO_SIZE
                if self._tilegrid[x, y]:
                    self.tile_y = -y
                    break

        self.append(self._tilegrid)

    @property
    def tetromino_index(self) -> int:
        return self._index
    
    @tetromino_index.setter
    def tetromino_index(self, value:int) -> None:
        self._index = value
        pattern, self._tile = TETROMINOS[value]["pattern"], TETROMINOS[value]["tile"]  # get tetromino data from index
        self.grid = pattern  # update tilegrid

    @property
    def collided(self) -> bool:
        return self.check_collide(self._tilegrid)
    
    def check_collide(self, grid:list|TileGrid=None, x:int=0, y:int=0) -> bool:
        global tilegrid
        if grid is None:
            grid = self._tilegrid
        for i in range(TETROMINO_SIZE):
            for j in range(TETROMINO_SIZE):
                if (grid[i][j] if type(grid) is list else grid[j, i]):
                    tile_x, tile_y = j + self.tile_x + x, i + self.tile_y + y
                    if tile_x < 0 or tile_x >= GRID_WIDTH:  # if we've hit the sides
                        return True
                    if tile_y >= GRID_HEIGHT:  # if we've hit the bottom
                        return True
                    if tilegrid[tile_x, tile_y]:  # if we've hit the grid
                        return True
        return False
    
    @property
    def grid(self) -> list:
        return [
            [1 if self._tilegrid[x, y] else 0 for x in range(TETROMINO_SIZE)]
            for y in range(TETROMINO_SIZE)
        ]
    
    @grid.setter
    def grid(self, value:list) -> None:
        for y in range(TETROMINO_SIZE):
            for x in range(TETROMINO_SIZE):
                self._tilegrid[x, y] = self._tile if value[y][x] else 0
    
    def place(self) -> None:
        global tilegrid
        for y in range(TETROMINO_SIZE):
            for x in range(TETROMINO_SIZE):
                grid_x, grid_y = x + self.tile_x, y + self.tile_y
                if self._tilegrid[x, y] and 0 <= grid_x < GRID_WIDTH and 0 <= grid_y < GRID_HEIGHT:
                    tilegrid[grid_x, grid_y] = self._tilegrid[x, y]

    def rotate(self) -> bool:
        return self.rotate_right()

    def rotate_right(self) -> bool:
        # rotate grid into copy
        grid = [
            [
                self._tilegrid[TETROMINO_SIZE - y - 1, x]
                for x in range(TETROMINO_SIZE)
            ]
            for y in range(TETROMINO_SIZE)
        ]

        # check if rotated piece fits
        if self.check_collide(grid):
            return False
        
        # update grid
        for y in range(TETROMINO_SIZE):
            for x in range(TETROMINO_SIZE):
                self._tilegrid[x, y] = grid[y][x]
        return True
    
    def rotate_left(self) -> bool:
        # rotate grid into copy
        grid = [
            [
                self._tilegrid[y, TETROMINO_SIZE - x - 1]
                for x in range(TETROMINO_SIZE)
            ]
            for y in range(TETROMINO_SIZE)
        ]

        # check if rotated piece fits
        if self.check_collide(grid):
            return False
        
        # update grid
        self.grid = grid
        return True
    
    def move(self, x:int=0, y:int=0) -> bool:
        if self.check_collide(x=x, y=y):
            return False
        self.tile_x += x
        self.tile_y += y
        return True
    
    def left(self) -> bool:
        return self.move(x=-1)
    
    def right(self) -> bool:
        return self.move(x=1)
    
    def down(self) -> bool:
        return self.move(y=1)

# initialize groups to hold visual elements
text_group = Group()
main_group = Group(scale=SCALE)
text_group.append(main_group)
display.root_group = text_group

# setup background color palette
bg_palette[0] = 0x030060
bg_palette[1] = 0x442a92

# use terminalio font as tile sheet to write to background
bg_grid = TileGrid(
    bg_tiles, pixel_shader=bg_palette,
    width=SCREEN_WIDTH, height=SCREEN_HEIGHT,
    tile_width=TILE_SIZE, tile_height=TILE_SIZE,
)

# randomly generate background with "/" and "\" to create a maze
for y in range(SCREEN_HEIGHT):
    for x in range(SCREEN_WIDTH):
        bg_grid[x, y] = randint(0, (bg_tiles.width // TILE_SIZE) - 1)

# add background to display
main_group.append(bg_grid)

# setup grid container
grid_window = Window(
    width=GRID_WIDTH + 2, height=GRID_HEIGHT + 2,
    x=(SCREEN_WIDTH - GRID_WIDTH - 2) // 2,
    y=(SCREEN_HEIGHT - GRID_HEIGHT - 2) // 2,
)
main_group.append(grid_window)

# setup grid
grid_container = Group(x=TILE_SIZE, y=TILE_SIZE)
tilegrid = TileGrid(
    tiles, pixel_shader=tiles_palette,
    width=GRID_WIDTH, height=GRID_HEIGHT,
    tile_width=TILE_SIZE, tile_height=TILE_SIZE,
)
grid_container.append(tilegrid)
grid_window.append(grid_container)

# display title image
title_bmp = OnDiskBitmap("bitmaps/title.bmp")
title_bmp.pixel_shader.make_transparent(8)
title_tg = TileGrid(
    title_bmp, pixel_shader=title_bmp.pixel_shader,
    y=grid_window.y,
    x=((SCREEN_WIDTH - GRID_WIDTH - 2) * TILE_SIZE) // 4 - title_bmp.width // 2,
)
main_group.append(title_tg)

# next tetromino container
tetromino_window = Window(
    text="Next",
    height=4,
    x=grid_window.tile_x + GRID_WIDTH + 2 + WINDOW_GAP,
    y=grid_window.tile_y,
)
main_group.append(tetromino_window)

next_tetromino = Tetromino(offset=False)
next_tetromino.tile_x = WINDOW_WIDTH - TETROMINO_SIZE - 1
tetromino_window.append(next_tetromino)

# high score container
score_window = ScoreWindow(
    x=tetromino_window.tile_x,
    y=grid_window.tile_y + tetromino_window.tile_height + WINDOW_GAP,
)
main_group.append(score_window)

# initial display refresh
display.refresh(target_frames_per_second=30)

# game variables
current_tetromino = None
game_speed = GAME_SPEED_START
current_level = 0

def reset_game() -> None:
    global current_tetromino, tilegrid, game_speed, score_window

    # reset old tetromino
    del current_tetromino
    current_tetromino = None

    # clear grid
    for y in range(GRID_HEIGHT):
        for x in range(GRID_WIDTH):
            tilegrid[x, y] = 0

    # reset game variables
    game_speed = GAME_SPEED_START
    score_window.score = 0

def get_next_tetromino() -> None:
    global current_tetromino, next_tetromino

    current_tetromino = Tetromino(next_tetromino.tetromino_index)
    current_tetromino.tile_x = (GRID_WIDTH - TETROMINO_SIZE) // 2  # center along x axis of grid
    grid_container.append(current_tetromino)

    next_tetromino.tetromino_index = get_random_tetromino_index()
    next_tetromino.rotate_left()

def update_tetromino() -> None:
    global current_tetromino, current_level, game_speed, tilegrid, score_window
    
    # generate new tetromino
    if current_tetromino is None:
        get_next_tetromino()
    elif current_tetromino.check_collide(y=1):  # place if collided
        current_tetromino.place()
        grid_container.remove(current_tetromino)

        # check for line clearing
        lines = 0
        for y in range(max(current_tetromino.tile_y, 0), min(current_tetromino.tile_y + TETROMINO_SIZE, GRID_HEIGHT)):
            cleared = True
            for x in range(GRID_WIDTH):
                if not tilegrid[x, y]:
                    cleared = False
                    break
            if cleared:
                lines += 1
                # move tiles down (clears current line)
                for i in range(y, 1, -1):
                    for x in range(GRID_WIDTH):
                        tilegrid[x, i] = tilegrid[x, i - 1]
                
                # clear top line
                for x in range(GRID_WIDTH):
                    tilegrid[x, 0] = 0
        
        if lines:
            game_speed *= GAME_SPEED_MOD
            score_window.score += (40, 100, 300, 1200)[lines - 1] * (current_level + 1)

        # check if final move
        if current_tetromino.tile_y <= 0 and not lines:
            reset_game()  # TODO: game over
        
        # reset old tetromino
        del current_tetromino
        current_tetromino = None
    else:  # move tetromino down
        current_tetromino.tile_y += 1

async def tetromino_handler() -> None:
    global game_speed
    while True:
        update_tetromino()
        await asyncio.sleep(game_speed)

buttons = Keys((board.BUTTON1, board.BUTTON2, board.BUTTON3), value_when_pressed=False, pull=True)

async def input_handler() -> None:
    global current_tetromino, buttons

    while True:

        # check if any keys were pressed
        if available := supervisor.runtime.serial_bytes_available:
            key = sys.stdin.read(available).lower()

            if current_tetromino is not None:
                # up
                if key == "w" or key == "\x1b[a" or key == " " or key == "\n":
                    current_tetromino.rotate()
                
                # left
                if key == "a" or key == "\x1b[d":
                    current_tetromino.left()
                
                # right
                if key == "d" or key == "\x1b[c":
                    current_tetromino.right()

                # down
                if key == "s" or key == "\x1b[b":
                    current_tetromino.down()

            if key == "q":
                supervisor.reload()

        # check hardware buttons
        if (event := buttons.events.get()) and event.pressed:
            if current_tetromino is not None:
                # button #1
                if event.key_number == 0:
                    current_tetromino.down()
                
                # button #2
                if event.key_number == 1:
                    current_tetromino.rotate()
            
            # button #3
            if event.key_number == 2:
                supervisor.reload()

        await asyncio.sleep(1/30)

async def main():
    await asyncio.gather(
        asyncio.create_task(tetromino_handler()),
        asyncio.create_task(input_handler())
    )

asyncio.run(main())
