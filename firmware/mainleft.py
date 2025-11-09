from __future__ import annotations

from keyboardcreator import KeyboardCreator
from reactions import KeyCmdKind, ReactionCommands, KeyCmd, MouseButtonCmd, MouseWheelCmd, ReactionCmd

try:
    from typing import Iterator
except ImportError:
    pass

import time
import board
import usb_hid
from digitalio import DigitalInOut, Direction, Pull
import rotaryio
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.mouse import Mouse

from base import PhysicalKeySerial, TimeInMs
from button import Button
from kbdlayoutdata import LEFT_KEY_GROUPS, VIRTUAL_KEY_ORDER, LAYERS, MODIFIERS, MACROS
from keyboardhalf import KeyboardHalf, KeyGroup, VKeyPressEvent
from keysdata import *
from uart import LeftUart, MouseMove


# TRRS
#
#   T R1 R2
#   S
#
#   T:  Tip,    VCC, red
#   R1: Ring1,  GND, black
#   R2: Ring2,  RX,  blue
#   S:  Sleeve, TX,  yellow


LEFT_TX = board.GP0
LEFT_RX = board.GP1


def main():
    left_kbd = LeftKeyboardSide()
    left_kbd.init()
    left_kbd.main_loop()


class RollerEncoder:

    def __init__(self, pin1, pin2):
        self._encoder = rotaryio.IncrementalEncoder(pin1, pin2)
        self._last_pos = None

    def update(self) -> int:
        pos = self._encoder.position
        if self._last_pos is None:
            self._last_pos = pos
            return 0

        if pos == self._last_pos:
            return 0

        offset = pos - self._last_pos
        self._last_pos = pos
        return offset


