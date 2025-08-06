# SPDX-FileCopyrightText: 2025 Cooper Dalrymple (@relic-se)
#
# SPDX-License-Identifier: GPLv3
import asyncio
import board
from displayio import Group, TileGrid, Bitmap, Palette
from keypad import Keys
from random import randint
import supervisor
import sys
import terminalio

from adafruit_display_text.bitmap_label import Label
from adafruit_fruitjam.peripherals import request_display_config
import adafruit_imageload

request_display_config(320, 240)
display = supervisor.runtime.display

# initialize groups to hold visual elements
main_group = Group()
display.root_group = main_group

# add background to the main group
background = Bitmap(display.width, display.height, 1)
bg_color = Palette(1)
bg_color[0] = 0x030060
main_group.append(TileGrid(
    background,
    pixel_shader=bg_color
))

TILE_SIZE = 8
SCREEN_WIDTH = display.width // TILE_SIZE
SCREEN_HEIGHT = display.height // TILE_SIZE
GRID_WIDTH = 40
GRID_HEIGHT = 30
TETROMINO_SIZE = 4
GAME_SPEED_START = 1
GAME_SPEED_MOD = 0.98  # modifies the game speed when line is cleared

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

tiles, tiles_palette = adafruit_imageload.load("bitmaps/tiles.bmp")
tiles_palette.make_transparent(27)

tilegrid = TileGrid(
    tiles, pixel_shader=tiles_palette,
    width=GRID_WIDTH, height=GRID_HEIGHT,
    tile_width=TILE_SIZE, tile_height=TILE_SIZE,
)
main_group.append(tilegrid)

class Tetromino(Group):

    def __init__(self, pattern:list, tile:int=1):
        super().__init__()
        self.tile_x = (GRID_WIDTH - TETROMINO_SIZE) // 2
        if tile == 3:  # square
            self.tile_y = -1
        
        self._tile = tile

        self._tilegrid = TileGrid(
            tiles, pixel_shader=tiles_palette,
            width=TETROMINO_SIZE, height=TETROMINO_SIZE,
            tile_width=TILE_SIZE, tile_height=TILE_SIZE,
        )
        self.grid = pattern

        self.append(self._tilegrid)

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
                if self._tilegrid[x, y]:
                    tilegrid[x + self.tile_x, y + self.tile_y] = self._tilegrid[x, y]

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

# game variables
tetromino = None
game_speed = GAME_SPEED_START

# initial display refresh
display.refresh(target_frames_per_second=30)

def reset_game() -> None:
    global tetromino, tilegrid, game_speed

    # reset old tetromino
    del tetromino
    tetromino = None

    # clear grid
    for y in range(GRID_HEIGHT):
        for x in range(GRID_WIDTH):
            tilegrid[x, y] = 0

    # reset game variables
    game_speed = GAME_SPEED_START

def update_tetromino() -> None:
    global tetromino, game_speed, tilegrid

    # generate new tetromino
    if tetromino is None:
        index = randint(0, len(TETROMINOS) - 1)
        tetromino = Tetromino(TETROMINOS[index]["pattern"], TETROMINOS[index]["tile"])
        main_group.append(tetromino)

    # place if collided
    if tetromino.check_collide(y=1):
        tetromino.place()
        main_group.remove(tetromino)

        # check for line clearing
        did_clear = False
        for y in range(GRID_HEIGHT):
            cleared = True
            for x in range(GRID_WIDTH):
                if not tilegrid[x, y]:
                    cleared = False
                    break
            if cleared:
                did_clear = True
                # move tiles down (clears current line)
                for i in range(y, 1, -1):
                    for x in range(GRID_WIDTH):
                        tilegrid[x, i] = tilegrid[x, i - 1]
                
                # clear top line
                for x in range(GRID_WIDTH):
                    tilegrid[x, 0] = 0
        
        if did_clear:
            game_speed *= GAME_SPEED_MOD

        # check if final move
        if tetromino.tile_y <= 0 and not did_clear:
            reset_game()  # TODO: game over
        
        # reset old tetromino
        del tetromino
        tetromino = None
    else:
        # move tetromino down
        tetromino.tile_y += 1

async def tetromino_handler() -> None:
    global tetromino, tilegrid, game_speed

    while True:
        update_tetromino()
        await asyncio.sleep(game_speed)

buttons = Keys((board.BUTTON1, board.BUTTON2, board.BUTTON3), value_when_pressed=False, pull=True)

async def input_handler() -> None:
    global tetromino, buttons

    while True:

        # check if any keys were pressed
        if available := supervisor.runtime.serial_bytes_available:
            key = sys.stdin.read(available).lower()

            if tetromino is not None:
                # up
                if key == "w" or key == "\x1b[a" or key == " " or key == "\n":
                    tetromino.rotate()
                
                # left
                if key == "a" or key == "\x1b[d":
                    tetromino.left()
                
                # right
                if key == "d" or key == "\x1b[c":
                    tetromino.right()

                # down
                if key == "s" or key == "\x1b[b":
                    tetromino.down()

            if key == "q":
                supervisor.reload()

        # check hardware buttons
        if (event := buttons.events.get()) and event.pressed:
            if tetromino is not None:
                # button #1
                if event.key_number == 0:
                    tetromino.down()
                
                # button #2
                if event.key_number == 1:
                    tetromino.rotate()
            
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
