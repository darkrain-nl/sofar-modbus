#!/usr/bin/env python3

"""Query a Sofar inverter and print every value."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
from contextlib import redirect_stdout

from modbus_connection import ModbusError
from modbus_connection.cli_helper import (
    add_connection_args,
    connect_from_args,
    print_component,
)
from modbus_connection.model import Component

from sofar_modbus import (
    SofarComponentBase,
    SofarInverter,
    SofarLegacyInverter,
    matches,
)
from sofar_modbus.modern import BatteryPack, async_detect_type
from sofar_modbus.tuning import LinkStats, TimedUnit

# An inverter's RS-485 line, direct or through a socket:// device, and
# the gateways answering Modbus TCP themselves. No ASCII: the library
# does not support it. The tcp framings are deprecated spellings.
CONNECTIONS = (("tcp", "rtu"), ("tcp", "socket"), ("serial", "rtu"))

# The most registers one Modbus read may ask for.
MAX_COUNT = 125
# The tower's selection register takes groups and packs 0 to 15.
MAX_INDEX = 16

Inverter = SofarInverter | SofarLegacyInverter
RegisterRead = tuple[int, int, list[int] | str]

EXAMPLES = """examples:
  # a gateway answering Modbus TCP: pass no framing (502 is the default)
  uv run script/query.py 192.168.1.50 --port 502 --unit 1
  # a box forwarding the RTU frames over TCP
  uv run script/query.py socket://192.168.1.50:8899 --transport serial --unit 1
  # a USB or serial adapter, on an older-generation inverter
  uv run script/query.py /dev/ttyUSB0 --transport serial --unit 1 --legacy
  # every register read, plus ranges the library does not model
  uv run script/query.py 192.168.1.50 --raw --registers 0x1480:40 --registers 0x2004
  # a hybrid with a BTS tower, every pack included
  uv run script/query.py 192.168.1.50 --packs
"""


def _timings(stats: LinkStats) -> str:
    """The poll's latency, for judging a timeout against the link."""
    if stats.median is None or stats.p95 is None or stats.slowest is None:
        return "nothing answered"
    return (
        f"median {stats.median * 1000:.0f} ms, "
        f"p95 {stats.p95 * 1000:.0f} ms, "
        f"slowest {stats.slowest * 1000:.0f} ms"
    )


def _register_range(text: str) -> tuple[int, int]:
    """Parse ``ADDR[:COUNT]``, each decimal or 0x-prefixed."""
    address, _, count = text.partition(":")
    try:
        start, length = int(address, 0), int(count or "1", 0)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not ADDR[:COUNT]") from None
    if not 1 <= length <= MAX_COUNT or not 0 <= start <= 0x10000 - length:
        raise argparse.ArgumentTypeError(
            f"{text!r} must read 1 to {MAX_COUNT} registers ending by 0xFFFF"
        )
    return start, length


def _line(label: str, value: object) -> None:
    print(f"{label:<16}{value}")


def _yes_no(flag: bool) -> str:
    return "yes" if flag else "no"


def served_components(inverter: Inverter) -> list[tuple[str, Component]]:
    """The components this inverter polls, plus the two setup reads."""
    inverter_type = inverter.inverter_type
    assert inverter_type is not None  # the update below set the inverter up
    if isinstance(inverter, SofarInverter):
        # The model decides these, so asking it beats deriving them.
        names = (
            "identity",
            "rating",
            *inverter.readings_components,
            *inverter.settings_components,
        )
        return [(name, getattr(inverter, name)) for name in names]
    return [
        (name, component)
        for name, component in vars(inverter).items()
        if isinstance(component, SofarComponentBase)
        and matches(inverter_type, component.applies_to)
    ]


async def _mask_type(unit: TimedUnit) -> str:
    """The type the masks alone declare, to compare with the serial's."""
    try:
        detected = await async_detect_type(unit)
    except ModbusError as err:
        return f"unreadable: {str(err) or type(err).__name__}"
    return "no usable mask" if detected is None else str(detected.name)


async def _read_registers(
    unit: TimedUnit, ranges: list[tuple[int, int]]
) -> list[RegisterRead]:
    """Each holding range's values, or why it could not be read."""
    reads: list[RegisterRead] = []
    for start, count in ranges:
        try:
            values: list[int] | str = await unit.read_holding_registers(start, count)
        except ModbusError as err:
            values = str(err) or type(err).__name__
        reads.append((start, count, values))
    return reads


async def _read_pack(
    inverter: SofarInverter, group_nr: int, pack_nr: int
) -> tuple[str, BatteryPack | None]:
    """One pack as printed text, and the pack if it answered."""
    text = io.StringIO()
    title = f"battery_pack group {group_nr} pack {pack_nr}"
    try:
        pack = await inverter.async_read_pack(pack_nr, group_nr)
    except ModbusError as err:
        text.write(f"{title}\n{'-' * len(title)}\n")
        text.write(f"  {str(err) or type(err).__name__}\n")
        return text.getvalue(), None
    with redirect_stdout(text):
        print_component(pack, title=title)
    # A tower can ignore the selection and keep serving another pack.
    if pack.pack_id is not None and pack.pack_id & 0x0FFF != group_nr << 8 | pack_nr:
        text.write(
            f"  the tower still serves group {pack.pack_id >> 8 & 0xF} "
            f"pack {pack.pack_id & 0xFF}\n"
        )
    return text.getvalue(), pack


