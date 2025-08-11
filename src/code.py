# SPDX-FileCopyrightText: 2025 Cooper Dalrymple (@relic-se)
#
# SPDX-License-Identifier: GPLv3
import asyncio
import board
from displayio import Group, TileGrid, OnDiskBitmap, Palette
from keypad import Keys
from micropython import const
import os
from random import randint
import supervisor
import terminalio
import time

from adafruit_display_text.label import Label
from adafruit_fruitjam.peripherals import request_display_config
import adafruit_imageload

import gamepad
from usb.core import USBError

request_display_config(640, 480)
display = supervisor.runtime.display
display.auto_refresh = False

TILE_SIZE        = const(8)
SCALE            = 2 if display.width > 360 else 1
SCREEN_WIDTH     = display.width // SCALE // TILE_SIZE
SCREEN_HEIGHT    = display.height // SCALE // TILE_SIZE
WINDOW_GAP       = const(1)
GRID_WIDTH       = const(10)
GRID_HEIGHT      = SCREEN_HEIGHT - WINDOW_GAP * 2 - 2
TETROMINO_SIZE   = const(4)
GAME_SPEED_START = const(1)
GAME_SPEED_MOD   = 0.98  # modifies the game speed when line is cleared
WINDOW_WIDTH     = (SCREEN_WIDTH - GRID_WIDTH - 2) // 2 - WINDOW_GAP * 2
FONT_HEIGHT      = terminalio.FONT.get_bounding_box()[1]
NEOPIXELS        = False

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

# configure hardware
buttons = Keys((board.BUTTON1, board.BUTTON2, board.BUTTON3), value_when_pressed=False, pull=True)
if NEOPIXELS:
    from neopixel import NeoPixel
    neopixels = NeoPixel(board.NEOPIXEL, 5)

def copy_palette(palette:Palette) -> Palette:
    clone = Palette(len(palette))
    for i, color in enumerate(palette):
        # Add color to new_palette
        clone[i] = color
        # Set new_palette color index transparency
        if palette.is_transparent(i):
            clone.make_transparent(i)
    return clone

def apply_brightness(value:int, brightness:float) -> int:
    for i in range(3):
        c = (value >> (8 * i)) & 0xff  # extract color component (rgb)
        c = int(c * brightness)  # apply brightness
        c = min(max(c, 0x00), 0xff)  # clamp value to acceptable range
        value &= 0xffffff ^ (0xff << (8 * i))  # remove old component value
        value |= c << (8 * i)  # insert new component value
    return value

# load background tiles
bg_tiles, bg_palette = adafruit_imageload.load("bitmaps/bg.bmp")
bg_palette[0] = 0x030060
bg_palette[1] = 0x442a92

# load window border tiles
window_tiles, window_palette = adafruit_imageload.load("bitmaps/window.bmp")
window_palette.make_transparent(2)

# load tetromino tiles
tiles, tiles_palette = adafruit_imageload.load("bitmaps/tetromino.bmp")
tiles_palette.make_transparent(27)

# load face tiles
face_bmp, face_palette = adafruit_imageload.load("bitmaps/face.bmp")
face_palette.make_transparent(2)

# load drink bitmap
drink_bmp = OnDiskBitmap("bitmaps/drink.bmp")
drink_map = (12, 3, 5, 4, 1, 10, 14, 9, 7, 6, 8)  # convert level index to palette index
drink_map = tuple([(x, drink_bmp.pixel_shader[x]) for x in drink_map])  # copy colors
for i, color in drink_map:
    drink_bmp.pixel_shader[i] = 0x000000

# starting neopixels
if NEOPIXELS:
    for i in range(neopixels.n):
        neopixels[i] = drink_map[neopixels.n - 1 - i][1]
    neopixels.show()

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

    def __init__(self, text:str="", width:int=WINDOW_WIDTH, height:int=3, x:int=0, y:int=0, background_color=0x000000, border_color=0x808080, title_color=0xffffff):
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

        self.append(self._tg)

        if len(text):
            global text_group
            self._text = Label(terminalio.FONT, text=text, color=title_color)
            self._text.anchor_point = (0, 0)
            self._text.anchored_position = ((self.x + TILE_SIZE) * SCALE + 1, (self.y + TILE_SIZE) * SCALE - 1)
            text_group.append(self._text)
    
    @property
    def tile_width(self) -> int:
        return self._tg.width
    
    @property
    def tile_height(self) -> int:
        return self._tg.height

    @property
    def width(self) -> int:
        return self._tg.width * TILE_SIZE
    
    @property
    def height(self) -> int:
        return self._tg.height * TILE_SIZE
    
