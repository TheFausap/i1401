"""Instruction-level IBM 1401 processor simulation.

The implementation follows IBM A24-1403-5 (April 1962).  Arithmetic is
performed character serially in core storage; host integers are used only for
one-digit intermediate values and addresses, never as a shortcut for a whole
numeric field.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable, Iterable, TextIO

from .bcd import (
    A_ZONE,
    BA_ZONE,
    B_ZONE,
    CHAR,
    DIGIT,
    GROUP_MARK,
    RECORD_MARK,
    WORD_MARK,
    ZONE,
    ZERO,
    BCD_TO_ASCII,
    char,
    decimal_char,
    decimal_digit,
    decode_address,
    encode_address,
    is_negative,
    to_ascii,
)
from .memory import CoreMemory, MemoryError

# Operation codes (the values are BA8421, not ASCII).
OP_R = 0x01
OP_W = 0x02
OP_WR = 0x03
OP_P = 0x04
OP_RP = 0x05
OP_WP = 0x06
OP_WRP = 0x07
OP_SRF = 0x08
OP_SPF = 0x09
OP_MA = 0x0B
OP_MUL = 0x0C
OP_CS = 0x11
OP_S = 0x12
OP_MTF = 0x14
OP_BWZ = 0x15
OP_BBE = 0x16
OP_MZ = 0x18
OP_MCS = 0x19
OP_SWM = 0x1B
OP_DIV = 0x1C
OP_SS = 0x22
OP_LCA = 0x23
OP_MCW = 0x24
OP_NOP = 0x25
OP_MCM = 0x27
OP_SAR = 0x28
OP_ZS = 0x2A
OP_A = 0x31
OP_B = 0x32
OP_C = 0x33
OP_MN = 0x34
OP_MCE = 0x35
OP_CC = 0x36
OP_SBR = 0x38
OP_ZA = 0x3A
OP_HALT = 0x3B
OP_CWM = 0x3C

# Indicators selected by the d-character of a five-character Branch.
IN_UNEQUAL = 0x11  # /
IN_EQUAL = 0x12  # S
IN_LOW = 0x13  # T
IN_HIGH = 0x14  # U
IN_OVERFLOW = 0x19  # Z
IN_PRINTER_ERROR = 0x1A
IN_PROCESS_CHECK = 0x1C
IN_END_OF_REEL = 0x22  # K
IN_TAPE_ERROR = 0x23  # L
IN_PRINTER_BUSY = 0x27  # P
IN_INQUIRY = 0x28  # Q
IN_CARRIAGE_BUSY = 0x29  # R
IN_PUNCH_ERROR = 0x2A  # !
IN_LAST_CARD = 0x31  # A
IN_SENSE_B = 0x32
IN_SENSE_G = 0x37
IN_READER_ERROR = 0x3A  # ?

RESET_ON_TEST = {
    IN_OVERFLOW,
    IN_PRINTER_ERROR,
    IN_PROCESS_CHECK,
    IN_PUNCH_ERROR,
    IN_INQUIRY,
    IN_END_OF_REEL,
    IN_TAPE_ERROR,
    IN_READER_ERROR,
}

MNEMONICS = {
    OP_R: "R",
    OP_W: "W",
    OP_WR: "WR",
    OP_P: "P",
    OP_RP: "RP",
    OP_WP: "WP",
    OP_WRP: "WRP",
    OP_SRF: "SRF",
    OP_SPF: "SPF",
    OP_MA: "MA",
    OP_MUL: "M",
    OP_CS: "CS",
    OP_S: "S",
    OP_MTF: "CU",
    OP_BWZ: "BWZ",
    OP_BBE: "BBE",
    OP_MZ: "MZ",
    OP_MCS: "MCS",
    OP_SWM: "SW",
    OP_DIV: "D",
    OP_SS: "SS",
    OP_LCA: "LCA",
    OP_MCW: "MCW",
    OP_NOP: "NOP",
    OP_MCM: "MCM",
    OP_SAR: "SAR",
    OP_ZS: "ZS",
    OP_A: "A",
    OP_B: "B",
    OP_C: "C",
    OP_MN: "MN",
    OP_MCE: "MCE",
    OP_CC: "CC",
    OP_SBR: "SBR",
    OP_ZA: "ZA",
    OP_HALT: "H",
    OP_CWM: "CW",
}

# Legal lengths for the implemented instruction forms.  NOP and Halt are
# deliberately permissive on the real machine; the same common forms are
# accepted here.
_TWO_ADDRESS = frozenset((1, 4, 7, 8))
_LEGAL_LENGTHS = {
    OP_R: frozenset((1, 2, 4, 5)),
    OP_W: frozenset((1, 2, 4, 5)),
    OP_WR: frozenset((1, 2, 4, 5)),
    OP_P: frozenset((1, 2, 4, 5)),
    OP_RP: frozenset((1, 4)),
    OP_WP: frozenset((1, 2, 4, 5)),
    OP_WRP: frozenset((1, 2, 4, 5)),
    OP_SRF: frozenset((1,)),
    OP_SPF: frozenset((1,)),
    OP_MA: frozenset((1, 4, 7)),
    OP_MUL: _TWO_ADDRESS,
    OP_CS: frozenset((1, 4, 7)),
    OP_S: _TWO_ADDRESS,
    OP_BWZ: frozenset((1, 8)),
    OP_BBE: frozenset((1, 8)),
    OP_MZ: _TWO_ADDRESS,
    OP_MCS: _TWO_ADDRESS,
    OP_SWM: frozenset((1, 4, 7)),
    OP_DIV: _TWO_ADDRESS,
    OP_SS: frozenset((2, 5)),
    OP_LCA: _TWO_ADDRESS,
    OP_MCW: _TWO_ADDRESS,
    OP_NOP: frozenset((1, 2, 4, 5, 7, 8)),
    OP_MCM: frozenset((1, 4, 7)),
    OP_SAR: frozenset((1, 4)),
    OP_ZS: _TWO_ADDRESS,
    OP_A: _TWO_ADDRESS,
    OP_B: frozenset((1, 4, 5, 7, 8)),
    OP_C: _TWO_ADDRESS,
    OP_MN: _TWO_ADDRESS,
    OP_MCE: _TWO_ADDRESS,
    OP_CC: frozenset((2, 5)),
    OP_SBR: frozenset((1, 4, 7)),
    OP_ZA: _TWO_ADDRESS,
    OP_HALT: frozenset((1, 2, 4, 5, 7, 8)),
    OP_CWM: frozenset((1, 4, 7)),
}

# BCD collating order used by the high/low/equal compare special feature.
_COLLATING_SEQUENCE = (
    0o000, 0o073, 0o074, 0o075, 0o076, 0o077, 0o060, 0o053,
    0o054, 0o055, 0o056, 0o057, 0o040, 0o021, 0o033, 0o034,
    0o035, 0o036, 0o037, 0o020, 0o013, 0o014, 0o015, 0o016,
    0o017, 0o072, 0o061, 0o062, 0o063, 0o064, 0o065, 0o066,
    0o067, 0o070, 0o071, 0o052, 0o041, 0o042, 0o043, 0o044,
    0o045, 0o046, 0o047, 0o050, 0o051, 0o032, 0o022, 0o023,
    0o024, 0o025, 0o026, 0o027, 0o030, 0o031, 0o012, 0o001,
    0o002, 0o003, 0o004, 0o005, 0o006, 0o007, 0o010, 0o011,
)
COLLATING_RANK = [0] * 64
for _rank, _code in enumerate(_COLLATING_SEQUENCE):
    COLLATING_RANK[_code] = _rank


class MachineFault(RuntimeError):
    """A processor check or invalid memory operation."""


class InstructionLimit(RuntimeError):
    """Raised only when a caller explicitly requests a hard execution limit."""


@dataclass(frozen=True)
class Instruction:
    address: int
    values: tuple[int, ...]
    opcode: int
    a_address: int
    b_address: int
    d_character: int

    @property
    def length(self) -> int:
        return len(self.values)

    @property
    def mnemonic(self) -> str:
        return MNEMONICS.get(self.opcode, "???")

    @property
    def text(self) -> str:
        return to_ascii(self.values)


@dataclass(frozen=True)
class RunResult:
    instructions: int
    reason: str
    fault: str | None = None


class IBM1401:
    """An instruction-steppable IBM 1401 with card, punch, and print streams."""

    def __init__(
        self,
        memory_size: int = 16000,
        *,
        multiply_divide: bool = True,
        indexing: bool = True,
        high_low_equal: bool = True,
        bit_test: bool = True,
        expanded_print_edit: bool = True,
        move_record: bool = True,
        cards: Iterable[str] = (),
    ) -> None:
        self.memory = CoreMemory(memory_size)
        self.multiply_divide = multiply_divide
        self.indexing = indexing
        self.high_low_equal = high_low_equal
        self.bit_test = bit_test
        self.expanded_print_edit = expanded_print_edit
        self.move_record = move_record
        self.modify_address_enabled = memory_size > 4000

        self.i_address = 0
        self.a_address = -1
        self.b_address = -1
        self.d_character = 0
        self.indicators = [False] * 64
        self.sense_switches = {c: False for c in "BCDEFG"}
        self.sense_switches["A"] = True

        self.cards = deque(cards)
        self.printed_lines: list[str] = []
        self.punched_cards: list[str] = []
        self.selected_stackers: list[str] = []
        self.carriage_controls: list[str] = []

        self.halted = False
        self.fault: str | None = None
        self.halt_branch_pending = False
        self.instruction_count = 0
        self.last_instruction: Instruction | None = None
        self.max_operation_cycles = 2_000_000
        self._operation_cycles = 0
        self.trace: Callable[[Instruction], None] | None = None

    @property
    def overflow(self) -> bool:
        return self.indicators[IN_OVERFLOW]

    @overflow.setter
    def overflow(self, value: bool) -> None:
        self.indicators[IN_OVERFLOW] = bool(value)

    def reset(self, *, clear_memory: bool = False) -> None:
        if clear_memory:
            self.memory.clear()
        self.a_address = self.b_address = -1
        self.d_character = 0
        self.indicators = [False] * 64
        self.halted = False
        self.fault = None
        self.halt_branch_pending = False
        self.instruction_count = 0
        self.last_instruction = None

    def resume(self) -> None:
        """Implement Start after a Halt, including a pending halt-and-branch."""

        if self.fault:
            self.fault = None
        if self.halt_branch_pending:
            self._validate_address(self.a_address, "branch")
            self.i_address = self.a_address
            self.halt_branch_pending = False
        self.halted = False

    def _validate_address(self, address: int, role: str = "core") -> int:
        if not 0 <= address < self.memory.size:
            raise MachineFault(f"invalid {role} address {address}")
        return address

    def _get(self, address: int) -> int:
        self._validate_address(address)
        return self.memory[address]

    def _put(self, address: int, value: int) -> None:
        self._validate_address(address)
        self.memory[address] = value

    @staticmethod
    def _decrement(address: int) -> int:
        if address <= 0:
            raise MachineFault("address wrapped below core location 000")
        return address - 1

    def _decrement_a(self) -> None:
        self.a_address = self._decrement(self.a_address)

    def _decrement_b(self) -> None:
        self.b_address = self._decrement(self.b_address)

    def _work(self, cycles: int = 1) -> None:
        self._operation_cycles += cycles
        if self._operation_cycles > self.max_operation_cycles:
            raise MachineFault(
                "operation cycle limit exceeded; check field layout or raise max_operation_cycles"
            )

    def _decode_instruction_address(self, values: tuple[int, ...], role: str) -> int:
        try:
            base = decode_address(values)
        except ValueError as exc:
            raise MachineFault(f"invalid {role}-address: {exc}") from exc
        index = (values[1] & ZONE) >> 4
        if index and self.indexing:
            # X1, X2, X3 occupy 087-089, 092-094, and 097-099.
            start = {1: 87, 2: 92, 3: 97}[index]
            try:
                offset = decode_address(tuple(self._get(start + i) for i in range(3)))
            except ValueError as exc:
                raise MachineFault(f"invalid index register X{index}: {exc}") from exc
            base = (base + offset) % 16000
        return base

    def _fetch(self) -> Instruction:
        start = self._validate_address(self.i_address, "instruction")
        first = self._get(start)
        if not first & WORD_MARK:
            raise MachineFault(f"no word mark under operation code at {start:05d}")
        opcode = first & CHAR
        if opcode not in _LEGAL_LENGTHS:
            raise MachineFault(f"invalid or uninstalled operation code {BCD_TO_ASCII[opcode]!r}")
        if opcode == OP_SAR:
            # SAR saves ASTAR before the new A-address is loaded.
            self.b_address = self.a_address

        marked = [first]
        values = [opcode]
        while True:
            length = len(values)
            next_address = start + length
            if length == 7 and opcode in (OP_SWM, OP_CS):
                break
            if length == 4 and opcode == OP_B:
                following = self._get(next_address)
                if not following & WORD_MARK and (following & CHAR) == 0:
                    break
            following = self._get(next_address)
            if following & WORD_MARK:
                break
            if length >= 8:
                raise MachineFault(f"instruction at {start:05d} exceeds eight characters")
            values.append(following & CHAR)
            marked.append(following)

        length = len(values)
        if length not in _LEGAL_LENGTHS[opcode]:
            raise MachineFault(
                f"invalid {length}-character {MNEMONICS[opcode]} instruction at {start:05d}"
            )
        self.i_address = start + length
        if length > 1:
            self.d_character = values[-1]

        if length >= 4:
            self.a_address = self._decode_instruction_address(tuple(values[1:4]), "A")
            if opcode not in (OP_MCW, OP_LCA, OP_SAR, OP_SBR):
                self.b_address = self.a_address
        if length >= 7:
            self.b_address = self._decode_instruction_address(tuple(values[4:7]), "B")

        return Instruction(
            start,
            tuple(values),
            opcode,
            self.a_address,
            self.b_address,
            self.d_character,
        )

    def step(self) -> Instruction | None:
        """Fetch and execute one instruction; return its decoded description."""

        if self.halted:
            return None
        self._operation_cycles = 0
        instruction: Instruction | None = None
        try:
            instruction = self._fetch()
            self._execute(instruction)
            self.instruction_count += 1
            self.last_instruction = instruction
        except (MachineFault, MemoryError) as exc:
            self.fault = str(exc)
            self.halted = True
            if instruction is not None:
                self.last_instruction = instruction
        if instruction is not None and self.trace:
            self.trace(instruction)
        return instruction

    def run(self, max_instructions: int = 1_000_000) -> RunResult:
        """Run until Halt, a processor fault, or the host safety limit."""

        executed = 0
        while not self.halted and executed < max_instructions:
            before = self.instruction_count
            self.step()
            if self.instruction_count != before:
                executed += 1
            elif self.fault:
                break
        if self.fault:
            return RunResult(executed, "fault", self.fault)
        if self.halted:
            return RunResult(executed, "halt")
        return RunResult(executed, "limit")

    def _branch(self) -> None:
        self._validate_address(self.a_address, "branch")
        next_instruction = self.i_address
        self.i_address = self.a_address
        self.b_address = next_instruction

    def _execute(self, ins: Instruction) -> None:
        op = ins.opcode
        if op in (OP_A, OP_S):
            self._add_or_subtract(subtract=op == OP_S)
        elif op in (OP_ZA, OP_ZS):
            self._zero_and_transfer(negate=op == OP_ZS)
        elif op == OP_MUL:
            self._require_feature(self.multiply_divide, "multiply/divide")
            self._multiply()
        elif op == OP_DIV:
            self._require_feature(self.multiply_divide, "multiply/divide")
            self._divide()
        elif op == OP_C:
            self._compare(ins.length)
        elif op == OP_MCW:
            self._move_characters(load=False)
        elif op == OP_LCA:
            self._move_characters(load=True)
        elif op == OP_MN:
            self._move_numeric(zone=False)
        elif op == OP_MZ:
            self._move_numeric(zone=True)
        elif op == OP_MCS:
            self._move_and_suppress_zeroes()
        elif op == OP_MCE:
            self._move_and_edit()
        elif op == OP_MCM:
            self._require_feature(self.move_record, "move record")
            self._move_record()
        elif op in (OP_SWM, OP_CWM):
            enabled = op == OP_SWM
            self.memory.set_word_mark(self._validate_address(self.b_address, "B"), enabled)
            self.memory.set_word_mark(self._validate_address(self.a_address, "A"), enabled)
            self._decrement_a()
            self._decrement_b()
        elif op == OP_CS:
            self._clear_storage(ins.length)
        elif op == OP_B:
            self._branch_instruction(ins.length)
        elif op == OP_BWZ:
            self._branch_word_mark_or_zone()
        elif op == OP_BBE:
            self._require_feature(self.bit_test, "branch if bit equal")
            if self._get(self.b_address) & self.d_character & CHAR:
                self._branch()
            else:
                self._decrement_b()
        elif op in (OP_SAR, OP_SBR):
            self._store_address_register()
        elif op == OP_MA:
            self._require_feature(self.modify_address_enabled, "modify address")
            self._modify_address()
        elif op == OP_R:
            self._io_read()
            self.b_address = 81
            if ins.length in (4, 5):
                self._branch()
        elif op == OP_W:
            self._io_write()
            self.b_address = 333
            if ins.length in (4, 5):
                self._branch()
        elif op == OP_P:
            self._io_punch()
            self.b_address = 181
            if ins.length in (4, 5):
                self._branch()
        elif op == OP_WR:
            self._io_write()
            self._io_read()
            self.b_address = 81
            if ins.length in (4, 5):
                self._branch()
        elif op == OP_RP:
            self._io_read()
            self._io_punch()
            self.b_address = 181
            if ins.length in (4, 5):
                self._branch()
        elif op == OP_WP:
            self._io_write()
            self._io_punch()
            self.b_address = 181
            if ins.length in (4, 5):
                self._branch()
        elif op == OP_WRP:
            self._io_write()
            self._io_read()
            self._io_punch()
            self.b_address = 181
            if ins.length in (4, 5):
                self._branch()
        elif op in (OP_SRF, OP_SPF):
            pass  # Feed motion has no processor-visible data effect here.
        elif op == OP_SS:
            self.selected_stackers.append(BCD_TO_ASCII[self.d_character & CHAR])
        elif op == OP_CC:
            self.carriage_controls.append(BCD_TO_ASCII[self.d_character & CHAR])
            if ins.length == 5:
                self._branch()
        elif op == OP_NOP:
            pass
        elif op == OP_HALT:
            self.halt_branch_pending = ins.length == 4
            self.halted = True
        else:  # pragma: no cover - guarded by the fetch opcode table
            raise MachineFault(f"unimplemented operation {op}")

    @staticmethod
    def _require_feature(enabled: bool, name: str) -> None:
        if not enabled:
            raise MachineFault(f"special feature not installed: {name}")

    # ------------------------------------------------------------------
    # Arithmetic

    def _zero_and_transfer(self, *, negate: bool) -> None:
        """ZA/ZS: copy with zone stripping, B-field length and sign control."""

        a = 0
        first = True
        while True:
            self._work()
            if a & WORD_MARK:
                wm = (self._get(self.b_address) & WORD_MARK) | ZERO
                self._put(self.b_address, wm)
            else:
                a = self._get(self.a_address)
                wm = (self._get(self.b_address) & WORD_MARK) | (a & DIGIT)
                self._put(self.b_address, wm)
                self._decrement_a()
            if first:
                negative = is_negative(a) ^ negate
                self._put(self.b_address, self._get(self.b_address) | (B_ZONE if negative else BA_ZONE))
                first = False
            self._decrement_b()
            if wm & WORD_MARK:
                break

    def _add_or_subtract(self, *, subtract: bool) -> None:
        """Serial true/complement add, including automatic recomplementing."""

        sign_position = self.b_address
        a = self._get(self.a_address)
        b = self._get(self.b_address)
        self._decrement_a()
        complement = is_negative(a) ^ is_negative(b) ^ subtract

        t = decimal_digit(b) + (10 - decimal_digit(a) if complement else decimal_digit(a))
        carry = t >= 10
        b = (b & ~DIGIT) | decimal_char(t)
        if complement and not b & B_ZONE:
            b |= ZONE
        self._put(self.b_address, b)
        self._decrement_b()
        self._work()

        if b & WORD_MARK:
            if complement and not carry:
                self._put(
                    sign_position,
                    WORD_MARK | ((b & ZONE) ^ A_ZONE) | decimal_char(10 - t),
                )
            if not complement and carry:
                self.overflow = True
            return

        while True:
            self._work()
            if a & WORD_MARK:
                a = WORD_MARK  # zero digit and zero zone after a short A-field
            else:
                a = self._get(self.a_address)
                self._decrement_a()
            b = self._get(self.b_address)
            t = decimal_digit(b) + (9 - decimal_digit(a) if complement else decimal_digit(a)) + carry
            carry = t >= 10
            if b & WORD_MARK and not complement:
                # Existing high-order zones participate in the zone adder.
                # Successive overflow carries therefore read A, B, BA, none.
                zones = ((a & ZONE) + (b & ZONE) + (A_ZONE if carry else 0)) & ZONE
                self._put(self.b_address, WORD_MARK | decimal_char(t) | zones)
                if carry:
                    self.overflow = True
            else:
                self._put(self.b_address, (b & WORD_MARK) | decimal_char(t))
            self._decrement_b()
            if b & WORD_MARK:
                break

        if complement and not carry:
            self._put(sign_position, self._get(sign_position) ^ A_ZONE)
            carry = True
            while sign_position != self.b_address:
                self._work()
                t = 9 - decimal_digit(self._get(sign_position)) + int(carry)
                carry = t >= 10
                self._put(
                    sign_position,
                    (self._get(sign_position) & ~DIGIT) | decimal_char(t),
                )
                sign_position -= 1

    def _multiply(self) -> None:
        """Optional @ instruction: in-place decimal partial products."""

        a_start = self.a_address
        product_units = self.b_address
        partial_units = self.b_address
        while True:
            self._work()
            a = self._get(self.a_address)
            self._put(self.b_address, ZERO)  # also clears marks in product space
            self._decrement_a()
            self._decrement_b()
            if a & WORD_MARK:
                break
        self._put(self.b_address, ZERO)
        self._decrement_b()  # low-order multiplier digit
        negative = is_negative(self._get(a_start)) ^ is_negative(self._get(self.b_address))

        while True:
            product_position = partial_units
            self.a_address = a_start
            carry = 0
            multiplier = self._get(self.b_address)
            while True:
                self._work()
                multiplicand = self._get(self.a_address)
                t = (
                    decimal_digit(multiplicand) * decimal_digit(multiplier)
                    + carry
                    + decimal_digit(self._get(product_position))
                )
                carry = t // 10
                self._put(
                    product_position,
                    (self._get(product_position) & WORD_MARK) | decimal_char(t),
                )
                self._decrement_a()
                product_position = self._decrement(product_position)
                if multiplicand & WORD_MARK:
                    break
            self._put(self.b_address, (self._get(self.b_address) & WORD_MARK) | ZERO)
            t = decimal_digit(self._get(product_position)) + carry
            self._put(
                product_position,
                (self._get(product_position) & WORD_MARK) | decimal_char(t),
            )
            partial_units -= 1
            self._decrement_b()
            if multiplier & WORD_MARK:
                break

        self._put(product_units, self._get(product_units) | ZONE)
        if negative:
            self._put(product_units, self._get(product_units) & ~A_ZONE)

    def _divide_add(self, ap: int, bp: int) -> int:
        carry = 0
        while True:
            self._work()
            a = self._get(ap)
            b = self._get(bp)
            result = decimal_digit(b) + decimal_digit(a) + carry
            carry = int(result >= 10)
            self._put(bp, (b & WORD_MARK) | decimal_char(result))
            ap -= 1
            bp -= 1
            if a & WORD_MARK:
                return carry

    def _divide_subtract(self, ap: int, bp: int) -> int:
        borrow = 0
        while True:
            self._work()
            a = self._get(ap)
            b = self._get(bp)
            result = decimal_digit(b) - decimal_digit(a) - borrow
            borrow = int(result < 0)
            self._put(bp, (b & WORD_MARK) | decimal_char(result))
            ap -= 1
            bp -= 1
            if a & WORD_MARK:
                break
        b = self._get(bp)
        if decimal_digit(b) != 0:
            result = decimal_digit(b) - borrow
            self._put(bp, (b & WORD_MARK) | decimal_char(result))
            return 0
        return borrow

    def _divide_signs(self, divisor: int, dividend: int, qp: int, rp: int) -> None:
        divisor_negative = is_negative(divisor)
        self._put(rp, self._get(rp) | ZONE)
        if divisor_negative:
            self._put(rp, self._get(rp) & ~A_ZONE)
        self._put(qp, self._get(qp) | ZONE)
        if is_negative(dividend) ^ divisor_negative:
            self._put(qp, self._get(qp) & ~A_ZONE)

    def _divide(self) -> None:
        """Optional % instruction: repeated-subtraction long division."""

        divisor_units = self.a_address
        nonzero = False
        while True:
            self._work()
            a = self._get(self.a_address)
            nonzero |= decimal_digit(a) != 0
            self._decrement_a()
            if a & WORD_MARK:
                break

        if not nonzero:
            self.overflow = True
            quotient_position = remainder_scan = self.b_address
            while True:
                self._work()
                b = self._get(remainder_scan)
                remainder_scan += 1
                self._validate_address(remainder_scan - 1, "dividend")
                if b & ZONE:
                    break
            self._validate_address(quotient_position, "quotient")
            self._divide_signs(
                self._get(divisor_units), b, quotient_position - 1, remainder_scan - 1
            )
            self.b_address = (self.b_address - 2) - (divisor_units - (self.a_address + 1))
            return

        subdividend_units = self.b_address
        quotient_position = self.b_address - (divisor_units - self.a_address) - 1
        while True:
            quotient_digit = 0
            self._validate_address(quotient_position, "quotient")
            self._validate_address(subdividend_units, "dividend")
            b = self._get(subdividend_units)
            while True:
                borrow = self._divide_subtract(divisor_units, subdividend_units)
                quotient_digit += 1
                self._work()
                if borrow:
                    break
            self._divide_add(divisor_units, subdividend_units)
            quotient_digit -= 1
            if quotient_digit > 9:
                self.overflow = True
            self._put(
                quotient_position,
                (self._get(quotient_position) & WORD_MARK) | decimal_char(quotient_digit),
            )
            subdividend_units += 1
            quotient_position += 1
            if b & ZONE:
                break

        self._divide_signs(
            self._get(divisor_units), b, quotient_position - 1, subdividend_units - 1
        )
        self.b_address = quotient_position - 2

    # ------------------------------------------------------------------
    # Data movement and logic

    def _move_characters(self, *, load: bool) -> None:
        while True:
            self._work()
            a = self._get(self.a_address)
            if load:
                wm = a
                self._put(self.b_address, a)
            else:
                wm = a | self._get(self.b_address)
                self._put(
                    self.b_address,
                    (self._get(self.b_address) & WORD_MARK) | (a & CHAR),
                )
            self._decrement_a()
            self._decrement_b()
            if wm & WORD_MARK:
                break

    def _move_numeric(self, *, zone: bool) -> None:
        mask = ZONE if zone else DIGIT
        self._put(
            self.b_address,
            (self._get(self.b_address) & ~mask) | (self._get(self.a_address) & mask),
        )
        self._decrement_a()
        self._decrement_b()

    def _move_and_suppress_zeroes(self) -> None:
        b_start = self.b_address
        suppress = True
        while True:
            a = self._get(self.a_address)
            value = self._get(self.a_address) & (CHAR if self.b_address != b_start else DIGIT)
            self._put(self.b_address, value)
            self._decrement_a()
            self._decrement_b()
            if a & WORD_MARK:
                break
        while self.b_address < b_start:
            self.b_address += 1
            value = self._get(self.b_address)
            code = value & CHAR
            if code in (ZERO, char(",")):
                if suppress:
                    self._put(self.b_address, 0)
            elif code in (0, char("-")):
                pass
            elif (code == char(".") and self.expanded_print_edit) or code <= 9:
                suppress = False
            else:
                suppress = True
        self.b_address += 1
        self._validate_address(self.b_address, "B")

    def _move_record(self) -> None:
        while True:
            a = self._get(self.a_address)
            self._put(
                self.b_address,
                (self._get(self.b_address) & WORD_MARK) | (a & CHAR),
            )
            self.a_address += 1
            self.b_address += 1
            self._validate_address(self.a_address, "A")
            self._validate_address(self.b_address, "B")
            if (a & CHAR) == RECORD_MARK or a == (GROUP_MARK | WORD_MARK):
                break

    def _compare(self, instruction_length: int) -> None:
        if instruction_length != 1:
            self.indicators[IN_EQUAL] = True
            self.indicators[IN_UNEQUAL] = False
            self.indicators[IN_HIGH] = False
            self.indicators[IN_LOW] = False
        while True:
            a = self._get(self.a_address)
            b = self._get(self.b_address)
            wm = a | b
            if (a & CHAR) != (b & CHAR):
                self.indicators[IN_EQUAL] = False
                self.indicators[IN_UNEQUAL] = True
                self.indicators[IN_HIGH] = COLLATING_RANK[b & CHAR] > COLLATING_RANK[a & CHAR]
                self.indicators[IN_LOW] = not self.indicators[IN_HIGH]
            self._decrement_a()
            self._decrement_b()
            if wm & WORD_MARK:
                break
        if a & WORD_MARK and not b & WORD_MARK:
            self.indicators[IN_EQUAL] = False
            self.indicators[IN_LOW] = False
            self.indicators[IN_UNEQUAL] = True
            self.indicators[IN_HIGH] = True
        if not self.high_low_equal:
            self.indicators[IN_EQUAL] = False
            self.indicators[IN_LOW] = False
            self.indicators[IN_HIGH] = False

    def _branch_instruction(self, length: int) -> None:
        if length == 4:
            self._branch()
            return
        if length == 5:
            d = self.d_character
            take = self._indicator_selected(d)
            if take:
                self._branch()
            if d in RESET_ON_TEST:
                self.indicators[d] = False
            return
        self._validate_address(self.b_address, "B")
        if (self._get(self.b_address) & CHAR) == self.d_character:
            self._branch()
        else:
            self._decrement_b()

    def _indicator_selected(self, d: int) -> bool:
        if d == 0:
            return True
        if d == char("9") or d == char("@"):
            return False  # Carriage channels are not modeled as timed devices.
        if IN_SENSE_B <= d <= IN_SENSE_G:
            return self.sense_switches[BCD_TO_ASCII[d]]
        if d == IN_LAST_CARD:
            return not self.cards and self.sense_switches["A"]
        if d in (IN_PRINTER_BUSY, IN_CARRIAGE_BUSY):
            return False
        return self.indicators[d]

    def _branch_word_mark_or_zone(self) -> None:
        d = self.d_character
        b = self._get(self.b_address)
        if ((d & 1) and b & WORD_MARK) or ((d & 2) and (b & ZONE) == (d & ZONE)):
            self._branch()
        else:
            self._decrement_b()

    def _clear_storage(self, length: int) -> None:
        lower = (self.b_address // 100) * 100
        self._validate_address(self.b_address, "B")
        while self.b_address >= lower:
            self._put(self.b_address, 0)
            self.b_address -= 1
        if self.b_address < 0:
            self.b_address += self.memory.size
        if length == 7:
            self._validate_address(self.a_address, "branch")
            self.i_address = self.a_address  # CS and branch preserves BSTAR.

    def _store_address_register(self) -> None:
        encoded = encode_address(self.b_address % 16000)
        for value in reversed(encoded):
            self._put(
                self.a_address,
                (self._get(self.a_address) & WORD_MARK) | value,
            )
            self._decrement_a()

    def _modify_address(self) -> None:
        a = decode_address(tuple(self._get(self.a_address - i) for i in (2, 1, 0)))
        b = decode_address(tuple(self._get(self.b_address - i) for i in (2, 1, 0)))
        self.a_address -= 3
        self.b_address -= 3
        result = (a + b) % 16000
        encoded = encode_address(result)
        high, tens, units = encoded
        self._put(self.b_address + 1, (self._get(self.b_address + 1) & WORD_MARK) | units)
        self._put(
            self.b_address + 2,
            (self._get(self.b_address + 2) & (WORD_MARK | ZONE)) | (tens & DIGIT),
        )
        self._put(self.b_address + 3, (self._get(self.b_address + 3) & WORD_MARK) | high)
        if (a % 4000) + (b % 4000) >= 4000:
            self.b_address += 2

    # ------------------------------------------------------------------
    # Move Characters and Edit (base and Expanded Print Edit scans)

    def _move_and_edit(self) -> None:
        a = self._get(self.a_address)
        t = a & DIGIT
        self._decrement_a()
        negative = is_negative(a)
        a_wm = suppress = body = False
        floating_dollar = asterisk = decimal_seen = False

        while True:
            b = self._get(self.b_address)
            self._put(self.b_address, b & ~WORD_MARK)
            code = b & CHAR
            take_a = False
            if code == char("*"):
                if body and not floating_dollar and self.expanded_print_edit:
                    asterisk = True
                    take_a = True
            elif code == char("$"):
                if body and not asterisk and self.expanded_print_edit:
                    floating_dollar = True
                    take_a = True
            elif code == ZERO:
                if a_wm:
                    if not suppress:
                        self._put(self.b_address, self._get(self.b_address) | WORD_MARK)
                    suppress = True
                else:
                    if not suppress:
                        t |= WORD_MARK
                    suppress = True
                    take_a = True
            elif code == 0:
                if not a_wm:
                    take_a = True
            elif code in (char("C"), char("R"), char("-")):
                if not negative and not body:
                    self._put(self.b_address, 0)
            elif code == char(","):
                if not body:
                    self._put(self.b_address, 0)
            elif code == char("&"):
                self._put(self.b_address, 0)

            if take_a:
                self._put(self.b_address, t)
                if a & WORD_MARK:
                    body = False
                    a_wm = True
                else:
                    body = True
                    a = self._get(self.a_address)
                    self._decrement_a()
                    t = a & CHAR
            self._decrement_b()
            if b & WORD_MARK:
                break

        if not suppress:
            return

        while True:
            self.b_address += 1
            b = self._get(self.b_address)
            code = b & CHAR
            if 1 <= code <= 9:
                suppress = False
            elif code in (ZERO, char(",")):
                if suppress and not decimal_seen:
                    self._put(self.b_address, char("*") if asterisk else 0)
            elif code == 0:
                if asterisk:
                    self._put(self.b_address, char("*"))
            elif code == char("."):
                if suppress and self.expanded_print_edit:
                    decimal_seen = True
            elif code in (char("%"), char("~"), char("\\"), char('"'), char("-")):
                pass
            else:
                suppress = True
            if b & WORD_MARK:
                break

        self._put(self.b_address, self._get(self.b_address) & ~WORD_MARK)
        if not floating_dollar and not (decimal_seen and suppress):
            self.b_address += 1
            self._validate_address(self.b_address, "B")
            return
        if decimal_seen and suppress:
            floating_dollar = False

        while True:
            b = self._get(self.b_address)
            if b == 0 and floating_dollar:
                self._put(self.b_address, char("$"))
                break
            if b == char("."):
                self._put(self.b_address, char("*") if asterisk else 0)
                break
            if b == ZERO and not floating_dollar:
                self._put(self.b_address, char("*") if asterisk else 0)
            self.b_address = self._decrement(self.b_address)

    # ------------------------------------------------------------------
    # Simple stream-oriented 1402/1403 devices

    def _io_read(self) -> None:
        if not self.cards:
            raise MachineFault("card reader empty")
        card = self.cards.popleft().rstrip("\r\n")[:80].ljust(80)
        self.memory.load_text(1, card, preserve_word_marks=True)
        self.indicators[IN_LAST_CARD] = not self.cards

    def _io_write(self) -> None:
        self.printed_lines.append(self.memory.text(201, 332))

    def _io_punch(self) -> None:
        self.punched_cards.append(self.memory.text(101, 180))
