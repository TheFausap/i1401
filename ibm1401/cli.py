"""Command-line interface for assembling and running IBM 1401 programs."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from . import __version__
from .assembler import AssemblyError, assemble
from .bcd import BCDError
from .cpu import IBM1401
from .memory import MemoryError


def _memory_size(value: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("memory size must be a decimal number") from exc


def _dump_range(value: str) -> tuple[int, int]:
    try:
        if ":" in value:
            start, stop = value.split(":", 1)
        elif "-" in value:
            start, stop = value.split("-", 1)
        else:
            start = stop = value
        return int(start), int(stop)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("dump range must be START:STOP") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ibm1401",
        description="Instruction-level IBM 1401 simulator with signed decimal arithmetic.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--memory-size",
        type=_memory_size,
        default=16000,
        choices=(1400, 2000, 4000, 8000, 12000, 16000),
        help="installed core characters (default: 16000)",
    )

    listing = sub.add_parser("assemble", parents=[common], help="assemble source and print a listing")
    listing.add_argument("source", type=Path)
    listing.add_argument("-o", "--output", type=Path, help="write the listing to a file")

    run = sub.add_parser("run", parents=[common], help="assemble and execute a program")
    run.add_argument("source", type=Path)
    run.add_argument(
        "--cards",
        type=Path,
        action="append",
        default=[],
        help="card-image text file; one 80-column card per line (repeatable)",
    )
    run.add_argument("--punch", type=Path, help="write punched 80-column card images")
    run.add_argument("--trace", action="store_true", help="trace instructions to stderr")
    run.add_argument("--listing", action="store_true", help="print the assembly listing to stderr")
    run.add_argument("--max-instructions", type=int, default=1_000_000)
    run.add_argument("--dump", type=_dump_range, metavar="START:STOP", help="dump core after execution")
    run.add_argument("--no-multiply-divide", action="store_true", help="remove the optional M/D feature")
    run.add_argument("--no-expanded-edit", action="store_true", help="remove Expanded Print Edit")
    return parser


def _read_cards(paths: list[Path]) -> list[str]:
    cards: list[str] = []
    for path in paths:
        cards.extend(path.read_text(encoding="utf-8").splitlines())
    return cards


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source = args.source.read_text(encoding="utf-8")
        image = assemble(source, memory_size=args.memory_size)
        if args.command == "assemble":
            text = image.listing() + "\n"
            if args.output:
                args.output.write_text(text, encoding="utf-8")
            else:
                sys.stdout.write(text)
            return 0

        if args.listing:
            print(image.listing(), file=sys.stderr)
        machine = IBM1401(
            args.memory_size,
            multiply_divide=not args.no_multiply_divide,
            expanded_print_edit=not args.no_expanded_edit,
            cards=_read_cards(args.cards),
        )
        image.load_into(machine)
        if args.trace:
            def trace(ins) -> None:
                print(
                    f"{ins.address:05d} {ins.text:<8} {ins.mnemonic:<4} "
                    f"I={machine.i_address:05d} A={machine.a_address:05d} "
                    f"B={machine.b_address:05d} OVF={int(machine.overflow)}",
                    file=sys.stderr,
                )

            machine.trace = trace
        result = machine.run(args.max_instructions)
        for line in machine.printed_lines:
            print(line.rstrip())
        if args.punch:
            args.punch.write_text(
                "".join(card + "\n" for card in machine.punched_cards), encoding="utf-8"
            )
        if args.dump:
            start, stop = args.dump
            print(f"CORE {start:05d}:{stop:05d} (^ = word mark)")
            print(machine.memory.dump(start, stop))
        if result.reason == "fault":
            print(f"processor fault: {result.fault}", file=sys.stderr)
            return 1
        if result.reason == "limit":
            print(f"instruction limit ({args.max_instructions}) reached", file=sys.stderr)
            return 2
        print(
            f"halted after {result.instructions} instructions; "
            f"{len(machine.printed_lines)} lines, {len(machine.punched_cards)} cards",
            file=sys.stderr,
        )
        return 0
    except (OSError, AssemblyError, BCDError, MemoryError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
