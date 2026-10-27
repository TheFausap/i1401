import random
import unittest

from ibm1401 import IBM1401, assemble
from ibm1401.bcd import A_ZONE, BA_ZONE, B_ZONE, ZONE, is_negative

from tests.helpers import (
    numeric_range,
    run_arithmetic,
    run_divide,
    run_multiply,
    run_source,
    signed_decimal,
)


class AddSubtractTests(unittest.TestCase):
    def test_reference_manual_addition(self):
        machine, units = run_arithmetic("A", "0025347", "04601231")
        self.assertEqual(machine.memory.field_text(units), "04626578")
        self.assertEqual(machine.memory.numeric_value(units), 4626578)
        self.assertFalse(machine.overflow)

    def test_unequal_lengths_zero_extend_a_field(self):
        machine, units = run_arithmetic("A", "123", "00000")
        self.assertEqual(machine.memory.numeric_value(units), 123)
        machine, units = run_arithmetic("S", "23", "000100")
        self.assertEqual(machine.memory.numeric_value(units), 77)

    def test_complement_add_and_recomplement(self):
        cases = (
            ("S", "1000", "00579", -421),
            ("A", "-7", "00003", -4),
            ("A", "7", "-00003", 4),
            ("S", "-7", "-0004", 3),
            ("S", "3", "-0007", -10),
            ("A", "-1000", "00002", -998),
        )
        for op, a, b, expected in cases:
            with self.subTest(op=op, a=a, b=b):
                machine, units = run_arithmetic(op, a, b)
                self.assertEqual(machine.memory.numeric_value(units), expected)

    def test_signed_zero_is_not_collapsed(self):
        cases = (
            ("A", "0", "0", False),
            ("A", "0", "-0", True),
            ("A", "-0", "0", False),
            ("A", "-0", "-0", True),
            ("S", "0", "0", False),
            ("S", "0", "-0", True),
            ("S", "-0", "-0", True),
        )
        for op, a, b, negative in cases:
            with self.subTest(op=op, a=a, b=b):
                machine, units = run_arithmetic(op, a, b)
                self.assertEqual(machine.memory.numeric_value(units), 0)
                self.assertEqual(is_negative(machine.memory[units]), negative)

    def test_zero_and_add_subtract_pad_and_normalize_sign(self):
        machine, units = run_arithmetic("ZA", "123", "000000")
        self.assertEqual(machine.memory.numeric_value(units), 123)
        self.assertEqual(machine.memory[units] & ZONE, BA_ZONE)
        machine, units = run_arithmetic("ZS", "123", "000000")
        self.assertEqual(machine.memory.numeric_value(units), -123)
        self.assertEqual(machine.memory[units] & ZONE, B_ZONE)
        machine, units = run_arithmetic("ZA", "-0", "000")
        self.assertTrue(is_negative(machine.memory[units]))

    def test_true_add_overflow_sets_indicator_and_high_zone(self):
        source = """
            ORG 100
START       A N1,W5
            H
N1          DCW 1
W5          DCW 99999
            END START
"""
        image = assemble(source)
        machine = IBM1401()
        image.load_into(machine)
        high = image.symbols["W5"] - 4
        for expected in (A_ZONE, B_ZONE, BA_ZONE, 0):
            machine.step()
            self.assertTrue(machine.overflow)
            self.assertEqual(machine.memory[high] & ZONE, expected)
            # Restore the same digits while retaining the overflow zone left
            # by the previous instruction, then execute the Add again.
            previous_zone = machine.memory[high] & ZONE
            machine.memory.load_text(high, "99999", preserve_word_marks=True)
            machine.memory[high] |= previous_zone
            machine.overflow = False
            machine.i_address = image.symbols["START"]

        source = """
            ORG 100
START       ZA N99999,W5
            A N1,W5
            BAV FIRST
            H
FIRST       ZA N99999,W5
            A N1,W5
            BAV SECOND
            H
SECOND      H
N99999      DCW 99999
N1          DCW 1
W5          DCW 00000
            END START
"""
        machine, image, result = run_source(source)
        self.assertIsNone(result.fault)
        self.assertFalse(machine.overflow)  # BAV tests and clears the latch.
        self.assertEqual(machine.last_instruction.address, image.symbols["SECOND"])

    def test_one_digit_overflow(self):
        machine, units = run_arithmetic("A", "1", "9")
        self.assertTrue(machine.overflow)
        self.assertEqual(machine.memory.numeric_value(units), 0)

    def test_deterministic_signed_arithmetic(self):
        rng = random.Random(1401)
        for _ in range(120):
            la = rng.randint(1, 7)
            lb = rng.randint(la, 8)
            # Leave one headroom digit so the mathematical result fits.
            a = rng.randint(-(10 ** (la - 1)), 10 ** (la - 1)) if la > 1 else rng.randint(-4, 4)
            b = rng.randint(-(10 ** (lb - 1)), 10 ** (lb - 1)) if lb > 1 else rng.randint(-4, 4)
            op = rng.choice(("A", "S"))
            expected = a + b if op == "A" else b - a
            if abs(expected) >= 10**lb:
                continue
            machine, units = run_arithmetic(op, signed_decimal(a, la), signed_decimal(b, lb))
            actual = machine.memory.numeric_value(units)
            self.assertEqual(actual, expected, (op, a, b, la, lb))
            self.assertFalse(machine.overflow)