async def _read_packs(inverter: SofarInverter) -> list[str]:
    """Every pack of every group, taken before the link closes."""
    text, first = await _read_pack(inverter, 0, 0)
    texts = [text]
    if first is None:
        return texts
    groups = min(first.parallel_group_count or 1, MAX_INDEX)
    per_group = min(first.packs_per_group or 1, MAX_INDEX)
    for group_nr in range(groups):
        for pack_nr in range(per_group):
            if group_nr or pack_nr:
                texts.append((await _read_pack(inverter, group_nr, pack_nr))[0])
    return texts


def _print_verdicts(inverter: SofarInverter, mask_type: str) -> None:
    """What the library concluded, which decides the entities Core makes."""
    strings = ", ".join(map(str, sorted(inverter.wired_battery_strings)))
    _line("Mask type", mask_type)
    _line("Unrecognized", _yes_no(inverter.unrecognized))
    _line("Battery tower", _yes_no(inverter.has_battery_tower))
    _line("Battery strings", strings or "none")
    _line("Set time", _yes_no(inverter.supports_set_time))
    _line("IV curve scan", _yes_no(inverter.supports_iv_curve_scan))


def _print_masks(masks: dict[int, int]) -> None:
    print("\nAddress masks")
    if not masks:
        print("  none answered")
    for base, mask in masks.items():
        print(f"  0x{base:04X}  0x{mask:016X}")


def _print_registers(reads: list[RegisterRead]) -> None:
    for start, count, values in reads:
        print(f"\nRegisters 0x{start:04X}-0x{start + count - 1:04X}")
        if isinstance(values, str):
            print(f"  {values}")
            continue
        for offset, value in enumerate(values):
            print(f"  0x{start + offset:04X}  0x{value:04X}  {value}")


async def main() -> int:
    """Read one inverter and print it."""
    # The backend logs a failed connect at ERROR with its traceback; the
    # messages below say it in one line.
    logging.getLogger().addHandler(logging.NullHandler())

    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_connection_args(parser, connections=CONNECTIONS)
    parser.add_argument("--unit", type=int, default=1, help="Modbus unit id")
    parser.add_argument(
        "--legacy", action="store_true", help="an older-generation inverter"
    )
    parser.add_argument(
        "--pm",
        action="store_true",
        help="also read the parallel-system registers (current generation only)",
    )
    parser.add_argument(
        "--raw", action="store_true", help="also dump every register read, as JSON"
    )
    parser.add_argument(
        "--registers",
        type=_register_range,
        action="append",
        default=[],
        metavar="ADDR[:COUNT]",
        help=f"also read these holding registers, up to {MAX_COUNT} at a time",
    )
    parser.add_argument(
        "--packs",
        action="store_true",
        help="also read each BTS battery pack; selecting one writes the tower's "
        "pack selection register (0x9020)",
    )
    args = parser.parse_args()

    try:
        connection = await connect_from_args(args)
    except ModbusError as err:
        # A connect timeout arrives with no message of its own.
        detail = str(err) or type(err).__name__
        print(f"Could not connect to {args.target}: {detail}")
        return 1

    timed = TimedUnit(connection.for_unit(args.unit))
    masks: dict[int, int] = {}
    mask_type = ""
    packs: list[str] = []
    try:
        inverter: Inverter = (
            await SofarLegacyInverter.async_detect(timed)
            if args.legacy
            else await SofarInverter.async_detect(timed, read_pm=args.pm)
        )
        report = await inverter.async_update()  # the first update sets the inverter up
        # Everything below reads again, so measure the poll alone.
        poll_reads, poll_stats = timed.reads, timed.stats
        if isinstance(inverter, SofarInverter):
            masks = await inverter.async_read_masks()
            mask_type = await _mask_type(timed)
        if (
            args.packs
            and isinstance(inverter, SofarInverter)
            and inverter.has_battery_tower
        ):
            packs = await _read_packs(inverter)
        registers = await _read_registers(timed, args.registers)
        raw = await inverter.async_read_raw() if args.raw else None
    except ModbusError as err:
        print(f"Could not read the inverter: {str(err) or type(err).__name__}")
        # A poll that gave up is exactly when its timings are worth seeing.
        print(f"{timed.reads} Modbus reads, {_timings(timed.stats)}")
        return 1
    finally:
        await connection.close()

    _line("Serial number", inverter.serial_number)
    if isinstance(inverter, SofarInverter):
        _line("Model", inverter.model)
    _line("Type", inverter.inverter_type.name)
    if isinstance(inverter, SofarInverter):
        _print_verdicts(inverter, mask_type)
    for name, component in served_components(inverter):
        print()
        print_component(component, title=name)
    if report.failed:
        print("\nFailed to read:")
        for name, error in report.failed.items():
            print(f"  {name}: {str(error) or type(error).__name__}")
    for text in packs:
        print()
        print(text, end="")
    if isinstance(inverter, SofarInverter):
        _print_masks(masks)
    _print_registers(registers)
    if raw is not None:
        print("\nRaw registers")
        # The dump arrives address-ordered; sorting keys would undo that.
        print(json.dumps(raw, indent=2))
    print(f"\n{poll_reads} Modbus reads, {_timings(poll_stats)}")
    return 0


raise SystemExit(asyncio.run(main()))
