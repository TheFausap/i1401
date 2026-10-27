"""IBM 1401 six-bit BCD characters and three-character addresses.

A core position contains BA8421 data bits and a separate word mark.  The
check (parity) bit is derived when a position is imported or exported; it is
not stored separately by the simulator.
"""

from __future__ import annotations

from typing import Iterable, Sequence

DIGIT = 0x0F
ZONE = 0x30
CHAR = 0x3F
WORD_MARK = 0x40
A_ZONE = 0x10
B_ZONE = 0x20
BA_ZONE = 0x30

BLANK = 0x00
ZERO = 0x0A  # The 1401's zero is 8+2, not an empty digit nibble.
RECORD_MARK = 0x1A
GROUP_MARK = 0x3F

# Paul Pierce's A-chain ordering, also used by current SIMH conversions.
# Keeping the table in BCD order makes the BA8421 representation explicit.
BCD_TO_ASCII = (
    " 1234567890#@:>{^/STUVWXYZ|,%~\\"
    + chr(34)
    + "-JKLMNOPQR!$*];_&ABCDEFGHI?.)[<}"
)
assert len(BCD_TO_ASCII) == 64

ASCII_TO_BCD = {c: i for i, c in enumerate(BCD_TO_ASCII)}
ASCII_TO_BCD.update({c.lower(): i for c, i in list(ASCII_TO_BCD.items()) if c.isalpha()})
# Common H-chain and manual notation aliases.
ASCII_TO_BCD.update(
    {
        "=": 0x0B,
        "'": 0x0C,
        "(": 0x1C,
        "+": 0x30,
        "‡": RECORD_MARK,
        "⌑": 0x3D,
        "¤": 0x3D,
    }
)

# Numeric nibbles used by addresses and by the decimal adder.  Blanks and
# zero both have numeric value zero.  Values 11..15 have the adder's normal
# aliases but are not legal in an unindexed address character.
DIGIT_TO_INT = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0, 3, 4, 5, 6, 7)
INT_TO_DIGIT = (10, 1, 2, 3, 4, 5, 6, 7, 8, 9)


class BCDError(ValueError):
    """Raised when host text cannot be represented in 1401 BCD."""


def from_ascii(text: str) -> list[int]:
    """Convert host text to six-bit BCD values (without word marks)."""

    try:
        return [ASCII_TO_BCD[c] for c in text]
    except KeyError as exc:
        raise BCDError(f"character {exc.args[0]!r} has no IBM 1401 BCD encoding") from exc


def to_ascii(values: Iterable[int]) -> str:
    """Convert BCD values to host text, ignoring word-mark bits."""

    return "".join(BCD_TO_ASCII[v & CHAR] for v in values)


def char(value: str) -> int:
    """Return the BCD value of one host character."""

    if len(value) != 1:
        raise BCDError(f"expected one character, got {value!r}")
    return from_ascii(value)[0]


def decimal_digit(value: int) -> int:
    """Return the adder's numeric value for a BA8421 character."""

    return DIGIT_TO_INT[value & DIGIT]


def decimal_char(value: int) -> int:
    """Encode a decimal residue (0..9) as a BCD numeric character."""

    return INT_TO_DIGIT[value % 10]


def check_bit(value: int) -> int:
    """Return the odd-parity C bit for a character and its word mark."""

    return 1 if ((value & (CHAR | WORD_MARK)).bit_count() & 1) == 0 else 0


def to_stored_byte(value: int) -> int:
    """Encode C, word mark, and BA8421 in one host byte.

    Bits 7, 6, and 5..0 are C, W, and BA8421 respectively.  This is a
    convenient file representation, not a claim about physical core wiring.
    """

    value &= CHAR | WORD_MARK
    return (check_bit(value) << 7) | value


def from_stored_byte(value: int, *, validate_parity: bool = True) -> int:
    """Decode a host byte produced by :func:`to_stored_byte`."""

    if not 0 <= value <= 0xFF:
        raise BCDError(f"stored byte out of range: {value}")
    data = value & (CHAR | WORD_MARK)
    if validate_parity and (value >> 7) != check_bit(data):
        raise BCDError(f"odd-parity check failed for stored byte 0x{value:02x}")
    return data


def _address_digit(value: int, position: str) -> int:
    nibble = value & DIGIT
    if nibble == 0 or nibble > 10:
        raise BCDError(f"invalid {position} address character {BCD_TO_ASCII[value & CHAR]!r}")
    return DIGIT_TO_INT[nibble]


def decode_address(values: Sequence[int]) -> int:
    """Decode three BA8421 characters to a decimal core address.

    Zone bits in the high-order and units characters encode four binary
    thousands bits.  Zone bits in the middle character are ignored here;
    the CPU uses those separately to select an index register.
    """

    if len(values) != 3:
        raise BCDError("a 1401 address contains exactly three characters")
    hundreds = _address_digit(values[0], "hundreds")
    tens = _address_digit(values[1], "tens")
    units = _address_digit(values[2], "units")
    thousands = ((values[0] & ZONE) >> 4) | (((values[2] & ZONE) >> 4) << 2)
    return thousands * 1000 + hundreds * 100 + tens * 10 + units


def encode_address(address: int) -> tuple[int, int, int]:
    """Encode a decimal core address in the 1401's three-character form."""

    if not 0 <= address <= 15999:
        raise BCDError(f"address outside the 1401 address range: {address}")
    thousands, remainder = divmod(address, 1000)
    hundreds, remainder = divmod(remainder, 100)
    tens, units = divmod(remainder, 10)
    return (
        decimal_char(hundreds) | ((thousands & 0b0011) << 4),
        decimal_char(tens),
        decimal_char(units) | (((thousands >> 2) & 0b0011) << 4),
    )


def is_negative(value: int) -> bool:
    """A B zone without A is negative; every other units zone is positive."""

    return (value & ZONE) == B_ZONE


def normalized_zone(negative: bool) -> int:
    """Return the canonical result sign: B for minus, BA for plus."""

    return B_ZONE if negative else BA_ZONE