class MultiplyDivideTests(unittest.TestCase):
    def test_reference_multiply_123_by_456(self):
        machine, units = run_multiply(123, 456, 3, 3)
        self.assertEqual(machine.memory.field_text(units), "005608H")
        self.assertEqual(machine.memory.numeric_value(units), 56088)

    def test_reference_multiply_negative(self):
        machine, units = run_multiply(-1246, 543, 4, 3)
        self.assertEqual(machine.memory.field_text(units), "0067657Q")
        self.assertEqual(machine.memory.numeric_value(units), -676578)

    def test_reference_divide_quotient_and_remainder(self):
        machine, quotient, remainder, bounds = run_divide(1246, 543, 4, 3)
        self.assertEqual((quotient, remainder), (2, 160))
        work_units = bounds[-1]
        total = 8
        self.assertEqual(machine.memory.text(work_units - total + 1, work_units), "000B016?")

    def test_reference_divide_million_by_seven(self):
        machine, quotient, remainder, bounds = run_divide(1_000_000, 7, 7, 1, prefix=4)
        self.assertEqual((quotient, remainder), (142857, 1))
        work_units = bounds[-1]
        self.assertEqual(machine.memory.text(work_units - 12, work_units), "0000014285G0A")

    def test_division_sign_rules(self):
        cases = (
            (1246, 543, 2, 160),
            (1246, -543, -2, -160),
            (-1246, 543, -2, 160),
            (-1246, -543, 2, -160),
        )
        for dividend, divisor, expected_q, expected_r in cases:
            with self.subTest(dividend=dividend, divisor=divisor):
                _, quotient, remainder, _ = run_divide(dividend, divisor, 4, 3)
                self.assertEqual((quotient, remainder), (expected_q, expected_r))

    def test_divide_by_zero_sets_overflow(self):
        machine, _, _, _ = run_divide(1234, 0, 4, 3)
        self.assertTrue(machine.overflow)
        self.assertIsNone(machine.fault)

    def test_multiply_divide_feature_can_be_removed(self):
        source = """
            ORG 100
START       M AA,BB
            H
AA          DCW 2
BB          DCW 0003
            END START
"""
        image = assemble(source)
        machine = IBM1401(multiply_divide=False)
        image.load_into(machine)
        result = machine.run()
        self.assertEqual(result.reason, "fault")
        self.assertIn("multiply/divide", result.fault)

    def test_deterministic_multiplication(self):
        rng = random.Random(1402)
        for _ in range(60):
            la = rng.randint(1, 5)
            lm = rng.randint(1, 5)
            a = rng.randint(1, 10**la - 1) * rng.choice((-1, 1))
            b = rng.randint(1, 10**lm - 1) * rng.choice((-1, 1))
            machine, units = run_multiply(a, b, la, lm)
            self.assertEqual(machine.memory.numeric_value(units), a * b, (a, b, la, lm))

    def test_deterministic_division(self):
        rng = random.Random(1403)
        for _ in range(60):
            ld = rng.randint(2, 7)
            ls = rng.randint(1, 4)
            dividend = rng.randint(1, 10**ld - 1) * rng.choice((-1, 1))
            divisor = rng.randint(1, 10**ls - 1) * rng.choice((-1, 1))
            _, quotient, remainder, _ = run_divide(dividend, divisor, ld, ls)
            expected_q = (abs(dividend) // abs(divisor)) * (-1 if (dividend < 0) ^ (divisor < 0) else 1)
            expected_r = (abs(dividend) % abs(divisor)) * (-1 if divisor < 0 else 1)
            self.assertEqual(quotient, expected_q, (dividend, divisor, ld, ls))
            self.assertEqual(remainder, expected_r, (dividend, divisor, ld, ls))


if __name__ == "__main__":
    unittest.main()