class NumberWindow(Window):
    def __init__(self, label:str|tuple, value:int|tuple=0, height:int=None, **args):
        if type(label) is not tuple:
            label = (label,)
        super().__init__(
            text=("\n" * SCALE).join(label),
            height=(FONT_HEIGHT * len(label)) // TILE_SIZE + 2 if height is None else height,
            **args
        )
        self._values = []
        for i in range(len(label)):
            value_label = Label(terminalio.FONT, color=0xffffff)
            value_label.anchor_point = (1, 0)
            value_label.anchored_position = (self.width - TILE_SIZE - 1, TILE_SIZE - 1 + i * FONT_HEIGHT)
            self._values.append(value_label)
            self.append(value_label)
        self.value = value

    @property
    def value(self) -> int|tuple:
        value = tuple([int(x.text) for x in self._values])
        return value[0] if len(value) == 1 else value
    
    @value.setter
    def value(self, value:int|tuple) -> None:
        if type(value) is not tuple:
            value = (value,)
        for i, label in enumerate(self._values):
            label.text = str(value[i  % len(value)])
    
class ScoreWindow(NumberWindow):
    
    def __init__(self, high_score:int=0, **args):
        super().__init__(
            label=("High" + (" Score" if SCALE - 1 else ""), "Score"),
            value=(high_score, 0),
            **args
        )
        self._read_save()

    @property
    def high_score(self) -> int:
        return self.value[0]
    
    @high_score.setter
    def high_score(self, value:int) -> None:
        self.value = (value, self.score)

    @property
    def score(self) -> int:
        return self.value[1]
    
    @score.setter
    def score(self, value:int) -> None:
        current = self.high_score
        self.value = (value if value > current else current, value)

    def reset(self) -> None:
        if self.score >= self.high_score:
            self._update_save()
        self.score = 0
    
    def _read_save(self) -> None:
        try:
            with open("/saves/fruitris.txt", "rt") as f:
                saved_score = int(f.readline())
                if saved_score > self.high_score:
                    self.high_score = saved_score
        except OSError:
            pass
        except ValueError:
            os.remove("/saves/fruitris.txt")
        return None

    def _update_save(self) -> None:
        try:
            with open("/saves/fruitris.txt", "wt") as f:
                f.write(str(self.high_score))
        except OSError:
            pass

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
        self._rotation = 0
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
        self._grid(value)
        for i in range(self._rotation):
            self._rotate_right(True)

    def _grid(self, value:list) -> None:
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

    def _wiggle(self, grid:list, force:bool = False) -> bool:
        # check if rotated piece fits
        collided = not force and self.check_collide(grid)
        if collided and not self.check_collide(grid, x=-1):  # move left if fits
            collided = False
            self.tile_x -= 1
        elif collided and not self.check_collide(grid, x=1):  # move right if fits
            collided = False
            self.tile_x += 1
        
        if not collided:
            self._grid(grid)  # update grid
            return True
        return False

    def rotate_right(self, force:bool = False) -> None:
        if self._rotate_right(force):
            self._rotation = (self._rotation + 1) % 4

    def _rotate_right(self, force:bool = False) -> bool:
        # rotate grid into copy
        grid = [
            [
                self._tilegrid[TETROMINO_SIZE - y - 1, x]
                for x in range(TETROMINO_SIZE)
            ]
            for y in range(TETROMINO_SIZE)
        ]

        # check if rotated piece fits or move left or right to fit
        return self._wiggle(grid, force)

    def rotate_left(self, force:bool = False) -> None:
        if self._rotate_left(force):
            self._rotation = (self._rotation - 1) % 4
     
    def _rotate_left(self, force:bool = False) -> bool:
        # rotate grid into copy
        grid = [
            [
                self._tilegrid[y, TETROMINO_SIZE - x - 1]
                for x in range(TETROMINO_SIZE)
            ]
            for y in range(TETROMINO_SIZE)
        ]
        
        # check if rotated piece fits or move left or right to fit
        return self._wiggle(grid, force)
    
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
    height=6,
    x=grid_window.tile_x + grid_window.tile_width + WINDOW_GAP,
    y=grid_window.tile_y,
)
main_group.append(tetromino_window)

