# SPDX-FileCopyrightText: 2025 Cooper Dalrymple (@relic-se)
#
# SPDX-License-Identifier: GPLv3
import supervisor
import sys
import terminalio
from displayio import Group, TileGrid, Bitmap, Palette
from adafruit_display_text.bitmap_label import Label
from adafruit_fruitjam.peripherals import request_display_config

request_display_config(320, 240)
display = supervisor.runtime.display

# initialize groups to hold visual elements
main_group = Group()

# any elements in this group will be scaled up 2x
scaled_group = Group(scale=2)
main_group.append(scaled_group)

# initial display refresh
display.refresh(target_frames_per_second=30)

while True:

    # check if any keys were pressed
    if available := supervisor.runtime.serial_bytes_available:
        key = sys.stdin.read(available)

        if "q" in key:
            supervisor.reload()
