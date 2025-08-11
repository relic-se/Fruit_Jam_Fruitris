# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright 2025 Sam Blenny
#
# Gamepad driver for various USB wired gamepads.
#
# NOTE: This code uses performance boosting tricks to avoid bogging down the
# CPU or making a lot of heap allocations. To learn more about caching function
# references, caching instance variables, and making iterators with generator
# functions, check out the links below.
#
# Related docs:
# - https://docs.circuitpython.org/projects/logging/en/latest/api.html
# - https://docs.python.org/3/glossary.html#term-generator
# - https://docs.python.org/3/glossary.html#term-iterable
# - https://docs.micropython.org/en/latest/reference/speed_python.html
#
import binascii
from micropython import const
from supervisor import ticks_ms
from usb import core
from usb.core import USBError, USBTimeoutError
from usb.util import SPEED_HIGH

import usb_descriptor


# Gamepad button bitmask constants
UP     = const(0x0001)  # dpad: Up
DOWN   = const(0x0002)  # dpad: Down
LEFT   = const(0x0004)  # dpad: Left
RIGHT  = const(0x0008)  # dpad: Right
START  = const(0x0010)
SELECT = const(0x0020)
L      = const(0x0100)  # Left shoulder button
R      = const(0x0200)  # Right shoulder button
B      = const(0x1000)  # button cluster: bottom button (Nintendo B, Xbox A)
A      = const(0x2000)  # button cluster: right button  (Nintendo A, Xbox B)
Y      = const(0x4000)  # button cluster: left button   (Nintendo Y, Xbox X)
X      = const(0x8000)  # button cluster: top button    (Nintendo X, Xbox Y)

# USB detected device types
TYPE_SWITCH_PRO    = const(1)  # 057e:2009 clones of Switch Pro Controller
TYPE_ADAFRUIT_SNES = const(2)  # 081f:e401 generic SNES layout HID, low-speed
TYPE_8BITDO_ZERO2  = const(3)  # 2dc8:9018 mini SNES layout, HID over USB-C
TYPE_XINPUT        = const(4)  # (vid:pid vary) Clones of Xbox360 controller
TYPE_BOOT_KEYBOARD = const(5)
TYPE_POWERA_WIRED  = const(6)  # 20d6:a711 PowerA Wired Controller (for Switch)


device_cache = {}
def find_usb_device():
    global device_cache
    # Find a USB wired gamepad by inspecting usb device descriptors
    # - device_cache: dictionary of previously checked device descriptors
    # - return: ScanResult object for success or None for failure.
    # Exceptions: may raise usb.core.USBError or usb.core.USBTimeoutError
    #
    for device in core.find(find_all=True):
        # Read descriptors to identify devices by type
        try:
            desc = usb_descriptor.Descriptor(device)
            k = str(desc.to_bytes())
            if k in device_cache:
                return None
            # Remember this device to avoid repeatedly checking it later
            device_cache[k] = True
            # Compare descriptor to known device type fingerprints
            desc.read_configuration(device)
            vid, pid = desc.vid_pid()
            # Get tuples of class/subclass/protocol for device and interface 0
            dev_info = desc.dev_class_subclass_protocol()
            int0_info = desc.int0_class_subclass_protocol()
            dev_int0_info = dev_info + int0_info
            dev = device
            if (vid, pid) == (0x057e, 0x2009):
                return ScanResult(dev, TYPE_SWITCH_PRO, 'SwitchPro', desc)
            elif (vid, pid) == (0x081f, 0xe401):
                # Generic SNES layout HID gamepad sold by Adafruit
                return ScanResult(dev, TYPE_ADAFRUIT_SNES, 'AdafruitSNES', desc)
            elif (vid, pid) == (0x2dc8, 0x9018):
                # This one is HID but quirky, so it needs special handling
                return ScanResult(dev, TYPE_8BITDO_ZERO2, '8BitDoZero2', desc)
            elif (vid, pid) == (0x20d6, 0xa711):
                # This is for Switch, but it's HID, with 8-bits per axis analog
                return ScanResult(dev, TYPE_POWERA_WIRED, 'PowerAWired', desc)
            elif dev_int0_info == (0xff, 0xff, 0xff, 0xff, 0x5d, 0x01):
                return ScanResult(dev, TYPE_XINPUT, 'XInput', desc)
            elif dev_int0_info == (0x00, 0x00, 0x00, 0x03, 0x01, 0x01):
                return ScanResult(dev, TYPE_BOOT_KEYBOARD, 'BootKeyboard', desc)
            else:
                return None
        except (ValueError, USBError) as e:
            pass
    return None