next_tetromino = Tetromino(offset=False)
next_tetromino.tile_x = (WINDOW_WIDTH - TETROMINO_SIZE) // 2
next_tetromino.tile_y = 1
next_tetromino.rotate_left(True)
tetromino_window.append(next_tetromino)

# high score container
score_window = ScoreWindow(
    high_score=10000,
    x=tetromino_window.tile_x,
    y=grid_window.tile_y + tetromino_window.tile_height + WINDOW_GAP,
)
main_group.append(score_window)

# face
face_window = Window(
    background_color=0xd0d0d0,
    height=8,
    x=score_window.tile_x,
)
face_window.tile_y = grid_window.tile_y + grid_window.tile_height - face_window.tile_height
main_group.append(face_window)

face_tg = TileGrid(
    face_bmp, pixel_shader=face_palette,
    width=1, height=1,
    tile_width=face_bmp.width // 4, tile_height=face_bmp.height,
)
face_tg.x = (face_window.width - face_tg.tile_width) // 2
face_tg.y = (face_window.height - face_tg.tile_height) // 2
face_window.append(face_tg)

# level drink
level_window_y = tetromino_window.tile_y + (title_bmp.height // TILE_SIZE) + WINDOW_GAP
level_window = NumberWindow(
    label="Level", value=1,
    x=WINDOW_GAP, y=level_window_y,
    height=grid_window.tile_height + grid_window.tile_y - level_window_y,
)
main_group.append(level_window)

drink_tg = TileGrid(
    drink_bmp, pixel_shader=drink_bmp.pixel_shader,
    x=(level_window.width - drink_bmp.width) // 2,
    y=level_window.height - TILE_SIZE - drink_bmp.height - (level_window.width - TILE_SIZE * 2 - drink_bmp.width) // 2,
)
level_window.append(drink_tg)

def set_drink_level(value:float) -> None:
    global level_window

    # get current level color
    current_color = drink_map[(level_window.value - 1) % len(drink_map)][1]

    # set level in drink bitmap palette using map
    drink_value = int(value * (len(drink_map) - 1))
    for i, color in enumerate(drink_map):
        drink_tg.pixel_shader[color[0]] = current_color if drink_value >= i else 0x000000
    
    # set neopixel level
    if NEOPIXELS:
        for i in range(neopixels.n):
            neopixels[i] = apply_brightness(current_color, (value * neopixels.n) - (neopixels.n - 1 - i))
        neopixels.show()

current_tetromino = None
def get_next_tetromino() -> None:
    global current_tetromino, next_tetromino
    if current_tetromino is not None:
        grid_container.remove(current_tetromino)

    current_tetromino = Tetromino(next_tetromino.tetromino_index)
    current_tetromino.tile_x = (GRID_WIDTH - TETROMINO_SIZE) // 2  # center along x axis of grid
    grid_container.append(current_tetromino)

    next_tetromino.tetromino_index = get_random_tetromino_index()

def reset_game(game_over:bool = True) -> None:
    global current_lines, level_window, tilegrid, score_window

    # generate new tetromino
    get_next_tetromino()

    # clear grid
    for y in range(GRID_HEIGHT):
        for x in range(GRID_WIDTH):
            tilegrid[x, y] = 0

    # update face
    face_tg[0, 0] = (face_bmp.width // face_tg.tile_width) - 1 if game_over else 0

    # reset game variables
    score_window.reset()
    level_window.value = 1
    current_lines = 0
    set_drink_level(0)
reset_game(False)

def get_lines_per_level() -> int:
    global level_window
    return level_window.value * 10

def get_drop_speed() -> float:
    global level_window
    level = level_window.value
    if level >= 20:
        return 2 / 60
    elif level >= 17:
        return 3 / 60
    elif level >= 14:
        return 4 / 60
    elif level >= 11:
        return 5 / 60
    elif level == 10:
        return 6 / 60
    else:  # <= 9
        return (48 - (level_window.value - 1) * 5) / 60

def add_lines(lines:int) -> None:
    global level_window, current_lines
    if lines:
        score_window.score += (40, 100, 300, 1200)[lines - 1] * level_window.value
        current_lines += lines
        total_lines = get_lines_per_level()
        if current_lines > total_lines:
            level_window.value += 1
            current_lines = 0
        set_drink_level(current_lines / total_lines)

last_drop_time = None
async def tetromino_handler() -> None:
    global current_tetromino, current_lines, tilegrid, score_window, last_drop_time
    while True:

        # Synchronize with last manual drop
        while last_drop_time is not None:
            sync_drop_time = max(get_drop_speed() - (time.monotonic() - last_drop_time), 0)
            last_drop_time = None
            await asyncio.sleep(sync_drop_time)
            
        if current_tetromino.check_collide(y=1):  # place if collided
            current_tetromino.place()

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

            # update score
            add_lines(lines)

            # check if final move
            if current_tetromino.tile_y <= 0 and not lines:
                reset_game()  # TODO: game over
            else:  # update face
                face_tg[0, 0] = ((GRID_HEIGHT - current_tetromino.tile_y) * 3) // GRID_HEIGHT

            # generate new tetromino
            get_next_tetromino()

        else:  # move tetromino down
            current_tetromino.tile_y += 1

        display.refresh()
        
        await asyncio.sleep(get_drop_speed())

ACTION_ROTATE    = const(0)
ACTION_LEFT      = const(1)
ACTION_RIGHT     = const(2)
ACTION_SOFT_DROP = const(3)
ACTION_HARD_DROP = const(4)
ACTION_QUIT      = const(5)

def do_action(action:int) -> None:
    global current_tetromino, last_drop_time
    if action == ACTION_ROTATE:
        current_tetromino.rotate_right()
    elif action == ACTION_LEFT:
        current_tetromino.left()
    elif action == ACTION_RIGHT:
        current_tetromino.right()
    elif action == ACTION_SOFT_DROP:
        if current_tetromino.down():
            last_drop_time = time.monotonic()
    elif action == ACTION_HARD_DROP:
        spaces = 0
        while current_tetromino.down():
            spaces += 1
        score_window.score += spaces
        if spaces:
            last_drop_time = time.monotonic()
    elif action == ACTION_QUIT:
        supervisor.reload()
    
    display.refresh()

gamepad_map = (
    (gamepad.A,     ACTION_ROTATE),
    (gamepad.B,     ACTION_HARD_DROP),
    (gamepad.DOWN,  ACTION_SOFT_DROP),
    (gamepad.START, ACTION_QUIT),
    (gamepad.LEFT,  ACTION_LEFT),
    (gamepad.RIGHT, ACTION_RIGHT),
    (gamepad.UP,    ACTION_ROTATE),
)

async def gamepad_handler() -> None:
    while True:
        try:
            scan_result = gamepad.find_usb_device()
            if scan_result is None:
                await asyncio.sleep(.4)
                continue
            device = gamepad.InputDevice(scan_result)

            prev = 0
            for data in device.input_event_generator():
                if data is not None and isinstance(data, int):
                    diff = prev ^ data
                    prev = data
                    for button, action in gamepad_map:
                        if diff & button and data & button:
                            do_action(action)
                await asyncio.sleep(1/30)

        except (USBError, ValueError) as e:
            await asyncio.sleep(.4)

button_map = (
    ACTION_SOFT_DROP,  # button #1
    ACTION_ROTATE,     # button #2
    ACTION_QUIT,       # button #3
)

async def button_handler() -> None:
    global current_tetromino, buttons

    while True:

        # check hardware buttons
        if (event := buttons.events.get()) and event.pressed:
            do_action(button_map[event.key_number])

        await asyncio.sleep(1/30)

async def main():
    await asyncio.gather(
        asyncio.create_task(tetromino_handler()),
        asyncio.create_task(gamepad_handler()),
        asyncio.create_task(button_handler()),
    )

# initial display refresh
display.refresh()

asyncio.run(main())
