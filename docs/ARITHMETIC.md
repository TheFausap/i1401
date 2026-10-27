# IBM 1401 arithmetic in this simulator

The primary reference is IBM A24-1403-5 (April 1962), “Arithmetic Operations” and “Multiply-Divide Feature.” This document describes the representation used by `ibm1401.cpu` and gives layouts that can be used in tests or new programs.

## 1. Numeric fields

A numeric field is a sequence of BA8421 characters. Its high-order digit is at the lowest address and carries the field-defining word mark. Its units digit is at the highest address. Instructions name the **units position** for ordinary two-address arithmetic.

```text
address:       500 501 502 503 504
character:       0   0   1   2   3
word mark:       ^

A-address or B-address = 504
```

Arithmetic proceeds from right to left: 504, 503, 502, 501, 500.

The digit nibble `8+2` (decimal BCD value 10) is character `0`. A blank nibble also has numeric value zero in the adder. Zone bits away from the units position are ignored as signs; arithmetic clears or processes them according to the individual instruction.

### Signs and zero

A units zone of **B without A** is negative. No zone, A only, and BA are positive. Arithmetic results normally use B for negative and BA for positive. A negative zero therefore has zero digits but retains its B zone.

This distinction matters. For example, adding positive zero to a negative-zero B field leaves a negative zero under the machine’s sign-control rules. The simulator does not normalize all zeroes to a single host-language `0`.

## 2. Add and subtract

For `A`, the operation is `B = B + A`. For `S`, it is `B = B - A`.

Let `subtract` be false for `A` and true for `S`. The processor selects complement addition when:

```text
negative(A) XOR negative(B) XOR subtract
```

is true. Otherwise it performs a true add.

### True add

Digits are added from units to high order with a decimal carry. The B-field word mark ends the operation. If A is shorter, its exhausted positions contribute zero. The result keeps the B field’s sign.

A carry out of a true add sets the arithmetic-overflow indicator. At a multi-digit B field’s high-order position, the zone adder also combines the incoming A/B high-order zones and the carry. Starting without high-order zones, repeated overflow carries produce:

| Carry | High-order zone |
|---|---|
| First | A |
| Second | B |
| Third | BA |
| Fourth | none; the cycle repeats |

The stored digit is the decimal residue; a field does not grow to accommodate the carry.

### Complement add and recomplement

The A digit is effectively converted to its ten’s complement in the units position and nine’s complement in subsequent positions. If there is a carry beyond the B field, the result is already in true form. If there is no carry, the processor performs another right-to-left scan, recomplements the result, and toggles its sign.

The implementation performs that scan explicitly. It does not choose a sign by comparing host-language magnitudes, which would lose the original sign zones and signed-zero behavior.

### Address registers and chaining

After the operation, ASTAR and BSTAR point one position below the last A/B positions examined. A one-character `A` or `S` reuses those registers. This is why consecutive fields can be processed by a full instruction followed by chained one-character instructions.

## 3. Zero and add / zero and subtract

`ZA` (`?`) and `ZS` (`!`) are field-transfer operations, not ordinary integer addition:

1. Copy A digits into B until the **B-field** word mark is reached.
2. If A ends first, fill the remaining high-order B positions with zero.
3. Strip zone bits from copied positions. Unlike the adder, this transfer retains the original digit nibble rather than normalizing an unusual nibble through addition.
4. Set the units sign from A, normalized to BA for positive or B for negative. `ZS` complements that sign.
5. Preserve B word marks.

These instructions are useful for preparing multiplier, dividend, and work fields as well as for ordinary signed copies.

## 4. Multiply (`@`, Autocoder `M`)

The A field is the multiplicand. The high-order part of B contains the multiplier, followed by one zero and enough product space for the multiplicand length.

If A has length `LA` and the multiplier has length `LM`, the B-field length is:

```text
LA + 1 + LM
```

Initial layout for `123 × 456`:

```text
B high                                                   B units
  |                                                         |
  v                                                         v
+----- multiplier -----+-- extra zero --+-- product space --+
|         456          |       0        |        000        |
+-----------------------------------------------------------+
```

The B address names the rightmost position. The instruction clears the extra zero and product space, develops each partial product in place, clears each multiplier digit after using it, and writes the final sign in the rightmost product digit.

Final seven-digit result:

```text
0056088   (the units 8 carries the canonical positive BA zone)
```

In the simulator’s A-chain text representation this appears as `005608H`, because BCD `H` is BA-zone digit 8.

The required B-field word mark is retained at the high-order end. Product digits and sign zones are not calculated by converting the complete operands to host integers.

## 5. Divide (`%`, Autocoder `D`)

The A field is the divisor and is addressed at its units digit. The B address is different from ordinary arithmetic: it names the **high-order digit of the dividend**, not the units digit of the entire work field. The dividend’s units digit is found by its sign zone.

For divisor length `LS` and dividend length `LD`, reserve at least `LS + 1` zero positions immediately to the left of the dividend. A word-marked work field may also contain additional high-order padding.

Before division:

```text
                         B address
                             |
                             v
+-- quotient workspace --+--- dividend, with sign in its units digit ---+
|     LS + 1 zeroes      |                LD digits                     |
+------------------------+----------------------------------------------+
```

The machine repeatedly subtracts the divisor from successive subdividends, restoring after the subtraction that borrows. Each subtraction count becomes one quotient digit. A count above nine sets overflow and stores the count’s decimal residue.

After `LD` quotient digits:

```text
+---------- quotient: LD digits ----------+-- remainder: LS + 1 digits --+
```

The quotient begins `LS + 1` positions left of the original high-order dividend. The remainder ends at the original dividend units position. Additional padding to the left of the quotient is unchanged.

For `1246 ÷ 543`, using an eight-character work field:

```text
quotient     remainder
0002         0160
```

Canonical positive sign zones make the exact A-chain text `000B016?`: `B` is BA-zone 2 and `?` is BA-zone 0.

For `1,000,000 ÷ 7`, the generated quotient is `0142857` and the two-position remainder area is `01`. With four leading work-field padding zeroes, the exact text is `0000014285G0A`.

The quotient sign is the exclusive-or of the divisor and dividend signs. The remainder receives the divisor sign, matching the 1401 divide algorithm. Division by zero sets the overflow indicator rather than raising a host `ZeroDivisionError`.

After a normal divide, BSTAR addresses the quotient’s tens position, which permits the documented chaining behavior.

## 6. Host safety limits versus machine behavior

`run(max_instructions=...)` is a host-side safeguard and does not set a hardware indicator. A separate operation-cycle safeguard stops pathological repeated subtraction, such as a malformed program overlapping its divisor and quotient until the divisor becomes zero. Increase `machine.max_operation_cycles` for deliberately enormous valid operations.

Genuine processor stops—invalid addresses, address wrap, missing opcode word marks, unavailable special features, and an empty card reader—set `machine.fault` and halt execution.

## 7. What is not modeled

The simulator is instruction-accurate for the implemented operations, not a transistor or timing model. It does not reproduce the qui-binary adder’s internal error checking, core-cycle timing, or analog/device behavior. Raw core import/export does, however, generate and validate the odd C parity bit, including the word mark in the parity calculation.
