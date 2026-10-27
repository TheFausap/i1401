import unittest

from tests.helpers import run_source


class EditingTests(unittest.TestCase):
    def test_edit_zero_suppression_status_and_expanded_print_edit(self):
        # The control words exercise ordinary zero suppression, CR status,
        # floating dollar, asterisk protection, and Expanded Print Edit.
        source = """
            ORG 400
START       LCA ED1,215
            MCE AMT1,215
            LCA ED2,235
            MCE AMT2,235
            LCA ED3,255
            MCE AMT3,255
            LCA ED4,275
            MCE AMT4,275
            LCA ED5,295
            MCE AMT5,295
            W
            CS 332
            CS
            MCS Z1,210
            MCS Z2,220
            MCW @ABC@,233
            MZ @J@,233
            MN @5@,232
            W
            H
AMT1        DCW 0012345
AMT2        DCW -0012345
AMT3        DCW 0000007
AMT4        DCW 0004567
AMT5        DCW 0000003
ED1         DCW @ ,  0.  @
ED2         DCW @$  ,  0.  &CR@
ED3         DCW @ ,  0.  &CR@
ED4         DCW @*  ,  0.  @
ED5         DCW @$  ,   .  @
Z1          DCW 0001230
Z2          DCW @0,0405@
            END START
"""
        machine, _, result = run_source(source)
        self.assertIsNone(result.fault)
        self.assertEqual(
            machine.printed_lines[0].rstrip(),
            "         123.45       $   123.45 CR              .07             *    45.67          $00,000.03",
        )
        self.assertEqual(machine.printed_lines[1].rstrip(), "      1230       405          AEL")


if __name__ == "__main__":
    unittest.main()
