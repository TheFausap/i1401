"""A compact Autocoder-style assembler for the simulator's core instruction set.

This is intentionally not a replacement for historical Tape Autocoder.  It
supports the free-form statements needed to write ordinary CPU programs:
ORG, EQU, DC/DCW, DS, DSA, literals, instructions, and END.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import TYPE_CHECKING, Iterable

from .bcd import BA_ZONE, B_ZONE, CHAR, WORD_MARK, ZONE, char, encode_address, from_ascii, to_ascii
from .cpu import (
    OP_A,
    OP_B,
    OP_BBE,
    OP_BWZ,
    OP_C,
    OP_CC,
    OP_CS,
    OP_CWM,
    OP_DIV,
    OP_HALT,
    OP_LCA,
    OP_MA,
    OP_MCE,
    OP_MCM,
    OP_MCS,
    OP_MCW,
    OP_MN,
    OP_MUL,
    OP_MZ,
    OP_NOP,
    OP_P,
    OP_R,
    OP_RP,
    OP_S,
    OP_SAR,
    OP_SBR,
    OP_SPF,
    OP_SRF,
    OP_SS,
    OP_SWM,
    OP_W,
    OP_WP,
    OP_WR,
    OP_WRP,
    OP_ZA,
    OP_ZS,
)
from .memory import MEMORY_SIZES

if TYPE_CHECKING:
    from .cpu import IBM1401


class AssemblyError(ValueError):
    """A source error with a line number and useful context."""


@dataclass
class Statement:
    line_number: int
    source: str
    label: str | None
    opcode: str
    operands: tuple[str, ...]
    location: int = 0
    length: int = 0


@dataclass
class ListingEntry:
    address: int
    values: tuple[int, ...]
    source: str


@dataclass
class ProgramImage:
    cells: bytearray
    entry: int
    symbols: dict[str, int]
    listing_entries: list[ListingEntry] = field(default_factory=list)

    @property
    def memory_size(self) -> int:
        return len(self.cells)

    def load_into(self, machine: "IBM1401", *, clear: bool = True) -> None:
        if machine.memory.size != self.memory_size:
            raise ValueError(
                f"program image has {self.memory_size} characters; machine has {machine.memory.size}"
            )
        if clear:
            machine.memory.clear()
        for address, value in enumerate(self.cells):
            if value:
                machine.memory[address] = value
        machine.i_address = self.entry
        machine.a_address = machine.b_address = -1
        machine.d_character = 0
        machine.halted = False
        machine.fault = None
        machine.halt_branch_pending = False
        machine.instruction_count = 0
        machine.last_instruction = None

    def listing(self) -> str:
        lines = []
        for entry in self.listing_entries:
            raw = "".join(
                ("^" if value & WORD_MARK else "") + to_ascii((value,))
                for value in entry.values
            )
            lines.append(f"{entry.address:05d}  {raw:<20}  {entry.source}")
        lines.append(f"ENTRY {self.entry:05d}")
        return "\n".join(lines)


OPCODES = {
    "R": OP_R,
    "W": OP_W,
    "WR": OP_WR,
    "P": OP_P,
    "RP": OP_RP,
    "WP": OP_WP,
    "WRP": OP_WRP,
    "SRF": OP_SRF,
    "SPF": OP_SPF,
    "MA": OP_MA,
    "M": OP_MUL,
    "CS": OP_CS,
    "S": OP_S,
    "BWZ": OP_BWZ,
    "BBE": OP_BBE,
    "MZ": OP_MZ,
    "MLZS": OP_MZ,
    "MCS": OP_MCS,
    "SW": OP_SWM,
    "D": OP_DIV,
    "SS": OP_SS,
    "LCA": OP_LCA,
    "MCW": OP_MCW,
    "MLC": OP_MCW,
    "MLCWA": OP_LCA,
    "NOP": OP_NOP,
    "MCM": OP_MCM,
    "MRCM": OP_MCM,
    "SAR": OP_SAR,
    "ZS": OP_ZS,
    "A": OP_A,
    "B": OP_B,
    "C": OP_C,
    "MN": OP_MN,
    "MLNS": OP_MN,
    "MCE": OP_MCE,
    "CC": OP_CC,
    "SBR": OP_SBR,
    "ZA": OP_ZA,
    "H": OP_HALT,
    "CW": OP_CWM,
}

BRANCH_MODIFIERS = {
    "BAV": "Z",
    "BC9": "9",
    "BCV": "@",
    "BE": "S",
    "BEF": "K",
    "BER": "L",
    "BH": "U",
    "BL": "T",
    "BLC": "A",
    "BPB": "P",
    "BPCB": "R",
    "BU": "/",
}

DIRECTIVES = {"ORG", "EQU", "DC", "DCW", "DS", "DSA", "END", "JOB", "CTL", "LTORG"}
KNOWN_WORDS = set(OPCODES) | set(BRANCH_MODIFIERS) | DIRECTIVES | {
    "BIN",
    "BSS",
    "BCE",
    "BW",
    "BM",
    "CCB",
}
TWO_ADDRESS_OPS = {
    "A",
    "S",
    "C",
    "D",
    "M",
    "ZA",
    "ZS",
    "MCW",
    "MLC",
    "LCA",
    "MLCWA",
    "MN",
    "MLNS",
    "MZ",
    "MLZS",
    "MCS",
    "MCE",
    "MCM",
    "MRCM",
    "MA",
    "CS",
    "SW",
    "CW",
}


def _strip_comment(line: str) -> str:
    in_literal = False
    for i, c in enumerate(line):
        if c == "@":
            in_literal = not in_literal
        elif c == "*" and not in_literal and (i == 0 or line[i - 1].isspace()):
            return line[:i]
    return line


def _words(line: str) -> list[tuple[str, int, int]]:
    result = []
    start = None
    in_literal = False
    for i, c in enumerate(line + " "):
        if c == "@":
            in_literal = not in_literal
        if c.isspace() and not in_literal:
            if start is not None:
                result.append((line[start:i], start, i))
                start = None
        elif start is None:
            start = i
    return result


def _split_operands(text: str) -> tuple[str, ...]:
    if not text.strip():
        return ()
    parts = []
    start = 0
    in_literal = False
    for i, c in enumerate(text):
        if c == "@":
            in_literal = not in_literal
        elif c == "," and not in_literal:
            parts.append(text[start:i].strip())
            start = i + 1
    parts.append(text[start:].strip())
    if any(not part for part in parts):
        raise ValueError("empty operand")
    return tuple(parts)


def _parse_line(line: str, number: int) -> Statement | None:
    original = line.rstrip()
    line = _strip_comment(original).strip()
    if not line:
        return None
    words = _words(line)
    if not words:
        return None
    first = words[0][0].upper()
    label = None
    if first in KNOWN_WORDS:
        op_word = words[0]
    else:
        if len(words) < 2:
            raise AssemblyError(f"line {number}: expected an operation after label {words[0][0]!r}")
        label = first
        op_word = words[1]
    op = op_word[0].upper()
    if op not in KNOWN_WORDS:
        raise AssemblyError(f"line {number}: unknown operation {op!r}")
    operand_text = line[op_word[2] :].strip()
    try:
        operands = _split_operands(operand_text)
    except ValueError as exc:
        raise AssemblyError(f"line {number}: {exc}") from exc
    return Statement(number, original, label, op, operands)


def _literal_key(token: str) -> tuple[str, str] | None:
    token = token.strip()
    if len(token) >= 2 and token.startswith("@") and token.endswith("@"):
        return "text", token[1:-1]
    if len(token) >= 2 and token.startswith("&") and re.fullmatch(r"&[+-]?\d+", token):
        return "number", token[1:]
    return None


def _constant_values(token: str) -> list[int]:
    token = token.strip()
    key = _literal_key(token)
    if key and key[0] == "text":
        return from_ascii(key[1])
    if token.startswith("#") and token[1:].isdigit():
        length = int(token[1:])
        if length <= 0:
            raise ValueError("blank constant length must be positive")
        return [0] * length
    numeric = token
    if key and key[0] == "number":
        numeric = key[1]
    if re.fullmatch(r"[+-]?\d+", numeric):
        negative = numeric.startswith("-")
        explicit_plus = numeric.startswith("+")
        digits = numeric.lstrip("+-")
        values = from_ascii(digits)
        if negative or explicit_plus:
            values[-1] |= B_ZONE if negative else BA_ZONE
        return values
    raise ValueError(f"expected @text@, #length, or a signed decimal constant, got {token!r}")


def _instruction_length(statement: Statement) -> int:
    op = statement.opcode
    count = len(statement.operands)
    if op in TWO_ADDRESS_OPS:
        if count <= 2:
            return (1, 4, 7)[count]
        if count == 3 and op not in {"CS", "SW", "CW", "MA", "MCM", "MRCM"}:
            return 8
        raise ValueError(f"{op} takes zero, one, or two addresses" + (" and a d-character" if count == 3 else ""))
    if op in {"R", "W", "WR", "P", "WP", "WRP", "RP"}:
        if count == 0:
            return 1
        if count == 1:
            return 4
        if count == 2 and op != "RP":
            return 5
        raise ValueError(f"invalid {op} operands")
    if op in {"SRF", "SPF"}:
        if count:
            raise ValueError(f"{op} takes no operands")
        return 1
    if op in {"SS", "CC"}:
        return {1: 2, 2: 5}.get(count, 0)
    if op == "CCB":
        return 5 if count == 2 else 0
    if op in {"SAR", "SBR"}:
        return {0: 1, 1: 4}.get(count, 0)
    if op in {"NOP", "H"}:
        return {0: 1, 1: 4, 2: 5}.get(count, 0)
    if op == "B":
        return {0: 1, 1: 4, 2: 5, 3: 8}.get(count, 0)
    if op in BRANCH_MODIFIERS or op in {"BIN", "BSS"}:
        return 5 if count == (2 if op in {"BIN", "BSS"} else 1) else 0
    if op in {"BWZ", "BBE", "BCE"}:
        return {0: 1, 3: 8}.get(count, 0)
    if op in {"BW", "BM"}:
        return {0: 1, 2: 8}.get(count, 0)
    return 0


def _address_operand_positions(statement: Statement) -> set[int]:
    op = statement.opcode
    if op in TWO_ADDRESS_OPS:
        return set(range(min(len(statement.operands), 2)))
    if op in {"R", "W", "WR", "P", "WP", "WRP", "RP", "CC", "CCB"}:
        return {0} if statement.operands else set()
    if op in {"SAR", "SBR", "B"}:
        return {0} if statement.operands else set()
    if op in BRANCH_MODIFIERS or op in {"BIN", "BSS"}:
        return {0}
    if op in {"BWZ", "BBE", "BCE", "BW", "BM"}:
        return set(range(min(len(statement.operands), 2)))
    return set()


def _mark_opcode(values: list[int]) -> list[int]:
    values[0] |= WORD_MARK
    return values


class Assembler:
    def __init__(self, memory_size: int = 16000) -> None:
        if memory_size not in MEMORY_SIZES:
            raise ValueError(f"invalid core size {memory_size}")
        self.memory_size = memory_size
        self.symbols: dict[str, int] = {}
        self.literals: dict[tuple[str, str], int] = {}
        self.literal_order: list[tuple[str, str]] = []
        self.statements: list[Statement] = []

    def _error(self, statement: Statement, message: str) -> AssemblyError:
        return AssemblyError(f"line {statement.line_number}: {message}: {statement.source.strip()}")

    def _eval(self, token: str, statement: Statement) -> int:
        token = token.strip()
        literal = _literal_key(token)
        if literal:
            if literal not in self.literals:
                raise self._error(statement, f"literal {token} is not valid in this context")
            return self.literals[literal]
        match = re.fullmatch(
            r"(?:(?P<base>[A-Z_][A-Z0-9_]*|\*|\d+)(?P<offset>[+-]\d+)?|(?P<signed>[+-]\d+))",
            token.upper(),
        )
        if not match:
            raise self._error(statement, f"invalid address expression {token!r}")
        if match.group("signed") is not None:
            return int(match.group("signed"))
        base_text = match.group("base")
        if base_text == "*":
            base = statement.location
        elif base_text.isdigit():
            base = int(base_text)
        elif base_text in self.symbols:
            base = self.symbols[base_text]
        else:
            raise self._error(statement, f"undefined symbol {base_text}")
        return base + int(match.group("offset") or 0)

    def _collect_literals(self, statement: Statement) -> None:
        for position in _address_operand_positions(statement):
            key = _literal_key(statement.operands[position])
            if key and key not in self.literals:
                self.literals[key] = -1
                self.literal_order.append(key)

    def assemble(self, source: str | Iterable[str]) -> ProgramImage:
        lines = source.splitlines() if isinstance(source, str) else list(source)
        self.statements = []
        self.symbols = {}
        self.literals = {}
        self.literal_order = []
        location = 0
        entry: int | None = None
        first_instruction: int | None = None

        for number, line in enumerate(lines, 1):
            statement = _parse_line(line, number)
            if statement is None:
                continue
            self.statements.append(statement)
            op = statement.opcode
            if op in {"JOB", "CTL", "LTORG"}:
                continue
            if op == "ORG":
                if len(statement.operands) != 1:
                    raise self._error(statement, "ORG takes one address")
                location = self._eval(statement.operands[0], statement)
                statement.location = location
                continue
            if op == "EQU":
                if not statement.label or len(statement.operands) != 1:
                    raise self._error(statement, "EQU requires a label and one expression")
                self.symbols[statement.label] = self._eval(statement.operands[0], statement)
                continue
            if op == "END":
                if len(statement.operands) > 1:
                    raise self._error(statement, "END takes at most one entry address")
                if statement.operands:
                    entry = self._eval(statement.operands[0], statement)
                continue

            statement.location = location
            if op in {"DC", "DCW", "DSA"}:
                if len(statement.operands) != 1:
                    raise self._error(statement, f"{op} takes one constant")
                try:
                    if op == "DSA":
                        address = self._eval(statement.operands[0], statement)
                        if not 0 <= address <= 15999:
                            raise ValueError("DSA address outside 0..15999")
                        length = 3
                    else:
                        length = len(_constant_values(statement.operands[0]))
                except ValueError as exc:
                    raise self._error(statement, str(exc)) from exc
                statement.length = length
                if statement.label:
                    self.symbols[statement.label] = location + length - 1
            elif op == "DS":
                if len(statement.operands) != 1:
                    raise self._error(statement, "DS takes one length")
                statement.length = self._eval(statement.operands[0], statement)
                if statement.length <= 0:
                    raise self._error(statement, "DS length must be positive")
                if statement.label:
                    self.symbols[statement.label] = location
            else:
                try:
                    statement.length = _instruction_length(statement)
                except ValueError as exc:
                    raise self._error(statement, str(exc)) from exc
                if statement.length == 0:
                    raise self._error(statement, f"invalid operands for {op}")
                if statement.label:
                    self.symbols[statement.label] = location
                if first_instruction is None:
                    first_instruction = location
                self._collect_literals(statement)
            if location + statement.length > self.memory_size:
                raise self._error(statement, "statement extends past installed core")
            location += statement.length

        # Literals form a word-marked pool after all explicit statements.
        for key in self.literal_order:
            token = "@" + key[1] + "@" if key[0] == "text" else key[1]
            length = len(_constant_values(token))
            self.literals[key] = location + length - 1
            location += length
            if location > self.memory_size:
                raise AssemblyError("literal pool extends past installed core")

        cells = bytearray(self.memory_size)
        listing: list[ListingEntry] = []
        for statement in self.statements:
            if not statement.length:
                continue
            at = statement.location
            op = statement.opcode
            try:
                if op in {"DC", "DCW"}:
                    values = _constant_values(statement.operands[0])
                    if op == "DCW":
                        values[0] |= WORD_MARK
                elif op == "DSA":
                    values = list(encode_address(self._eval(statement.operands[0], statement)))
                    values[0] |= WORD_MARK
                elif op == "DS":
                    values = [0] * statement.length
                else:
                    values = self._emit_instruction(statement)
                for offset, value in enumerate(values):
                    cells[at + offset] = value
                listing.append(ListingEntry(at, tuple(values), statement.source))
            except (ValueError, IndexError) as exc:
                if isinstance(exc, AssemblyError):
                    raise
                raise self._error(statement, str(exc)) from exc

        for key in self.literal_order:
            token = "@" + key[1] + "@" if key[0] == "text" else key[1]
            values = _constant_values(token)
            values[0] |= WORD_MARK
            start = self.literals[key] - len(values) + 1
            for offset, value in enumerate(values):
                cells[start + offset] = value
            listing.append(ListingEntry(start, tuple(values), f"* literal {token}"))

        # Supply the required terminating word mark after a final instruction
        # when no following marked data or literal already supplies it.
        if location < self.memory_size and cells[location] == 0:
            cells[location] = WORD_MARK

        return ProgramImage(
            cells,
            entry if entry is not None else first_instruction if first_instruction is not None else 0,
            dict(self.symbols),
            listing,
        )

    def _encode_address(self, token: str, statement: Statement) -> list[int]:
        index = 0
        match = re.search(r"&X([123])$", token.upper())
        if match:
            index = int(match.group(1))
            token = token[: match.start()]
        address = self._eval(token, statement)
        if not 0 <= address <= 15999:
            raise self._error(statement, f"address outside 0..15999: {address}")
        values = list(encode_address(address))
        values[1] |= index << 4
        return values

    def _decode_d(self, token: str, statement: Statement) -> int:
        literal = _literal_key(token)
        if literal and literal[0] == "text" and len(literal[1]) == 1:
            return char(literal[1])
        if len(token) == 1:
            return char(token)
        raise self._error(statement, f"d-character must be one character, got {token!r}")

    def _emit_instruction(self, statement: Statement) -> list[int]:
        op = statement.opcode
        operands = statement.operands
        if op in BRANCH_MODIFIERS:
            return _mark_opcode(
                [char("B")]
                + self._encode_address(operands[0], statement)
                + [char(BRANCH_MODIFIERS[op])]
            )
        if op in {"BIN", "BSS"}:
            return _mark_opcode(
                [char("B")]
                + self._encode_address(operands[0], statement)
                + [self._decode_d(operands[1], statement)]
            )
        if op in {"BW", "BM"}:
            if not operands:
                return _mark_opcode([char("V")])
            modifier = "1" if op == "BW" else "K"
            return _mark_opcode(
                [char("V")]
                + self._encode_address(operands[0], statement)
                + self._encode_address(operands[1], statement)
                + [char(modifier)]
            )
        if op in {"BWZ", "BBE", "BCE"}:
            opcode = char("V") if op == "BWZ" else char("W") if op == "BBE" else char("B")
            if not operands:
                return _mark_opcode([opcode])
            return _mark_opcode(
                [opcode]
                + self._encode_address(operands[0], statement)
                + self._encode_address(operands[1], statement)
                + [self._decode_d(operands[2], statement)]
            )
        if op == "CCB":
            return _mark_opcode(
                [char("F")]
                + self._encode_address(operands[0], statement)
                + [self._decode_d(operands[1], statement)]
            )

        values = [OPCODES[op]]
        if op in TWO_ADDRESS_OPS:
            for operand in operands[:2]:
                values.extend(self._encode_address(operand, statement))
            if len(operands) == 3:
                values.append(self._decode_d(operands[2], statement))
        elif op in {"R", "W", "WR", "P", "RP", "WP", "WRP"}:
            if operands:
                values.extend(self._encode_address(operands[0], statement))
            if len(operands) == 2:
                values.append(self._decode_d(operands[1], statement))
        elif op in {"SS", "CC"}:
            if len(operands) == 2:
                values.extend(self._encode_address(operands[0], statement))
                values.append(self._decode_d(operands[1], statement))
            else:
                values.append(self._decode_d(operands[0], statement))
        elif op in {"SAR", "SBR", "B", "NOP", "H"}:
            if operands:
                values.extend(self._encode_address(operands[0], statement))
            if len(operands) >= 2:
                if op == "B" and len(operands) == 3:
                    values.extend(self._encode_address(operands[1], statement))
                    values.append(self._decode_d(operands[2], statement))
                else:
                    values.append(self._decode_d(operands[1], statement))
        if len(values) != statement.length:
            raise self._error(
                statement,
                f"internal assembly length mismatch ({len(values)} != {statement.length})",
            )
        values[0] |= WORD_MARK
        return values


def assemble(source: str | Iterable[str], *, memory_size: int = 16000) -> ProgramImage:
    """Assemble source text into a loadable :class:`ProgramImage`."""

    return Assembler(memory_size).assemble(source)
