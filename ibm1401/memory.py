"""Character-addressed IBM 1401 core storage."""

from __future__ import annotations

from collections.abc import Iterator

from .bcd import (
    BA_ZONE,
    B_ZONE,
    CHAR,
    WORD_MARK,
    ZONE,
    decimal_char,
    from_ascii,
    from_stored_byte,
    to_ascii,
    to_stored_byte,
)

MEMORY_SIZES = (1400, 2000, 4000, 8000, 12000, 16000)


class MemoryError(ValueError):
    """Raised for invalid core sizes, addresses, or field definitions."""


class CoreMemory:
    """A bytearray of BA8421 characters with independent word-mark bits.

    Array indices are the actual decimal core addresses, 0 through size-1.
    Thus the conventional card-read area 001..080 is at indices 1..80.
    """

    def __init__(self, size: int = 16000) -> None:
        if size not in MEMORY_SIZES:
            raise MemoryError(f"core size must be one of {MEMORY_SIZES}, not {size}")
        self.size = size
        self._cells = bytearray(size)

    def check_address(self, address: int) -> int:
        if not isinstance(address, int) or not 0 <= address < self.size:
            raise MemoryError(f"core address outside 0..{self.size - 1}: {address!r}")
        return address

    def __len__(self) -> int:
        return self.size

    def __getitem__(self, address: int) -> int:
        return self._cells[self.check_address(address)]

    def __setitem__(self, address: int, value: int) -> None:
        self.check_address(address)
        if not 0 <= value <= CHAR | WORD_MARK:
            raise MemoryError(f"invalid core character value: {value}")
        self._cells[address] = value

    def __iter__(self) -> Iterator[int]:
        return iter(self._cells)

    def clear(self) -> None:
        self._cells[:] = b"\0" * self.size

    def character(self, address: int) -> int:
        return self[address] & CHAR

    def word_mark(self, address: int) -> bool:
        return bool(self[address] & WORD_MARK)

    def set_word_mark(self, address: int, enabled: bool = True) -> None:
        if enabled:
            self[address] = self[address] | WORD_MARK
        else:
            self[address] = self[address] & ~WORD_MARK

    def write_character(self, address: int, value: int, *, preserve_word_mark: bool = True) -> None:
        mark = self[address] & WORD_MARK if preserve_word_mark else 0
        self[address] = mark | (value & CHAR)

    def load_text(
        self,
        address: int,
        text: str,
        *,
        word_mark: bool = False,
        preserve_word_marks: bool = True,
    ) -> int:
        """Load text from left to right and return its units (last) address.

        If ``word_mark`` is true, the high-order (first) character is marked.
        Other positions' existing marks are preserved unless
        ``preserve_word_marks`` is false, in which case all other marks are
        cleared.
        """

        values = from_ascii(text)
        for offset, value in enumerate(values):
            at = address + offset
            self.check_address(at)
            mark = self[at] & WORD_MARK if preserve_word_marks else 0
            if word_mark and offset == 0:
                mark = WORD_MARK
            self[at] = mark | value
        return address + len(values) - 1

    def load_number(
        self,
        address: int,
        value: int | str,
        *,
        width: int | None = None,
        word_mark: bool = True,
        signed_positive: bool = False,
    ) -> int:
        """Load a decimal field and return its units address.

        ``address`` is the high-order position.  A negative value receives a
        B zone in its units position.  Positive fields are unsigned unless
        ``signed_positive`` requests the canonical BA zone.
        """

        negative = isinstance(value, int) and value < 0 or isinstance(value, str) and value.startswith("-")
        digits = str(value)
        if digits.startswith(("+", "-")):
            digits = digits[1:]
        if not digits.isdigit():
            raise MemoryError(f"not a decimal field: {value!r}")
        if width is not None:
            if width < len(digits):
                raise MemoryError(f"{value!r} does not fit in {width} digits")
            digits = digits.rjust(width, "0")
        end = self.load_text(address, digits, word_mark=word_mark, preserve_word_marks=False)
        zone = B_ZONE if negative else BA_ZONE if signed_positive else 0
        self[end] = (self[end] & (CHAR | WORD_MARK)) | zone
        return end

    def text(self, start: int, stop: int | None = None) -> str:
        """Return characters in the inclusive range ``start..stop``."""

        if stop is None:
            stop = start
        if stop < start:
            raise MemoryError("memory text range must run from low to high address")
        self.check_address(start)
        self.check_address(stop)
        return to_ascii(self._cells[start : stop + 1])

    def field_bounds(self, units_address: int) -> tuple[int, int]:
        """Find a conventionally marked field from its units address."""

        self.check_address(units_address)
        for high in range(units_address, -1, -1):
            if self.word_mark(high):
                return high, units_address
        raise MemoryError(f"no word mark found at or below address {units_address}")

    def field_text(self, units_address: int) -> str:
        high, units = self.field_bounds(units_address)
        return self.text(high, units)

    def numeric_value(self, units_address: int) -> int:
        """Decode a conventional numeric field for tests and host tools."""

        from .bcd import decimal_digit, is_negative

        high, units = self.field_bounds(units_address)
        digits = [decimal_digit(self._cells[a]) for a in range(high, units + 1)]
        value = 0
        for digit in digits:
            value = value * 10 + digit
        return -value if is_negative(self._cells[units]) else value

    def dump(self, start: int, stop: int, *, mark: str = "^") -> str:
        """Render a range, prefixing word-marked characters with ``mark``."""

        self.check_address(start)
        self.check_address(stop)
        if stop < start:
            raise MemoryError("memory dump range must run from low to high address")
        return "".join((mark if self._cells[a] & WORD_MARK else "") + self.text(a) for a in range(start, stop + 1))

    def export_bytes(self) -> bytes:
        """Export C/W/BA8421 bytes with generated odd parity."""

        return bytes(to_stored_byte(v) for v in self._cells)

    def import_bytes(self, data: bytes, *, address: int = 0, validate_parity: bool = True) -> None:
        """Import C/W/BA8421 bytes, checking odd parity by default."""

        if address + len(data) > self.size:
            raise MemoryError("import extends past installed core storage")
        for offset, value in enumerate(data):
            self._cells[address + offset] = from_stored_byte(value, validate_parity=validate_parity)
