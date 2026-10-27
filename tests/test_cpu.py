import unittest

from ibm1401 import IBM1401, assemble
from ibm1401.bcd import WORD_MARK

from tests.helpers import run_source


class ProcessorTests(unittest.TestCase):
    def test_address_chaining_uses_registers_left_by_prior_add(self):
        source = """
            ORG 100
START       A A2,B2
            A
            H
A1          DCW 1
A2          DCW 2
B1          DCW 10
B2          DCW 20
            END START
"""
        machine, image, result = run_source(source)
        self.assertIsNone(result.fault)
        self.assertEqual(machine.memory.numeric_value(image.symbols["B1"]), 11)
        self.assertEqual(machine.memory.numeric_value(image.symbols["B2"]), 22)

    def test_move_characters_preserves_destination_word_mark(self):
        source = """
            ORG 100
START       MCW AA,BB
            H
AA          DCW @ABC@
BB          DCW @000@
            END START
"""
        machine, image, result = run_source(source)
        self.assertIsNone(result.fault)
        units = image.symbols["BB"]
        self.assertEqual(machine.memory.field_text(units), "ABC")
        self.assertTrue(machine.memory.word_mark(units - 2))

    def test_compare_equal_and_unequal_branches(self):
        source = """
            ORG 100
START       C AA,BB
            BE EQUAL
            H
EQUAL       C AA,OTHER
            BU UNEQUAL
            H
UNEQUAL     H
AA          DCW @ABC@
BB          DCW @ABC@
OTHER       DCW @ABD@
            END START
"""
        machine, image, result = run_source(source)
        self.assertIsNone(result.fault)
        self.assertEqual(machine.last_instruction.address, image.symbols["UNEQUAL"])

    def test_branch_if_character_equal(self):
        source = """
            ORG 100
START       BCE FOUND,VALUE,@C@
            H
FOUND       H
VALUE       DCW @C@
            END START
"""
        machine, image, result = run_source(source)
        self.assertIsNone(result.fault)
        self.assertEqual(machine.last_instruction.address, image.symbols["FOUND"])

    def test_branch_on_minus_zone(self):
        source = """
            ORG 100
START       BM MINUS,VALUE
            H
MINUS       H
VALUE       DCW -1
            END START
"""
        machine, image, result = run_source(source)
        self.assertIsNone(result.fault)
        self.assertEqual(machine.last_instruction.address, image.symbols["MINUS"])

    def test_card_read_print_and_punch(self):
        source = """
            ORG 400
START       SW 1,201
            SW 101
            R
            MCW 80,180
            MCW 80,280
            W
            P
            H
            END START
"""
        machine, _, result = run_source(source, cards=["HELLO, 1401"])
        self.assertIsNone(result.fault)
        self.assertEqual(len(machine.printed_lines), 1)
        self.assertTrue(machine.printed_lines[0].startswith("HELLO, 1401"))
        self.assertEqual(len(machine.punched_cards), 1)
        self.assertTrue(machine.punched_cards[0].startswith("HELLO, 1401"))
        self.assertEqual(len(machine.punched_cards[0]), 80)

    def test_empty_card_reader_is_a_processor_stop(self):
        machine, _, result = run_source(" ORG 100\nSTART R\n H\n END START")
        self.assertEqual(result.reason, "fault")
        self.assertIn("card reader empty", result.fault)

    def test_halt_and_branch_on_resume(self):
        source = """
            ORG 100
START       H TARGET
            H
TARGET      H
            END START
"""
        image = assemble(source)
        machine = IBM1401()
        image.load_into(machine)
        first = machine.run()
        self.assertEqual(first.reason, "halt")
        self.assertTrue(machine.halt_branch_pending)
        machine.resume()
        second = machine.run()
        self.assertEqual(second.reason, "halt")
        self.assertEqual(machine.last_instruction.address, image.symbols["TARGET"])

    def test_indexed_address(self):
        source = """
            ORG 87
X1          DSA 1
            ORG 100
START       MCW SOURCE-1&X1,DEST
            H
SOURCE      DCW @Z@
DEST        DCW @0@
            END START
"""
        machine, image, result = run_source(source)
        self.assertIsNone(result.fault)
        self.assertEqual(machine.memory.field_text(image.symbols["DEST"]), "Z")

    def test_instruction_limit_does_not_change_processor_fault_state(self):
        source = " ORG 100\nSTART B START\n END START\n"
        _, _, result = run_source(source, max_instructions=20)
        self.assertEqual(result.reason, "limit")
        self.assertEqual(result.instructions, 20)

    def test_clear_storage_clears_characters_and_marks_to_hundred_boundary(self):
        source = """
            ORG 200
START       CS 105
            H
            END START
"""
        image = assemble(source)
        machine = IBM1401()
        for address in range(100, 106):
            machine.memory[address] = 1 | WORD_MARK
        image.load_into(machine, clear=False)
        result = machine.run()
        self.assertIsNone(result.fault)
        for address in range(100, 106):
            self.assertEqual(machine.memory[address], 0)


if __name__ == "__main__":
    unittest.main()
