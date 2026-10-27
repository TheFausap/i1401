"""A dependency-free, instruction-level IBM 1401 simulator."""

from .assembler import Assembler, AssemblyError, ProgramImage, assemble
from .bcd import (
    A_ZONE,
    BA_ZONE,
    B_ZONE,
    CHAR,
    DIGIT,
    WORD_MARK,
    ZONE,
    decode_address,
    encode_address,
    from_ascii,
    to_ascii,
)
from .cpu import IBM1401, Instruction, MachineFault, RunResult
from .memory import CoreMemory, MemoryError

__all__ = [
    "A_ZONE",
    "BA_ZONE",
    "B_ZONE",
    "CHAR",
    "DIGIT",
    "WORD_MARK",
    "ZONE",
    "Assembler",
    "AssemblyError",
    "CoreMemory",
    "IBM1401",
    "Instruction",
    "MachineFault",
    "MemoryError",
    "ProgramImage",
    "RunResult",
    "assemble",
    "decode_address",
    "encode_address",
    "from_ascii",
    "to_ascii",
]

__version__ = "0.1.0"
