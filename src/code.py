# SPDX-FileCopyrightText: 2025 Cooper Dalrymple (@relic-se)
# SPDX-FileCopyrightText: 2025 RetiredWizard
#
# SPDX-License-Identifier: GPLv3
from array import array
import asyncio
import board
from displayio import Group, TileGrid, OnDiskBitmap, Palette
import json
from micropython import const
import os
from random import randint
import supervisor
import terminalio
import time
import vectorio

from adafruit_display_text.label import Label
from adafruit_fruitjam.peripherals import request_display_config
import adafruit_imageload
import adafruit_pathlib as pathlib

import gamepad
from usb.core import USBError

try:
    request_display_config()  # attempt to use default display size
except (ValueError, TypeError):
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

# initialize groups to hold visual elements
root_group = Group()
display.root_group = root_group

loading_group = Group()
root_group.append(loading_group)

main_group = Group(scale=SCALE)
main_group.hidden = True
root_group.append(main_group)

text_group = Group()
text_group.hidden = True
root_group.append(text_group)

# loading text
loading_text = Label(terminalio.FONT, text="Loading Fruitris...", color=0xffffff)
loading_text.anchor_point = (.5, .5)
loading_text.anchored_position = (display.width//2, display.height//2)
loading_group.append(loading_text)

# loading bar
loading_bar_palette = Palette(1)
loading_bar_palette[0] = 0xffffff
loading_bar = vectorio.Rectangle(
    pixel_shader=loading_bar_palette,
    width=1, height=24//(3-SCALE),
)
loading_bar.y = display.height - loading_bar.height
loading_group.append(loading_bar)

LOADING_STEPS = 33
loading_step = 0
def increment_loading_bar(steps:int=1) -> None:
    global loading_step
    loading_step += steps
    loading_bar.width = int(display.width * (loading_step / LOADING_STEPS))
    display.refresh()

increment_loading_bar()  # display loading screen

# read config
launcher_config = {}
if pathlib.Path("/launcher.conf.json").exists():
    with open("/launcher.conf.json", "r") as f:
        launcher_config = json.load(f)

increment_loading_bar()

# Check if DAC is connected
i2c = board.I2C()
while not i2c.try_lock():
    time.sleep(0.01)
tlv320_present = 0x18 in i2c.scan()
i2c.unlock()

if tlv320_present:
    from audiobusio import I2SOut
    from audiomixer import Mixer
    import synthio

    import adafruit_tlv320
    import relic_waveform

    dac = adafruit_tlv320.TLV320DAC3100(i2c)

    # set sample rate & bit depth
    dac.configure_clocks(sample_rate=32000, bit_depth=16)

    if "tlv320" in launcher_config and launcher_config["tlv320"].get("output") == "speaker":
        # use speaker
        dac.speaker_output = True
        dac.dac_volume = launcher_config["tlv320"].get("volume", 5)  # dB
    else:
        # use headphones
        dac.headphone_output = True
        dac.dac_volume = launcher_config["tlv320"].get("volume", 0) if "tlv320" in launcher_config else 0  # dB

    # setup audio output
    audio = I2SOut(board.I2S_BCLK, board.I2S_WS, board.I2S_DIN)
    mixer = Mixer(
        voice_count=3,
        sample_rate=dac.sample_rate,
        channel_count=1,
        bits_per_sample=dac.bit_depth,
        buffer_size=8192,
    )
    mixer.voice[0].level = 0.3  # bass level
    mixer.voice[1].level = 0.1  # melody level
    mixer.voice[2].level = 0.2  # sfx level
    audio.play(mixer)

    synth = synthio.Synthesizer(
        sample_rate=dac.sample_rate,
        channel_count=mixer.channel_count,
    )
    mixer.voice[2].play(synth)

    increment_loading_bar()

    # load midi tracks
    def read_midi_track(path:str, waveform=None, envelope:synthio.Envelope=None, ppqn:int=240, tempo:int=168) -> synthio.MidiTrack:
        global dac
        with open(path, "rb") as f:
            # Ignore SMF header
            if f.read(4) == b'MThd':
                f.read(22)
            else:
                f.seek(f.tell() - 4)

            return synthio.MidiTrack(
                f.read(), tempo=ppqn*tempo//60,
                sample_rate=dac.sample_rate,
                waveform=waveform, envelope=envelope,
            )

    song_bass = read_midi_track(
        "samples/bass.mid",
        waveform = relic_waveform.mix(
            (relic_waveform.triangle(), .9),
            (relic_waveform.saw(), .2),
        ),
        envelope = synthio.Envelope(
            attack_time=.01, attack_level=1,
            decay_time=.05, sustain_level=.5,
            release_time=.1,
        ),
    )

    increment_loading_bar()

    song_melody = read_midi_track(
        "samples/melody.mid",
        waveform = relic_waveform.mix(
            (relic_waveform.square(), .2),
            (relic_waveform.saw(frequency=2, reverse=True), .3),
            (relic_waveform.sine(frequency=3), .4),
        ),
        envelope = synthio.Envelope(
            attack_time=.02, attack_level=1,
            decay_time=.1, sustain_level=.2,
            release_time=.04,
        ),
    )

    increment_loading_bar()

    # sfx notes
    SFX_DROP = synthio.Note(
        frequency=synthio.midi_to_hz(78),
        waveform=relic_waveform.triangle(),
        envelope=synthio.Envelope(attack_time=0, decay_time=.1, sustain_level=0),
        amplitude=.2,
    )

    increment_loading_bar()

    SFX_HARD_DROP = synthio.Note(
        frequency=synthio.midi_to_hz(50),
        waveform=relic_waveform.saw(),
        envelope=synthio.Envelope(attack_time=0, decay_time=.3, sustain_level=0),
        amplitude=.3,
        bend=synthio.LFO(
            waveform=relic_waveform.saw(reverse=True, frequency=.5, phase=.5),
            rate=1/.3, once=True,
        ),
    )

    increment_loading_bar()

    SFX_MOVE = synthio.Note(
        frequency=synthio.midi_to_hz(65),
        waveform=relic_waveform.noise(),
        envelope=synthio.Envelope(attack_time=.025, decay_time=.05, sustain_level=0),
        amplitude=.2,
        bend=synthio.LFO(
            waveform=relic_waveform.saw(frequency=.5, phase=.5),
            rate=1/.075, scale=3/12, once=True,
        ),
        filter=synthio.Biquad(synthio.FilterMode.LOW_PASS, 5000),
    )

    increment_loading_bar()

    SFX_ROTATE = synthio.Note(
        frequency=synthio.midi_to_hz(55),
        waveform=relic_waveform.mix(
            relic_waveform.saw(),
            (relic_waveform.noise(), .5),
        ),
        envelope=synthio.Envelope(attack_time=.05, decay_time=.05, sustain_level=0),
        amplitude=.3,
        filter=synthio.Biquad(
            synthio.FilterMode.LOW_PASS,
            synthio.LFO(
                waveform=relic_waveform.triangle(frequency=.5),
                rate=1/.1, scale=4000, offset=100, once=True,
            ),
            Q=2,
        ),
    )

    increment_loading_bar()

    SFX_ERROR = synthio.Note(
        frequency=synthio.midi_to_hz(31),
        waveform=relic_waveform.mix(
            relic_waveform.square(),
            (relic_waveform.noise(), .3),
        ),
        envelope=synthio.Envelope(attack_time=0, decay_time=.1, sustain_level=0),
        amplitude=.3,
        filter=synthio.Biquad(synthio.FilterMode.LOW_PASS, 8000),
    )

    increment_loading_bar()

    SFX_PLACE = synthio.Note(
        frequency=synthio.midi_to_hz(43),
        waveform=relic_waveform.mix(
            relic_waveform.square(),
            (relic_waveform.noise(), .4),
        ),
        envelope=synthio.Envelope(attack_time=0, decay_time=.1, sustain_level=0),
        amplitude=.6,
        bend=synthio.LFO(
            waveform=relic_waveform.saw(frequency=.5, phase=.5),
            rate=1/.1, scale=5/12, once=True,
        ),
        filter=synthio.Biquad(
            synthio.FilterMode.LOW_PASS,
            synthio.LFO(
                waveform=relic_waveform.saw(frequency=.5, phase=.5),
                rate=1/.1, scale=-800, offset=1000, once=True,
            ),
        ),
    )

    increment_loading_bar()

    def bend_melody(*notes:int) -> array:
        return array('h', [x * 32767 // 24 for x in notes])

    SFX_CLEAR = synthio.Note(
        frequency=synthio.midi_to_hz(74),
        waveform=relic_waveform.mix(
            (relic_waveform.saw(), .5),
            (relic_waveform.saw(frequency=1+5/12), .5),
            (relic_waveform.saw(frequency=1+7/12), .5),
        ),
        amplitude=synthio.LFO(
            waveform=array('h', [32767, 32767, 0, 0]),
            scale=.2, rate=.75, interpolate=False, once=True,
        ),
        bend=synthio.LFO(
            waveform=bend_melody(0, 1, 4, 7, 19, 19, 19),
            rate=1.5, scale=-2, interpolate=False, once=True,
        ),
        filter=synthio.Biquad(synthio.FilterMode.LOW_PASS, synthio.LFO(scale=400, offset=1600, rate=5), Q=1.2),
    )

    increment_loading_bar()

    SFX_TETRIS = synthio.Note(
        frequency=synthio.midi_to_hz(62),
        waveform=relic_waveform.mix(
            (relic_waveform.saw(), .5),
            (relic_waveform.saw(frequency=1+5/12), .5),
            (relic_waveform.saw(frequency=1+7/12), .5),
        ),
        amplitude=synthio.LFO(
            waveform=array('h', [32767, 32767, 0, 0]),
            scale=.2, rate=1, interpolate=False, once=True,
        ),
        bend=synthio.LFO(
            waveform=bend_melody(0, 2, 4, 5, 7, 8, 10, 12, 17, 17),
            rate=2, scale=2, interpolate=False, once=True,
        ),
        filter=synthio.Biquad(synthio.FilterMode.LOW_PASS, synthio.LFO(scale=400, offset=1600, rate=5), Q=1.2),
    )

    increment_loading_bar()

    SFX_GAME_OVER = synthio.Note(
        frequency=synthio.midi_to_hz(50),
        waveform=relic_waveform.mix(
            relic_waveform.square(),
            (relic_waveform.square(frequency=1+7/12), .4),
            (relic_waveform.noise(), .4),
        ),
        amplitude=synthio.LFO(
            waveform=array('h', [32767, 32767, 0, 0]),
            scale=.2, rate=.125, interpolate=False, once=True,
        ),
        bend=synthio.LFO(
            waveform=bend_melody(0, 2, 4, 5, 7, 7),
            rate=.25, scale=-2, interpolate=False, once=True,
        ),
        filter=synthio.Biquad(
            synthio.FilterMode.LOW_PASS,
            synthio.LFO(
                waveform=array('h', [0, -32767]),
                scale=2500, offset=3000, rate=.25, once=True,
            ),
            Q=2.5,
        ),
    )

    increment_loading_bar()

else:
    SFX_DROP = None
    SFX_HARD_DROP = None
    SFX_MOVE = None
    SFX_ROTATE = None
    SFX_ERROR = None
    SFX_PLACE = None
    SFX_CLEAR = None
    SFX_TETRIS = None
    SFX_GAME_OVER = None

    increment_loading_bar(12)

def play_song(reset:bool=True) -> None:
    if tlv320_present:
        if reset:
            set_song_tempo()  # reset tempo
        mixer.play(song_bass, voice=0, loop=True)
        mixer.play(song_melody, voice=1, loop=True)

def stop_song() -> None:
    if tlv320_present:
        mixer.stop_voice(0)
        mixer.stop_voice(1)

def get_song_tempo(ppqn:int=240) -> int:
    if tlv320_present and hasattr(song_bass, "tempo"):
        return song_bass.tempo*60//ppqn
    else:
        return 168

def set_song_tempo(tempo:int=168, ppqn:int=240) -> None:
    if tlv320_present and hasattr(song_bass, "tempo"):
        for track in (song_bass, song_melody):
            track.tempo = ppqn*tempo//60

def play_sfx(note:synthio.Note) -> None:
    if tlv320_present:
        for lfo in (note.bend, note.amplitude, (note.filter.frequency if type(note.filter) is synthio.Biquad else None)):
            if type(lfo) is synthio.LFO:
                lfo.retrigger()
        synth.release_all_then_press(note)

# configure hardware
if "BUTTON1" in dir(board) and "BUTTON2" in dir(board) and "BUTTON3" in dir(board):
    from keypad import Keys
    buttons = Keys((board.BUTTON1, board.BUTTON2, board.BUTTON3), value_when_pressed=False, pull=True)
else:
    buttons = None

if NEOPIXELS and "NEOPIXEL" in dir(board):
    from neopixel import NeoPixel
    neopixels = NeoPixel(board.NEOPIXEL, 5)

# load tiles
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

increment_loading_bar()

# load pause tiles
pause_tiles, pause_palette = adafruit_imageload.load("bitmaps/pause.bmp")
pause_palette.make_transparent(1)
PAUSE_TILE_SIZE = min(pause_tiles.width, pause_tiles.height)

increment_loading_bar()

# load window border tiles
window_tiles, window_palette = adafruit_imageload.load("bitmaps/window.bmp")
window_palette.make_transparent(2)

increment_loading_bar()

# load tetromino tiles
tiles, tiles_palette = adafruit_imageload.load("bitmaps/tetromino.bmp")
tiles_palette.make_transparent(28)

increment_loading_bar()

# create separate palette to only show tile borders
tiles_border_palette = copy_palette(tiles_palette)
tiles_border_indexes = (1, 11, 16, 9, 6, 2, 0, 26)
for i in range(len(tiles_border_palette)):
    if i not in tiles_border_indexes:
        tiles_border_palette.make_transparent(i)

increment_loading_bar()

# load face tiles
face_bmp, face_palette = adafruit_imageload.load("bitmaps/face.bmp")
face_palette.make_transparent(2)

increment_loading_bar()

# load drink bitmap
drink_bmp = OnDiskBitmap("bitmaps/drink{:s}.bmp".format("-sm" if display.width / display.height > 1.5 else ""))
drink_map = (12, 3, 5, 4, 1, 10, 14, 9, 7, 6, 8)  # convert level index to palette index
drink_map = tuple([(x, drink_bmp.pixel_shader[x]) for x in drink_map])  # copy colors
for i, color in drink_map:
    drink_bmp.pixel_shader[i] = 0x000000

increment_loading_bar()

# starting neopixels
if NEOPIXELS:
    for i in range(neopixels.n):
        neopixels[i] = drink_map[neopixels.n - 1 - i][1]
    neopixels.show()

increment_loading_bar()

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
        self.score = 0
    
    def save(self) -> None:
        if self.score >= self.high_score:
            self._update_save()
    
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

increment_loading_bar()

def get_random_tetromino_index() -> int:
    return randint(0, len(TETROMINOS) - 1)

class Tetromino(TileGroup):

    def __init__(self, index:int=None, offset:bool=True, tile_index:int=None, border_only:bool=False):
        super().__init__()
        self._tile_index = tile_index

        # setup tilegrid
        self._tilegrid = TileGrid(
            tiles, pixel_shader=tiles_border_palette if border_only else tiles_palette,
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
        if self._tile_index is not None:  # allow override
            self._tile = self._tile_index
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

    def rotate_right(self, force:bool = False) -> bool:
        if self._rotate_right(force):
            self._rotation = (self._rotation + 1) % 4
            return True
        return False

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

    def rotate_left(self, force:bool = False) -> bool:
        if self._rotate_left(force):
            self._rotation = (self._rotation - 1) % 4
            return True
        return False
     
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

increment_loading_bar()

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

increment_loading_bar()

# setup grid container
grid_window = Window(
    width=GRID_WIDTH + 2, height=GRID_HEIGHT + 2,
    x=(SCREEN_WIDTH - GRID_WIDTH - 2) // 2 + (SCREEN_WIDTH % 2),  # account of odd screen width
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

increment_loading_bar()

# display title image
title_bmp = OnDiskBitmap("bitmaps/title.bmp")
title_bmp.pixel_shader.make_transparent(8)
title_tg = TileGrid(
    title_bmp, pixel_shader=title_bmp.pixel_shader,
    y=grid_window.y,
    x=grid_window.x // 2 - title_bmp.width // 2,
)
main_group.append(title_tg)

increment_loading_bar()

# waiting text
waiting_text = Label(terminalio.FONT, text="Press any key\n to start...", color=0xffffff)
waiting_text.anchor_point = (.5, .5)
waiting_text.anchored_position = (
    (grid_window.x + grid_window.width // 2) * SCALE,
    (grid_window.y + grid_window.height // 2) * SCALE
)
text_group.append(waiting_text)

increment_loading_bar()

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

increment_loading_bar()

# high score container
score_window = ScoreWindow(
    high_score=10000,
    x=tetromino_window.tile_x,
    y=grid_window.tile_y + tetromino_window.tile_height + WINDOW_GAP,
)
main_group.append(score_window)

increment_loading_bar()

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

increment_loading_bar()

# level drink
level_window_y = tetromino_window.tile_y + (title_bmp.height // TILE_SIZE) + WINDOW_GAP
level_window = NumberWindow(
    label="Level", value=1,
    x=WINDOW_GAP, y=level_window_y,
    height=grid_window.tile_height + grid_window.tile_y - level_window_y,
    width=WINDOW_WIDTH + (SCREEN_WIDTH % 2),  # account for odd screen width
)
main_group.append(level_window)

drink_tg = TileGrid(
    drink_bmp, pixel_shader=drink_bmp.pixel_shader,
    x=(level_window.width - drink_bmp.width) // 2,
    y=max(
        level_window.height - TILE_SIZE - drink_bmp.height - (level_window.width - TILE_SIZE * 2 - drink_bmp.width) // 2,  # equal padding (4:3)
        (level_window.height - drink_bmp.height) // 2  # center of window (1.8:1)
    ),
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

increment_loading_bar()

# setup pause screen
pause_group = Group()
pause_group.hidden = True
root_group.append(pause_group)

pause_tg = TileGrid(
    pause_tiles, pixel_shader=pause_palette,
    width=display.width//PAUSE_TILE_SIZE, height=display.height//PAUSE_TILE_SIZE,
    tile_width=PAUSE_TILE_SIZE, tile_height=PAUSE_TILE_SIZE,
    default_tile=0,
)
pause_group.append(pause_tg)

# clear out area for text
for y in range(pause_tg.height//2-2, pause_tg.height//2+2):
    for x in range(pause_tg.width//2-4, pause_tg.width//2+4):
        pause_tg[x, y] = 1

pause_label = Label(terminalio.FONT, text="PAUSED", color=0xffffff)
pause_label.anchor_point = (.5, .5)
pause_label.anchored_position = (display.width//2, display.height//2)
pause_group.append(pause_label)

increment_loading_bar()

tetromino, tetromino_indicator = None, None
def update_tetromino_indicator_y() -> None:
    tetromino_indicator.tile_y = 0
    for i in range(tetromino.tile_y + 1, GRID_HEIGHT):
        if tetromino_indicator.check_collide(y=i):
            tetromino_indicator.tile_y = i - 1
            tetromino_indicator.hidden = False
            return
    tetromino_indicator.hidden = True

def get_next_tetromino() -> None:
    global tetromino, tetromino_indicator, next_tetromino
    if tetromino is not None:
        grid_container.remove(tetromino)
        del tetromino
    if tetromino_indicator is not None:
        grid_container.remove(tetromino_indicator)
        del tetromino_indicator

    tetromino = Tetromino(next_tetromino.tetromino_index)
    tetromino.tile_x = (GRID_WIDTH - TETROMINO_SIZE) // 2  # center along x axis of grid
    grid_container.append(tetromino)

    tetromino_indicator = Tetromino(tetromino.tetromino_index, offset=False, border_only=True)
    tetromino_indicator.tile_x = tetromino.tile_x
    update_tetromino_indicator_y()
    
    grid_container.append(tetromino_indicator)

    next_tetromino.tetromino_index = get_random_tetromino_index()

STATE_WAITING   = const(1)
STATE_PLAYING   = const(2)
STATE_PAUSED    = const(3)
STATE_GAME_OVER = const(4)

game_state = STATE_WAITING
def reset_game() -> None:
    global current_lines, level_window, tilegrid, score_window, game_state

    # clear grid
    for y in range(GRID_HEIGHT):
        for x in range(GRID_WIDTH):
            tilegrid[x, y] = 0

    # generate new tetromino
    get_next_tetromino()
    next_tetromino.hidden = False

    # update face
    face_tg[0, 0] = 0

    # hide waiting text
    waiting_text.hidden = True

    # reset game variables
    score_window.reset()
    level_window.value = 1
    current_lines = 0
    set_drink_level(0)
    game_state = STATE_PLAYING
    play_song()

    display.refresh()

async def game_over() -> None:
    global game_state, display, tetromino, tetromino_indicator, next_tetromino
    game_state = STATE_GAME_OVER
    stop_song()

    # hide tetrominos
    tetromino.hidden = True
    tetromino_indicator.hidden = True
    next_tetromino.hidden = True

    # update face
    face_tg[0, 0] = (face_bmp.width // face_tg.tile_width) - 1

    # save high score
    score_window.save()

    # play melody
    play_sfx(SFX_GAME_OVER)

    # wipe out grid
    for y in range(GRID_HEIGHT - 1, -1, -1):
        for x in range(GRID_WIDTH):
            tilegrid[x, y] = (tiles.width // tilegrid.tile_width) - 1  # gray tile
        display.refresh()
        await asyncio.sleep(2 / GRID_HEIGHT)

    game_state = STATE_WAITING
    waiting_text.hidden = False

    # clear out area for text
    for y in range(GRID_HEIGHT // 2 - 2 + (SCREEN_HEIGHT % 2), GRID_HEIGHT // 2 + 2):
        for x in range(SCALE - 1, GRID_WIDTH - (SCALE - 1)):
            tilegrid[x, y] = 0
    display.refresh()

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
            set_song_tempo(int(get_song_tempo() * 1.05))  # increase song tempo by 5% each level
        set_drink_level(current_lines / total_lines)
        play_sfx(SFX_TETRIS if lines == 4 or not current_lines else SFX_CLEAR)

last_drop_time = None
async def tetromino_handler() -> None:
    global tetromino, current_lines, tilegrid, score_window, last_drop_time, game_state
    while True:

        if game_state == STATE_PLAYING:

            # Synchronize with last manual drop
            while last_drop_time is not None:
                sync_drop_time = max(get_drop_speed() - (time.monotonic() - last_drop_time), 0)
                last_drop_time = None
                await asyncio.sleep(sync_drop_time)
                
            if tetromino.check_collide(y=1):  # place if collided
                tetromino.place()
                tetromino_indicator.hidden = True
                play_sfx(SFX_PLACE)

                # check for line clearing
                lines = 0
                for y in range(max(tetromino.tile_y, 0), min(tetromino.tile_y + TETROMINO_SIZE, GRID_HEIGHT)):
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
                if tetromino.tile_y <= 0 and not lines:
                    await game_over()
                else:  # update face
                    face_tg[0, 0] = ((GRID_HEIGHT - tetromino.tile_y) * 3) // GRID_HEIGHT

                if game_state == STATE_PLAYING:
                    # generate new tetromino
                    get_next_tetromino()

            else:  # move tetromino down
                tetromino.tile_y += 1
                play_sfx(SFX_DROP)

            display.refresh()
            
            await asyncio.sleep(get_drop_speed())
        else:
            await asyncio.sleep(1/30)

ACTION_ROTATE    = const(0)
ACTION_LEFT      = const(1)
ACTION_RIGHT     = const(2)
ACTION_SOFT_DROP = const(3)
ACTION_HARD_DROP = const(4)
ACTION_PAUSE     = const(5)
ACTION_QUIT      = const(6)

gamepad_map = (
    (gamepad.A,      ACTION_ROTATE),
    (gamepad.B,      ACTION_HARD_DROP),
    (gamepad.DOWN,   ACTION_SOFT_DROP),
    (gamepad.START,  ACTION_PAUSE),
    (gamepad.SELECT, ACTION_QUIT),
    (gamepad.LEFT,   ACTION_LEFT),
    (gamepad.RIGHT,  ACTION_RIGHT),
    (gamepad.UP,     ACTION_ROTATE),
)
gamepad_device = None

def do_action(action:int) -> None:
    global tetromino, last_drop_time, game_state, gamepad_device
    if action is not None:
        if game_state == STATE_PLAYING:
            if action == ACTION_ROTATE:
                if tetromino.rotate_right():
                    tetromino_indicator.rotate_right(True)
                    tetromino_indicator.tile_x = tetromino.tile_x
                    update_tetromino_indicator_y()
                    play_sfx(SFX_ROTATE)
                else:
                    play_sfx(SFX_ERROR)
            elif action == ACTION_LEFT:
                if tetromino.left():
                    tetromino_indicator.tile_x = tetromino.tile_x
                    update_tetromino_indicator_y()
                    play_sfx(SFX_MOVE)
                else:
                    play_sfx(SFX_ERROR)
            elif action == ACTION_RIGHT:
                if tetromino.right():
                    tetromino_indicator.tile_x = tetromino.tile_x
                    update_tetromino_indicator_y()
                    play_sfx(SFX_MOVE)
                else:
                    play_sfx(SFX_ERROR)
            elif action == ACTION_SOFT_DROP:
                if tetromino.down():
                    play_sfx(SFX_DROP)
                    last_drop_time = time.monotonic()
            elif action == ACTION_HARD_DROP:
                spaces = 0
                while tetromino.down():
                    spaces += 1
                score_window.score += spaces
                if spaces:
                    play_sfx(SFX_HARD_DROP)
                    last_drop_time = time.monotonic()
            elif action == ACTION_PAUSE:
                game_state = STATE_PAUSED
                pause_group.hidden = False
                stop_song()
        elif game_state == STATE_PAUSED and action == ACTION_PAUSE:
            game_state = STATE_PLAYING
            pause_group.hidden = True
            play_song(False)
        elif game_state == STATE_WAITING and action != ACTION_QUIT:
            reset_game()
        elif action == ACTION_QUIT:
            if gamepad_device is not None and not gamepad_device.device.is_kernel_driver_active(gamepad_device.interface):
                gamepad_device.device.attach_kernel_driver(gamepad_device.interface)
            supervisor.reload()
        
        display.refresh()

async def gamepad_handler() -> None:
    global gamepad_device, gamepad_map
    while True:
        try:
            scan_result = gamepad.find_usb_device()
            if scan_result is None:
                await asyncio.sleep(.4)
                continue
            gamepad_device = gamepad.InputDevice(scan_result)

            prev = 0
            for data in gamepad_device.input_event_generator():
                if data is not None and isinstance(data, int):
                    diff = prev ^ data
                    prev = data
                    for button, action in gamepad_map:
                        if diff & button and data & button:
                            do_action(action)
                await asyncio.sleep(1/30)

        except (USBError, ValueError) as e:
            await asyncio.sleep(.4)

if buttons is not None:
    
    BUTTON_MAP = (
        None,
        ACTION_LEFT,       # button #1
        ACTION_ROTATE,     # button #2
        ACTION_PAUSE,      # button #1 & #2
        ACTION_RIGHT,      # button #3
        ACTION_HARD_DROP,  # button #1 & #3
        ACTION_SOFT_DROP,  # button #2 & #3
        ACTION_QUIT,       # button #1 & #2 & #3
    )

    async def button_handler() -> None:
        global tetromino, buttons

        button_pressed = 0

        while True:

            # check hardware buttons
            if (event := buttons.events.get()):
                if event.pressed:
                    button_pressed += 1 << event.key_number
                elif event.released and button_pressed:
                    do_action(BUTTON_MAP[button_pressed])  # None will be ignored
                    button_pressed = 0  # reset

            await asyncio.sleep(1/30)

async def main():
    tasks = [
        asyncio.create_task(tetromino_handler()),
        asyncio.create_task(gamepad_handler()),
    ]
    if buttons is not None:
        tasks.append(asyncio.create_task(button_handler()))
    await asyncio.gather(*tasks)

# remove loading screen
loading_group.remove(loading_text)
loading_group.remove(loading_bar)
root_group.remove(loading_group)
del loading_text, loading_bar, loading_group

# display game components
main_group.hidden = False
text_group.hidden = False

# initial display refresh
display.refresh()

asyncio.run(main())
