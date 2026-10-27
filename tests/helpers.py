from __future__ import annotations

from ibm1401 import IBM1401, assemble
from ibm1401.bcd import decimal_digit, is_negative


def run_source(source: str, *, cards=(), max_instructions: int = 10000):
    image = assemble(source)
    machine = IBM1401(cards=cards)
    image.load_into(machine)
    result = machine.run(max_instructions)
    return machine, image, result


def run_arithmetic(op: str, a: str, b: str):
    source = f"""
        ORG 100
START   {op} AA,BB
        H
AA      DCW {a}
BB      DCW {b}
        END START
"""
    machine, image, result = run_source(source)
    if result.fault:
        raise AssertionError(result.fault)
    return machine, image.symbols["BB"]


def signed_decimal(value: int, width: int) -> str:
    sign = "-" if value < 0 else "+"
    return sign + str(abs(value)).rjust(width, "0")


def numeric_range(machine: IBM1401, start: int, stop: int) -> int:
    value = 0
    for address in range(start, stop + 1):
        value = value * 10 + decimal_digit(machine.memory[address])
    return -value if is_negative(machine.memory[stop]) else value


def run_multiply(a: int, b: int, la: int, lm: int):
    total = la + 1 + lm
    source = f"""
        ORG 100
START   ZA BB,WORK-{la + 1}
        M AA,WORK
        H
AA      DCW {signed_decimal(a, la)}
BB      DCW {signed_decimal(b, lm)}
WORK    DCW {'0' * total}
        END START
"""
    machine, image, result = run_source(source)
    if result.fault:
        raise AssertionError(result.fault)
    return machine, image.symbols["WORK"]


def run_divide(dividend: int, divisor: int, ld: int, ls: int, prefix: int = 0):
    total = prefix + ls + 1 + ld
    source = f"""
        ORG 100
START   ZA DD,WORK
        D DV,WORK-{ld - 1}
        H
DD      DCW {signed_decimal(dividend, ld)}
DV      DCW {signed_decimal(divisor, ls)}
WORK    DCW {'0' * total}
        END START
"""
    machine, image, result = run_source(source)
    if result.fault:
        raise AssertionError(result.fault)
    work_units = image.symbols["WORK"]
    work_start = work_units - total + 1
    high_dividend = work_units - ld + 1
    quotient_start = high_dividend - ls - 1
    quotient_stop = quotient_start + ld - 1
    remainder_start = quotient_stop + 1
    return (
        machine,
        numeric_range(machine, quotient_start, quotient_stop),
        numeric_range(machine, remainder_start, work_units),
        (work_start, quotient_start, quotient_stop, remainder_start, work_units),
    )
