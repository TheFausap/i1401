import unittest

from ibm1401.bcd import (
    BCD_TO_ASCII,
    CHAR,
    WORD_MARK,
    ZERO,
    check_bit,
    decode_address,
    encode_address,
    from_ascii,
    from_stored_byte,
    to_ascii,
    to_stored_byte,
    BCDError,
)
from ibm1401.memory import CoreMemory, MemoryError


class BCDTests(unittest.TestCase):
    def test_all_64_characters_round_trip(self):
        self.assertEqual(len(BCD_TO_ASCII), 64)
        for value in range(64):
            self.assertEqual(from_ascii(BCD_TO_ASCII[value]), [value])
            self.assertEqual(to_ascii([value]), BCD_TO_ASCII[value])

    def test_zero_is_eight_plus_two(self):
        self.assertEqual(ZERO, 0b1010)
        self.assertEqual(from_ascii("0"), [10])
        self.assertEqual(from_ascii(" "), [0])

    def test_address_round_trip_and_zone_encoding(self):
        for address in (0, 1, 999, 1000, 1999, 2000, 3999, 4000, 7999, 8000, 11999, 12000, 15999):
            with self.subTest(address=address):
                encoded = encode_address(address)
                self.assertEqual(decode_address(encoded), address)
        self.assertEqual(to_ascii(encode_address(1000)), "|00")
        self.assertEqual(to_ascii(encode_address(4000)), "00|")
        self.assertEqual(to_ascii(encode_address(15999)), "I9I")

    def test_invalid_address_character(self):
        with self.assertRaises(BCDError):
            decode_address((0, 0, 0))
        with self.assertRaises(BCDError):
            decode_address((11, 10, 10))

    def test_odd_parity_includes_word_mark(self):
        for value in range(64):
            for mark in (0, WORD_MARK):
                stored = to_stored_byte(value | mark)
                self.assertEqual(stored.bit_count() % 2, 1)
                self.assertEqual(from_stored_byte(stored), value | mark)
                self.assertEqual((stored >> 7), check_bit(value | mark))

    def test_parity_error_is_detected(self):
        stored = to_stored_byte(WORD_MARK | 5)
        with self.assertRaises(BCDError):
            from_stored_byte(stored ^ 0x80)


class MemoryTests(unittest.TestCase):
    def test_word_marks_are_independent_of_characters(self):
        memory = CoreMemory(4000)
        memory.load_text(100, "12345", word_mark=True)
        self.assertTrue(memory.word_mark(100))
        for address in range(101, 105):
            self.assertFalse(memory.word_mark(address))
        memory.write_character(100, from_ascii("9")[0])
        self.assertTrue(memory.word_mark(100))
        self.assertEqual(memory.field_text(104), "92345")
        memory.set_word_mark(100, False)
        with self.assertRaises(MemoryError):
            memory.field_text(104)

    def test_numeric_sign_and_negative_zero(self):
        memory = CoreMemory()
        units = memory.load_number(200, "-000", signed_positive=True)
        self.assertEqual(memory.numeric_value(units), 0)
        self.assertEqual(memory[units] & 0x30, 0x20)
        self.assertEqual(memory.text(200, units), "00!")

    def test_raw_memory_parity_round_trip(self):
        memory = CoreMemory(1400)
        memory.load_text(1, "HELLO", word_mark=True)
        restored = CoreMemory(1400)
        restored.import_bytes(memory.export_bytes())
        self.assertEqual(list(restored), list(memory))

    def test_bounds(self):
        memory = CoreMemory(1400)
        with self.assertRaises(MemoryError):
            _ = memory[1400]
        with self.assertRaises(MemoryError):
            memory.load_text(1399, "AB")


if __name__ == "__main__":
    unittest.main()
