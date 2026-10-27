from pathlib import Path
import subprocess
import sys
import unittest

from tests.helpers import run_source

ROOT = Path(__file__).resolve().parents[1]


class ExampleTests(unittest.TestCase):
    def test_arithmetic_example_and_edit_instruction(self):
        source = (ROOT / "examples" / "arithmetic.s").read_text(encoding="utf-8")
        machine, _, result = run_source(source)
        self.assertIsNone(result.fault)
        self.assertEqual(
            [line.rstrip() for line in machine.printed_lines],
            [" 4626578", "     421 CR", "  676578 CR", "       2", "     160"],
        )

    def test_hello_example(self):
        source = (ROOT / "examples" / "hello.s").read_text(encoding="utf-8")
        cards = (ROOT / "examples" / "cards.txt").read_text(encoding="utf-8").splitlines()
        machine, _, result = run_source(source, cards=cards)
        self.assertIsNone(result.fault)
        self.assertEqual(machine.printed_lines[0].rstrip(), "HELLO FROM THE IBM 1401")
        self.assertEqual(machine.punched_cards[0].rstrip(), "HELLO FROM THE IBM 1401")

    def test_command_line_interface(self):
        process = subprocess.run(
            [sys.executable, "-m", "ibm1401", "run", "examples/arithmetic.s"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn(" 676578 CR\n", process.stdout)
        self.assertIn("halted after 23 instructions", process.stderr)


if __name__ == "__main__":
    unittest.main()
