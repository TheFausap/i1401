# i1401 — IBM 1401 simulator

A dependency-free Python simulation of the IBM 1401, with particular attention to its signed, variable-length decimal arithmetic. It models six-bit BCD characters, independent word marks, three-character decimal addresses, instruction chaining, processor indicators, and the optional multiply/divide instructions.

The arithmetic engine operates **digit by digit in simulated core storage**. It does not convert a whole field to a Python integer, perform the operation, and convert it back. Consequently, complement addition, recomplementing, signed zero, unequal field lengths, overflow zones, partial products, and long-division remainder placement are all represented explicitly.

## Quick start

Python 3.10 or newer is the only requirement.

```sh
# Run the arithmetic demonstration
python -m ibm1401 run examples/arithmetic.s

# See each instruction and the A/B address registers
python -m ibm1401 run examples/arithmetic.s --trace

# Read, print, and punch a card image
python -m ibm1401 run examples/hello.s \
  --cards examples/cards.txt --punch punched.txt

# Produce an assembly listing
python -m ibm1401 assemble examples/arithmetic.s

# Run all tests
python -m unittest discover -v
```

The arithmetic example prints:

```text
 4626578
     421 CR
  676578 CR
       2
     160
```

These are the sum, difference, product, quotient, and remainder. `CR` is emitted by the 1401 **Move Characters and Edit** instruction for a negative field.

You can also install the package to get an `i1401` command:

```sh
python -m pip install -e .
i1401 run examples/arithmetic.s
```

## Python API

```python
from ibm1401 import IBM1401, assemble

source = """
    ORG 100
START   A X,Y
        H
X       DCW 123
Y       DCW 456
        END START
"""

image = assemble(source)
machine = IBM1401(memory_size=16000)
image.load_into(machine)
result = machine.run()

assert result.reason == "halt"
assert machine.memory.numeric_value(image.symbols["Y"]) == 579
```

Use `machine.step()` for single instructions, `machine.trace` for a trace callback, and `machine.memory[start]` to inspect the raw BCD-plus-word-mark value at a core address. Addresses are actual decimal locations, so reader area 001–080, punch area 101–180, and print area 201–332 retain their conventional meanings.

## Arithmetic highlights

- Numeric fields run from a word-marked high-order digit at the lowest address to a units digit at the highest address.
- The adder treats blanks and zeroes as zero. A B-only zone in the units position means minus; every other zone combination is positive.
- `A` and `S` implement true and ten’s-complement addition, including the automatic recomplement scan when the complement result has no carry.
- `ZA` and `ZS` follow the hardware’s field-copy behavior: strip zones, pad a longer B field with zeroes, preserve its word marks, and normalize the result sign.
- A true-add carry sets the overflow indicator. High-order zone bits also accumulate overflow counts in the sequence **A, B, BA, none**.
- `BAV` (`B ... Z`) tests **and clears** the overflow indicator.
- `@` (`M` in Autocoder) develops partial products in place. `%` (`D`) performs repeated-subtraction decimal long division and leaves both quotient and remainder in storage.
- Positive and negative zero remain distinct, as they are on the machine.

See [docs/ARITHMETIC.md](docs/ARITHMETIC.md) for operand diagrams and edge cases.

## Source language

The included assembler is a compact, free-form Autocoder-style frontend, not a complete historical Tape Autocoder implementation.

```text
LABEL   OP   OPERAND1,OPERAND2,d
```

Supported data and control statements:

| Statement | Meaning |
|---|---|
| `ORG address` | Set the assembly location. |
| `EQU expression` | Equate a label to an address. |
| `DCW constant` | Define a constant with a high-order word mark. |
| `DC constant` | Define a constant without adding a word mark. |
| `DS length` | Reserve blank storage. |
| `DSA expression` | Store a three-character encoded address. |
| `END label` | Set the entry point. |
| `JOB`, `CTL`, `LTORG` | Accepted as non-emitting statements. |

Constants can be decimal (`123`, `-00123`, `+7`), character (`@HELLO@`), or blank (`#80`). Instruction literals `@TEXT@` and `&123` are emitted into a word-marked literal pool. Address expressions accept `LABEL`, `LABEL+3`, `LABEL-3`, numbers, and `*`; append `&X1`, `&X2`, or `&X3` for indexing.

**A label on a data constant denotes its units (rightmost) position**, matching Autocoder arithmetic usage. A label on an instruction denotes its opcode position. For example, `PRODUCT-5` addresses five positions before the units position of `PRODUCT`.

Common mnemonics include:

| Mnemonics | Operations |
|---|---|
| `A S ZA ZS M D` | Add, subtract, zero-and-add/subtract, multiply (`@`), divide (`%`) |
| `MCW LCA MN MZ MCS MCE MCM` | Character/data movement and editing |
| `C B BCE BWZ BW BM BBE` | Compare and branch |
| `BAV BE BU BH BL BIN BSS` | Indicator branches |
| `SW CW CS` | Set/clear word marks and clear storage |
| `R W P WR RP WP WRP` | Card/printer stream operations |
| `SAR SBR MA` | Store address registers and modify address |
| `NOP H SS CC CCB SRF SPF` | Miscellaneous operations |

The assembler always places a word mark on an instruction opcode. In listings, `^` precedes a word-marked character.

## Implemented machine scope

- Core sizes: 1400, 2000, 4000, 8000, 12000, and 16000 characters.
- Variable-length instruction fetch, A/B address chaining, and three index registers.
- Signed arithmetic and the optional multiply/divide feature (enabled by default).
- Compare and high/low/equal indicators, bit tests, sense switches, and overflow testing.
- Move/load, edit, zero suppression, move record, address-register storage, and address modification.
- Stream-oriented card reader, punch, and 132-column printer areas.
- Generated and checked odd parity for raw core import/export.

This is an **instruction-level**, not gate-level, simulation. Magnetic tape, RAMAC/1311 disk, column binary, console inquiry, mechanical device timing, carriage-tape behavior, processing overlap, and qui-binary circuit timing are outside the current scope. Card, punch, and printer devices use host strings and do not simulate motor timing. Parity faults cannot be injected during ordinary CPU execution; parity is checked when importing raw core bytes.

## Validation

The test suite includes:

- All 64 BCD characters, decimal addresses, word marks, and odd parity.
- Reference-manual arithmetic examples and exact signed BCD results.
- True/complement addition, recomplementing, signed zero, and overflow.
- Exact multiply/divide field layouts, signs, quotients, and remainders.
- Deterministic randomized signed arithmetic over varied field lengths.
- Assembly, branch word marks, chaining, indexing, I/O, editing, halt/resume, and fault handling.

The primary reference is IBM **A24-1403-5, Reference Manual: IBM 1401 Data Processing System** (April 1962), especially arithmetic operations and the multiply/divide feature. The manual is available in the [Bitsavers IBM 1401 collection](http://bitsavers.informatik.uni-stuttgart.de/pdf/ibm/1401/). Arithmetic behavior was also cross-checked against the established SIMH i1401 implementation; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## License

MIT; see [LICENSE](LICENSE).