class LeftKeyboardSide:
    _BUTTON_MAP = {
        LEFT_INDEX_RIGHT: board.GP2,  # blue
        LEFT_INDEX_DOWN: board.GP3,  # yellow
        LEFT_INDEX_UP: board.GP4,  # red
        LEFT_MIDDLE_DOWN: board.GP10,  # blue
        LEFT_MIDDLE_UP: board.GP11,  # yellow
        LEFT_RING_DOWN: board.GP12,  # red
        LEFT_RING_UP: board.GP13,  # blue
        LEFT_PINKY_DOWN: board.GP14,  # red
        LEFT_PINKY_UP: board.GP15,  # yellow
        LEFT_THUMB_DOWN: board.GP21,  # red
        LEFT_THUMB_UP: board.GP20,  # yellowu
    }
    _ROTARY_PIN1 = board.GP16
    _ROTARY_PIN2 = board.GP17

    def __init__(self):
        self._uart = LeftUart(tx=LEFT_TX, rx=LEFT_RX)
        self._roller_encoder = RollerEncoder(self._ROTARY_PIN1, self._ROTARY_PIN2)
        self._buttons = [Button(pkey_serial=pkey_serial, gp_pin=gp_pin) for pkey_serial, gp_pin in self._BUTTON_MAP.items()]
        self._kbd_half = KeyboardHalf(key_groups=[KeyGroup(group_serial, group_data)
                                                  for group_serial, group_data in LEFT_KEY_GROUPS.items()])
        creator = KeyboardCreator(virtual_key_order=VIRTUAL_KEY_ORDER,
                                  layers=LAYERS,
                                  modifiers=MODIFIERS,
                                  macros=MACROS,
                                  )
        self._virt_keyboard = creator.create()

        self._kbd_device = Keyboard(usb_hid.devices)
        self._mouse_device = Mouse(usb_hid.devices)
        self._queue: list[QueueItem] = []

    def init(self) -> None:
        print('init uart...')
        self._uart.wait_for_start()

    def main_loop(self) -> None:
        print('start main loop')
        i = 0
        while True:
            try:
                if i % 500 == 0:
                    print(i)
                self._read_devices()

                for queue_item in self._read_queue_items():
                    self._process_queue_item(queue_item)

                time.sleep(0.001)
            except Exception as err:
                print(f'ERROR : {err}')
                time.sleep(0.5)
            i += 1

    def _read_devices(self) -> None:
        t = time.monotonic() * 1000

        #print(f'_read_devices: t={t}')
        my_pressed_pkeys = self._get_pressed_pkeys()

        encoder_offset = self._roller_encoder.update()
        if encoder_offset != 0:
            print(f'encoder_offset={encoder_offset}')

        mouse_dx = mouse_dy = 0
        other_vkey_events: list[VKeyPressEvent] = []
        for uart_item in self._uart.read_items():
            if isinstance(uart_item, MouseMove):
                mouse_move = uart_item
                mouse_dx += mouse_move.dx
                mouse_dy += mouse_move.dy
            elif isinstance(uart_item, VKeyPressEvent):
                vkey_evt = uart_item
                other_vkey_events.append(vkey_evt)

        queue_item = QueueItem(time=t, mouse_move=MouseMove(dx=mouse_dx, dy=mouse_dy),
                               encoder_offset=encoder_offset,
                               my_pressed_pkeys=my_pressed_pkeys,
                               other_vkey_events=other_vkey_events)
        #print(f'read_devices: {queue_item}')
        self._queue.append(queue_item)

    def _read_queue_items(self) -> Iterator[QueueItem]:
        while len(self._queue) > 0:
            queue_item = self._queue[0]
            self._queue = self._queue[1:]
            yield queue_item

    def _process_queue_item(self, queue_item: QueueItem) -> None:
        #print(f'_process_queue_item: {queue_item}')
        mouse_dx = queue_item.mouse_move.dx
        mouse_dy = queue_item.mouse_move.dy
        if mouse_dx != 0 or mouse_dy != 0:
            self._mouse_device.move(mouse_dx, mouse_dy)

        if queue_item.encoder_offset != 0:
            print(f'mouse wheel: {queue_item.encoder_offset}')
            self._mouse_device.move(wheel=queue_item.encoder_offset)

        my_vkey_events = list(self._kbd_half.update(time=queue_item.time,
                                                    cur_pressed_pkeys=queue_item.my_pressed_pkeys))
        t = time.monotonic() * 1000
        reaction_commands = list(self._virt_keyboard.update(time=t,
                                                            vkey_events=queue_item.other_vkey_events + my_vkey_events))
        for reaction_cmd in reaction_commands:
            self._send_reaction_cmd(reaction_cmd)

    def _get_pressed_pkeys(self) -> set[PhysicalKeySerial]:
        return {button.pkey_serial
                for button in self._buttons
                if button.is_pressed()}

    def _send_reaction_cmd(self, reaction_cmd: ReactionCmd) -> None:
        if isinstance(reaction_cmd, KeyCmd):
            key_cmd = reaction_cmd
            if key_cmd.kind == KeyCmdKind.KEY_PRESS:
                self._kbd_device.press(key_cmd.key_code)
            elif key_cmd.kind == KeyCmdKind.KEY_RELEASE:
                self._kbd_device.release(key_cmd.key_code)
        elif isinstance(reaction_cmd, MouseButtonCmd):
            self._mouse_device.click(reaction_cmd.button_no)  # Mouse.LEFT_BUTTON)
        elif isinstance(reaction_cmd, MouseWheelCmd):
            self._mouse_device.move(wheel=reaction_cmd.offset)


class QueueItem:

    def __init__(self, time: TimeInMs, mouse_move: MouseMove, encoder_offset: int,
                 my_pressed_pkeys: set[PhysicalKeySerial], other_vkey_events: list[VKeyPressEvent]):
        # public
        self.time = time
        self.mouse_move = mouse_move
        self.encoder_offset = encoder_offset
        self.my_pressed_pkeys = my_pressed_pkeys
        self.other_vkey_events = other_vkey_events

    def __str__(self) -> str:
        return f'QueueItem({self.time}, mouse=({self.mouse_move.dx, self.mouse_move.dy}), my-pkeys=({self.my_pressed_pkeys})), other-vkey={self.other_vkey_events})'


if __name__ == '__main__':
    main()
