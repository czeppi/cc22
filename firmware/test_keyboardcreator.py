import unittest

from adafruit_hid.keycode import Keycode as KC
from kbdlayoutdata import VIRTUAL_KEY_ORDER, LAYERS, \
    MODIFIERS, MACROS
from keyboardcreator import KeyboardCreator
from keyboardhalf import VKeyPressEvent
from keysdata import LPU, NO_KEY
from reactions import KeyCmdKind, KeyCmd


class KeyboardCreatorTest(unittest.TestCase):

    def test_one_simple_key(self):
        creator = KeyboardCreator(virtual_key_order=[[LPU]],
                                  layers={NO_KEY: ['a']},
                                  modifiers={},
                                  macros={},
                                  )
        keyboard = creator.create()

        vkey_event = VKeyPressEvent(vkey_serial=LPU, pressed=True)
        act_reaction_commands = list(keyboard.update(time=210, vkey_events=[vkey_event]))
        expected_reaction_commands = [KeyCmd(kind=KeyCmdKind.KEY_PRESS, key_code=KC.A)]
        self.assertEqual(expected_reaction_commands, act_reaction_commands)

    def test_with_real_layout(self):
        creator = KeyboardCreator(virtual_key_order=VIRTUAL_KEY_ORDER,
                                  layers=LAYERS,
                                  modifiers=MODIFIERS,
                                  macros=MACROS,
                                  )
        keyboard = creator.create()

        vkey_event = VKeyPressEvent(vkey_serial=LPU, pressed=True)
        act_reaction_commands = list(keyboard.update(time=210, vkey_events=[vkey_event]))   # todo: not working with 10

        expected_reaction_commands = [KeyCmd(kind=KeyCmdKind.KEY_PRESS, key_code=KC.Q)]
        self.assertEqual(expected_reaction_commands, act_reaction_commands)
