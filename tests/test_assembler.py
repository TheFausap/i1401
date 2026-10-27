import unittest

from ibm1401 import AssemblyError, assemble
from ibm1401.bcd import WORD_MARK, decode_address

from tests.helpers import run_source


class AssemblerTests(unittest.TestCase):
    def test_labels_on_data_are_units_addresses(self):
        image = assemble(
            """
                ORG 100
START           H
NUMBER          DCW 00123
TEXT            DC @ABC@
                END START
"""
        )
        self.assertEqual(image.symbols["START"], 100)
        self.assertEqual(image.symbols["NUMBER"], 105)
        self.assertEqual(image.symbols["TEXT"], 108)
        self.assertTrue(image.cells[101] & WORD_MARK)
        self.assertEqual(image.entry, 100)

    def test_character_and_numeric_literal_pool(self):
        source = """
            ORG 100
START       MCW @ABC@,DEST
            ZA &123,NUMBER
            H
DEST        DCW 000
NUMBER      DCW 00000
            END START
"""
        machine, image, result = run_source(source)
        self.assertIsNone(result.fault)
        self.assertEqual(machine.memory.field_text(image.symbols["DEST"]), "ABC")
        self.assertEqual(machine.memory.numeric_value(image.symbols["NUMBER"]), 123)

    def test_dsa_emits_three_character_address(self):
        image = assemble(" ORG 100\nPTR DSA 15999\n END 100\n")
        units = image.symbols["PTR"]
        encoded = tuple(image.cells[units - 2 : units + 1])
        self.assertEqual(decode_address(encoded), 15999)

    def test_all_branch_forms_have_opcode_word_marks(self):
        source = """
            ORG 100
LAV         BAV START
LBIN        BIN START,@Z@
LBW         BW START,VALUE
LBM         BM START,VALUE
LBWZ        BWZ START,VALUE,@K@
LBBE        BBE START,VALUE,@1@
LBCE        BCE START,VALUE,@C@
LCCB        CCB START,@1@
START       H
VALUE       DCW -1
            END START
"""
        image = assemble(source)
        for label in ("LAV", "LBIN", "LBW", "LBM", "LBWZ", "LBBE", "LBCE", "LCCB", "START"):
            with self.subTest(label=label):
                self.assertTrue(image.cells[image.symbols[label]] & WORD_MARK)

    def test_undefined_symbol_has_line_number(self):
        with self.assertRaisesRegex(AssemblyError, r"line 2:.*undefined symbol"):
            assemble(" ORG 100\nSTART B MISSING\n END START\n")

    def test_invalid_constant_is_rejected(self):
        with self.assertRaises(AssemblyError):
            assemble("VALUE DCW NOT_A_NUMBER\n")


if __name__ == "__main__":
    unittest.main()