class ScanResult:
    def __init__(self, device, dev_type, tag, descriptor):
        self.device = device
        self.dev_type = dev_type
        self.tag = tag
        self.descriptor = descriptor
        self.vid = descriptor.idVendor
        self.pid = descriptor.idProduct
        self.dev_info = descriptor.dev_class_subclass_protocol()
        self.int0_info = descriptor.int0_class_subclass_protocol()


def elapsed_ms_generator():
    # Generator function for measuring time intervals efficiently.
    # - returns: an iterator
    # - iterator yields: ms since last call to next(iterator)
    #
    ms = ticks_ms      # caching function ref avoids dictionary lookups
    mask = 0x3fffffff  # (2**29)-1 because ticks_ms rolls over at 2**29
    t0 = ms()
    while True:
        t1 = ms()
        delta = (t1 - t0) & mask  # handle possible timer rollover gracefully
        t0 = t1
        yield delta


class InputDevice:
    def __init__(self, scan_result):
        # Initialize buffers used in polling USB gamepad events
        # - scan_result: a ScanResult instance
        # Exceptions: may raise usb.core.USBError
        #
        device = scan_result.device
        dev_type = scan_result.dev_type
        self._prev = 0
        self.buf64 = bytearray(64)
        self.device = device
        self.dev_type = dev_type
        # Make sure CircuitPython core is not claiming the device
        interface = 0
        if device.is_kernel_driver_active(interface):
            device.detach_kernel_driver(interface)
        # Set configuration
        device.set_configuration()
        # Figure out which endpoints to use
        int0_ins = scan_result.descriptor.int0_input_endpoints()
        int0_outs = scan_result.descriptor.int0_output_endpoints()
        endpoint_in  = None if (len(int0_ins) < 1) else int0_ins[0]
        endpoint_out = None if (len(int0_outs) < 1) else int0_outs[0]
        self.int0_endpoint_in = endpoint_in
        self.int0_endpoint_out = endpoint_out
        # Initialize USB device if needed (e.g. handshake or set gamepad LEDs)
        if dev_type == TYPE_SWITCH_PRO:
            self.init_switch_pro_gamepad()
        elif dev_type == TYPE_ADAFRUIT_SNES:
            print('Initializing Adafruit SNES-like gamepad')
        elif dev_type == TYPE_8BITDO_ZERO2:
            print('Initializing 8BitDo Zero 2 gamepad')
        elif dev_type == TYPE_POWERA_WIRED:
            print('Initializing PowerA Wired Controller')
        elif dev_type == TYPE_XINPUT:
            self.init_xinput()
        elif dev_type == TYPE_BOOT_KEYBOARD:
            print('Initializing Boot-Compatible Keyboard')
        else:
            raise ValueError('Unknown dev_type: %d' % dev_type)

    def init_switch_pro_gamepad(self):
        # Prepare Switch Pro compatible gamepad for use.
        # Exceptions: may raise usb.core.USBError and usb.core.USBTimeoutError
        #
        print('Initializing SwitchPro gamepad')
        out_addr = self.int0_endpoint_out.bEndpointAddress
        in_addr = self.int0_endpoint_in.bEndpointAddress
        out_interval = self.int0_endpoint_out.bInterval
        in_interval = self.int0_endpoint_in.bInterval
        max_packet = min(64, self.int0_endpoint_in.wMaxPacketSize)
        data = bytearray(max_packet)
        data_mv = memoryview(data)
        handshake_messages = (
            bytes(b'\x80\x01'),  # get device type and mac address
            bytes(b'\x80\x02'),  # handshake
            bytes(b'\x80\x03'),  # set faster baud rate
            bytes(b'\x80\x02'),  # handshake
            bytes(b'\x80\x04'),  # use USB HID only and disable timeout
            # set input report mode to standard
            bytes(b'\x01\x06\x00\x00\x00\x00\x00\x00\x00\x00\x03\x30'),
            # set player LED1 to on (for LED1+LED2 do 30 03, etc.)
            bytes(b'\x01\x0a\x00\x00\x00\x00\x00\x00\x00\x00\x30\x01'),
            # set home LED
            bytes(b'\x01\x0b\x00\x00\x00\x00\x00\x00\x00\x00\x38\x01\x00\x00\x11\x11'),
        )
        hexdump = binascii.hexlify  # cache hexdumper function
        for msg in handshake_messages:
            try:
                self.device.write(out_addr, msg, timeout=out_interval)
            except USBTimeoutError as e:
                raise ValueError("SwitchPro HANDSHAKE GLITCH (wr)")
            # Wait for ACK
            okay = False
            for _ in range(8):
                try:
                    self.device.read(in_addr, data, timeout=in_interval)
                    okay = True
                    break
                except USBTimeoutError:
                    pass
            if not okay:
                # This happens with my 8BitDo Ultimate Bluetooth Controller's
                # 2.4 GHz USB adapter. It glitches several times like this
                # before re-appearing in XInput mode with vid:pid 045e:028e.
                raise ValueError("SwitchPro HANDSHAKE GLITCH (rd)")

    def init_xinput(self):
        # Prepare XInput gamepad for use.
        # Exceptions: may raise USBError
        print('Initializing XInput gamepad')
        out_addr = self.int0_endpoint_out.bEndpointAddress
        in_addr = self.int0_endpoint_in.bEndpointAddress
        out_inteval = self.int0_endpoint_out.bInterval
        in_interval = self.int0_endpoint_in.bInterval
        max_packet = min(64, self.int0_endpoint_in.wMaxPacketSize)
        data = bytearray(max_packet)
        # Set player number LEDs on XInput gamepad (hardcode to player 1)
        msg = bytes(b'\x01\x03\x02')  # 1 LED
        #msg = bytes(b'\x01\x03\x03')  # 2 LEDs
        #msg = bytes(b'\x01\x03\x04')  # 3 LEDs
        #msg = bytes(b'\x01\x03\x05')  # 4 LEDs
        self.device.write(out_addr, msg, timeout=8)
        # Some XInput gamepads send a bunch of stuff initially before normal
        # reports begin, so drain the input pipe
        for _ in range(8):
            try:
                self.device.read(in_addr, data, timeout=in_interval)
            except USBTimeoutError as e:
                # Ignore timeouts
                pass

    def input_event_generator(self):
        # This is a generator that makes an iterable for reading input events.
        # - returns: iterable that can be used with a for loop
        # - yields: (3 possibilities)
        #   1. Normalized 16-bit integer with XInput style button bitfield
        #   2. A memoryview(bytearray(...)) with raw or filtered data from
        #      polling the default endpoint.
        #   3. None in the case of a timeout or rate limit throttle
        # Exceptions: may raise USBError
        #
        dev_type = self.dev_type  # cache this as we use it several times
        int0_gen = self.int0_read_generator  # cache to make shorter lines
        if self.device is None:
            return None
        elif dev_type == TYPE_SWITCH_PRO:
            # Report format (cluster layout: A on right)
            # byte 0: report ID
            # byte 1: sequence number
            # byte 2: 0x01=Y, 0x02=X, 0x04=B, 0x08=A, 0x40=R, 0x80=R2
            # byte 3: 0x01=Select, 0x02=Start, 0x04=R_stick_btn,
            #         0x08=L_stick_btn, 0x10=Home=0x10, 0x20=Share
            # byte 4: DpadDn=0x01, DpadUp=0x02, DpadR=0x04, DpadL=0x08,
            #         0x40=L, 0x80=L2
            #
            # Generator function converts byte array to an XInput format uint16
            # - data: an iterator that yields memoryview(bytearray(...))
            def normalize_switchpro(data):
                for d in data:
                    if d is None:
                        yield None
                        continue
                    v = 0
                    d2 = d[0]  # byte 2 of the unfiltered report
                    d3 = d[1]  # byte 3 of the unfiltered report
                    d4 = d[2]  # byte 4 of the unfiltered report
                    v |= Y      if d2 & 0x01 else 0
                    v |= X      if d2 & 0x02 else 0
                    v |= B      if d2 & 0x04 else 0
                    v |= A      if d2 & 0x08 else 0
                    v |= R      if d2 & 0x40 else 0
                    v |= SELECT if d3 & 0x01 else 0
                    v |= START  if d3 & 0x02 else 0
                    v |= DOWN   if d4 & 0x01 else 0
                    v |= UP     if d4 & 0x02 else 0
                    v |= RIGHT  if d4 & 0x04 else 0
                    v |= LEFT   if d4 & 0x08 else 0
                    v |= L      if d4 & 0x40 else 0
                    yield v
            # This filter lambda returns None when report ID is not 0x30. For
            # report ID 0x30, filter trims off report ID, sequence number, and
            # IMU data, leaving bytes for buttons, dpad, and sticks.
            filter_fn = lambda d: None if (d[0] != 0x30) else d[3:6]
            return normalize_switchpro(int0_gen(filter_fn=filter_fn))
        elif dev_type == TYPE_ADAFRUIT_SNES:
            # Report format (SNES cluster layout, A on right)
            # byte 0: (analog dpad) 0x00=dPadL, 0x7f=dPadCenter, 0xff=dPadR
            # byte 1: (analog dpad) 0x00=dPadUp, 0x7f=dPadCenter, 0xff=dPadDn
            # ...
            # byte 5: (bitfield) 0x10=X, 0x20=A, 0x40=B, 0x80=Y
            # byte 6: (bitfield) 0x01=L, 0x02=R, 0x10=Select, 0x20=Start
            #
            def normalize_adasnes(data):
                for d in data:
                    if d is None:
                        yield None
                        continue
                    v = 0
                    d0 = d[0]  # byte 0 of the unfiltered report
                    d1 = d[1]  # byte 1 of the unfiltered report
                    d5 = d[5]  # byte 5 of the unfiltered report
                    d6 = d[6]  # byte 6 of the unfiltered report
                    # Dpad uses 2 analog axes
                    v |= LEFT   if d0 == 0x00 else 0
                    v |= RIGHT  if d0 == 0xff else 0
                    v |= UP     if d1 == 0x00 else 0
                    v |= DOWN   if d1 == 0xff else 0
                    # Buttons are bitfield
                    v |= X      if d5 & 0x10 else 0
                    v |= A      if d5 & 0x20 else 0
                    v |= B      if d5 & 0x40 else 0
                    v |= Y      if d5 & 0x80 else 0
                    v |= L      if d6 & 0x01 else 0
                    v |= R      if d6 & 0x02 else 0
                    v |= SELECT if d6 & 0x10 else 0
                    v |= START  if d6 & 0x20 else 0
                    yield v
            return normalize_adasnes(int0_gen(filter_fn=lambda d: d[:7]))
        elif dev_type == TYPE_8BITDO_ZERO2:
            # This device is quirky because it alternates between 8 byte and
            # 24 byte HID reports. The 24 byte reports seem to be three of the
            # 8 byte reports stuck together.
            #
            # Report format (dpad is 4-bit BCD style):
            # byte 0: 0x01=A, 0x02=B, 0x08=X, 0x10=Y, 0x40=L, 0x80=R
            # byte 1: 0x04=Select, 0x08=Start
            # byte 2: 0x00=dPadN, 0x01=dPadNE, 0x02=dPadE, 0x03=dPadSE,
            #         0x04=dPadS, 0x05=dPadSW, 0x06=dPadW, 0x07=dPadNW,
            #         0x0f=dPadCenter
            #
            def normalize_zero2(data):
                for d in data:
                    if d is None:
                        yield None
                        continue
                    v = 0
                    d0 = d[0]  # byte 0 of the unfiltered report
                    d1 = d[1]  # byte 1 of the unfiltered report
                    d2 = d[2]  # byte 2 of the unfiltered report
                    # Buttons are bitfield
                    v |= A            if d0 & 0x01 else 0
                    v |= B            if d0 & 0x02 else 0
                    v |= X            if d0 & 0x08 else 0
                    v |= Y            if d0 & 0x10 else 0
                    v |= L            if d0 & 0x40 else 0
                    v |= R            if d0 & 0x80 else 0
                    v |= SELECT       if d1 & 0x04 else 0
                    v |= START        if d1 & 0x08 else 0
                    # Dpad is 4-bit BCD
                    v |= UP           if d2 == 0x00 else 0
                    v |= UP | RIGHT   if d2 == 0x01 else 0
                    v |= RIGHT        if d2 == 0x02 else 0
                    v |= DOWN | RIGHT if d2 == 0x03 else 0
                    v |= DOWN         if d2 == 0x04 else 0
                    v |= DOWN | LEFT  if d2 == 0x05 else 0
                    v |= LEFT         if d2 == 0x06 else 0
                    v |= UP | LEFT    if d2 == 0x07 else 0
                    yield v
            return normalize_zero2(int0_gen(filter_fn=lambda d: d[:3]))
        elif dev_type == TYPE_POWERA_WIRED:
            # This device is a straightforward well-behaved HID gamepad with
            # 4-bit BCD dpad and 8-bits per axis analog (which I'm ignoring).
            #
            # Report format (dpad is 4-bit BCD style, buttons are bitfield):
            # byte 0: 0x01=Y, 0x02=B, 0x04=A, 0x08=X, 0x10=L, 0x20=R,
            #         0x40=L1, 0x80=R2
            # byte 1: 0x01=Select, 0x02=Start, 0x10=Home, 0x20=Screenshot
            # byte 2: 0x00=dPadN, 0x01=dPadNE, 0x02=dPadE, 0x03=dPadSE,
            #         0x04=dPadS, 0x05=dPadSW, 0x06=dPadW, 0x07=dPadNW,
            #         0x0f=dPadCenter
            #
            def normalize_powera_wired(data):
                for d in data:
                    if d is None:
                        yield None
                        continue
                    v = 0
                    d0 = d[0]  # byte 0 of the unfiltered report
                    d1 = d[1]  # byte 1 of the unfiltered report
                    d2 = d[2]  # byte 2 of the unfiltered report
                    # Buttons are bitfield
                    v |= Y            if d0 & 0x01 else 0
                    v |= B            if d0 & 0x02 else 0
                    v |= A            if d0 & 0x04 else 0
                    v |= X            if d0 & 0x08 else 0
                    v |= L            if d0 & 0x10 else 0
                    v |= R            if d0 & 0x20 else 0
                    v |= SELECT       if d1 & 0x01 else 0
                    v |= START        if d1 & 0x02 else 0
                    # Dpad is 4-bit BCD
                    v |= UP           if d2 == 0x00 else 0
                    v |= UP | RIGHT   if d2 == 0x01 else 0
                    v |= RIGHT        if d2 == 0x02 else 0
                    v |= DOWN | RIGHT if d2 == 0x03 else 0
                    v |= DOWN         if d2 == 0x04 else 0
                    v |= DOWN | LEFT  if d2 == 0x05 else 0
                    v |= LEFT         if d2 == 0x06 else 0
                    v |= UP | LEFT    if d2 == 0x07 else 0
                    yield v
            return normalize_powera_wired(int0_gen(filter_fn=lambda d: d[:3]))
        elif dev_type == TYPE_XINPUT:
            # Report format (clone w/ SNES cluster layout, A on right):
            # (NOTE: This is the canonical format that others get normalized to)
            #  ...
            #  byte 2: 0x01=dPadUp, 0x02=dPadDn, 0x04=dPadL, 0x08=dPadR,
            #          0x10=Start, 0x20=Select
            #  byte 3: 0x01=L, 0x02=R, 0x10=B, 0x20=A, 0x05=Home, 0x40=Y, 0x80=X
            #
            def normalize_xinput(data):
                for d in data:
                    yield None if d is None else ((d[1] << 8) | d[0])
            # Filter lambda trims off all the analog stuff
            return normalize_xinput(int0_gen(filter_fn=lambda d: d[2:4]))
        elif dev_type == TYPE_BOOT_KEYBOARD:
            return int0_gen()

    def int0_read_generator(self, filter_fn=lambda d: d):
        # Generator function: read from interface 0 and yield raw report data
        # - filter_fn: Optional lambda function to modify raw reports. This is
        #   for slicing off sequence numbers, analog values, or junk bytes.
        # - yields: memoryview of bytes
        # Exceptions: may raise USBError
        #
        # Meaning of bInterval depends on negotiated speed:
        # - USB 2.0 spec: 5.6.4 Isochronous Transfer Bus Access Constraints
        # - USB 2.0 spec: 9.6.6 Endpoint (table 9-13)
        # - Low-speed: max time between polling requests = bInterval * 1 ms
        # - Full-speed: max time = bInterval * 1 ms
        # - High-speed: max time = math.pow(2, bInterval-1) * 125 µs
        #
        # This implementation alternates between two data buffers so it's
        # possible to compare the previous report with the current report
        # without having to heap allocate a new buffer every time.
        #
        in_addr = self.int0_endpoint_in.bEndpointAddress
        interval = self.int0_endpoint_in.bInterval
        if self.device.speed == SPEED_HIGH:
            # Units here are 125 µs or (1 ms)/8. Since timer resolution we have
            # available is 1 ms, quantize the requested interval to 1 ms units
            # (left shift 3 to divide by 8).
            interval = (2 << (interval - 1)) >> 3
        max_packet = min(64, self.int0_endpoint_in.wMaxPacketSize)
        odd = True
        data_odd  = bytearray(max_packet)
        data_even = bytearray(max_packet)
        mv_odd    = memoryview(data_odd)  # memoryview reduces heap allocations
        mv_even   = memoryview(data_even)
        prev_report = mv_even
        dev_read = self.device.read  # cache function to avoid dictionary lookups

        # Make timer to throttle the polling rate because...
        # 1. Reading USB too much bogs down the system and fights with DVI
        # 2. Waiting too long to read USB will upset some devices
        poll_ms = 0
        poll_dt = elapsed_ms_generator()
        poll_target = (interval * 3) >> 2  # 75% of the max polling interval

        # Polling loop
        while True:
            poll_ms += next(poll_dt)
            if poll_ms < poll_target:
                yield None  # It's too soon to poll now
                continue
            else:
                poll_ms = 0

            # Enough time has passed, so poll endpoint and compare report data
            # to that of the previous report. If they differ, update the
            # previous value, swap the active buffer, and yield a memoryview
            # into the most recent trimmed report data. The even/odd buffer
            # swapping is necessary for the memoryview stuff to work properly.
            #
            # NOTE: This is using a lambda function provided by the caller to
            # filter the raw data read from the endpoint. The lambda function
            # can return None when the current read should be skipped (e.g. HID
            # report with boring report ID).
            #
            curr_data = data_odd if odd else data_even
            try:
                if odd:
                    n = dev_read(in_addr, data_odd, timeout=interval)
                    report = filter_fn(mv_odd[:n])
                    if (report is None) or (report == prev_report):
                        yield None
                    else:
                        prev_report = report
                        odd = False
                        yield report
                else:
                    n = dev_read(in_addr, data_even, timeout=interval)
                    report = filter_fn(mv_even[:n])
                    if (report is None) or (report == prev_report):
                        yield None
                    else:
                        prev_report = report
                        odd = True
                        yield report
            except USBTimeoutError as e:
                # This is normal. Timeouts happen fairly often.
                yield None
            except USBError as e:
                # This may happen when device is unplugged (not always though)
                raise e
