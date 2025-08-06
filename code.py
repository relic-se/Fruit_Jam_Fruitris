# SPDX-FileCopyrightText: 2025 Cooper Dalrymple (@relic-se)
#
# SPDX-License-Identifier: GPLv3
import supervisor
import sys
import terminalio
from displayio import Group, TileGrid, Bitmap, Palette, OnDiskBitmap
from adafruit_display_text.bitmap_label import Label
from adafruit_fruitjam.peripherals import request_display_config

request_display_config(320, 240)
display = supervisor.runtime.display

# initialize groups to hold visual elements
main_group = Group()

# any elements in this group will be scaled up 2x
scaled_group = Group(scale=2)
main_group.append(scaled_group)

# add background to the main group
background = Bitmap(display.width, display.height, 1)
bg_color = Palette(1)
bg_color[0] = 0x030060
main_group.append(TileGrid(
    background,
    pixel_shader=bg_color
))

GRID_WIDTH = 16
GRID_HEIGHT = 64
TETROMINO_SIZE = 4

tetrominos = [
    {
        "color": 0xf1e610, # yellow
        "pattern": [
            0, 0, 1, 0,
            0, 0, 1, 0,
            0, 0, 1, 0,
            0, 0, 1, 0
        ],
    },
    {
        "color": 0xe71c1f, # red
        "pattern": [
            0, 0, 1, 0,
            0, 1, 1, 0,
            0, 1, 0, 0,
            0, 0, 0, 0
        ],
    },
    {
        "color": 0xf39816, # orange
        "pattern": [
            0, 1, 0, 0,
            0, 1, 1, 0,
            0, 0, 1, 0,
            0, 0, 0, 0
        ],
    },
    {
        "color": 0x4b4c9c, # blue
        "pattern": [
            0, 0, 0, 0,
            0, 1, 1, 0,
            0, 1, 1, 0,
            0, 0, 0, 0
        ],
    },
    {
        "color": 0x6db52f, # green
        "pattern": [
            0, 0, 1, 0,
            0, 1, 1, 0,
            0, 0, 1, 0,
            0, 0, 0, 0
        ],
    },
    {
        "color": 0x428ccb, # light blue
        "pattern": [
            0, 0, 1, 0,
            0, 0, 1, 0,
            0, 1, 1, 0,
            0, 0, 0, 0
        ],
    },
    {
        "color": 0x772fb5, # purple
        "pattern": [
            0, 1, 0, 0,
            0, 1, 0, 0,
            0, 1, 1, 0,
            0, 0, 0, 0
        ]
    }
]

tile_bmp = OnDiskBitmap("bitmaps/tile.bmp")

class Tetromino:
    def __init__(self, pattern:list, color=0xffffff):
        self.x = (GRID_WIDTH - TETROMINO_SIZE) // 2
        self.y = 0
        self.pattern = pattern
        self.tile_tg = TileGrid(tile_bmp, pixel_shader=self._get_palette(color))
    
    def _get_palette(self, color:int) -> Palette:
        palette = Palette(4)
        palette[0] = color
        palette[1] = self._apply_brightness(color, 0.75)
        palette[2] = self._apply_brightness(color, 0.5)
        palette[3] = self._apply_brightness(color, 0.25)
        return palette

    def _apply_brightness(self, color:int, brightness:float) -> int:
        for i in range(3):
            # extract component value
            value = (color >> (8 * i)) & 0xff
            # apply brightness
            value = int(value * brightness)
            # remove previous value of component
            color &= 0xffffff ^ (0xff << (8 * i))
            # add new value back in
            color |= value << (8 * i)
        return color

# initial display refresh
display.refresh(target_frames_per_second=30)

while True:

    # check if any keys were pressed
    if available := supervisor.runtime.serial_bytes_available:
        key = sys.stdin.read(available)

        if "q" in key:
            supervisor.reload()
