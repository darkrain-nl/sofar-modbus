#!/usr/bin/env python3

"""Query a Sofar inverter and print every value."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

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
from sofar_modbus.tuning import LinkStats, TimedUnit

# An inverter's RS-485 line, direct or through a socket:// device, and
# the gateways answering Modbus TCP themselves. No ASCII: the library
# does not support it. The tcp framings are the deprecated spelling of
# a serial line, kept working while the examples move over.
CONNECTIONS = (("tcp", "rtu"), ("tcp", "socket"), ("serial", "rtu"))

Inverter = SofarInverter | SofarLegacyInverter

EXAMPLES = """examples:
  uv run script/query.py socket://192.168.1.50:8899 --transport serial --unit 1
  uv run script/query.py /dev/ttyUSB0 --transport serial --unit 1 --legacy
  uv run script/query.py 192.168.1.50 --unit 1 --raw
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
            *(("battery_pack",) if inverter.has_battery_tower else ()),
        )
        return [(name, getattr(inverter, name)) for name in names]
    return [
        (name, component)
        for name, component in vars(inverter).items()
        if isinstance(component, SofarComponentBase)
        and matches(inverter_type, component.applies_to)
    ]


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
    args = parser.parse_args()

    try:
        connection = await connect_from_args(args)
    except ModbusError as err:
        # A connect timeout arrives with no message of its own.
        detail = str(err) or type(err).__name__
        print(f"Could not connect to {args.target}: {detail}")
        return 1

    timed = TimedUnit(connection.for_unit(args.unit))
    try:
        inverter: Inverter = (
            await SofarLegacyInverter.async_detect(timed)
            if args.legacy
            else await SofarInverter.async_detect(timed, read_pm=args.pm)
        )
        report = await inverter.async_update()  # the first update sets the inverter up
        # A raw dump re-reads everything, so measure the poll alone.
        poll_reads, poll_stats = timed.reads, timed.stats
        raw = await inverter.async_read_raw() if args.raw else None
    except ModbusError as err:
        print(f"Could not read the inverter: {str(err) or type(err).__name__}")
        # A poll that gave up is exactly when its timings are worth seeing.
        print(f"{timed.reads} Modbus reads, {_timings(timed.stats)}")
        return 1
    finally:
        await connection.close()

    print(f"Serial number  {inverter.serial_number}")
    if isinstance(inverter, SofarInverter):
        print(f"Model          {inverter.model}")
    print(f"Type           {inverter.inverter_type.name}")
    for name, component in served_components(inverter):
        print()
        print_component(component, title=name)
    if report.failed:
        print("\nFailed to read:")
        for name, error in report.failed.items():
            print(f"  {name}: {str(error) or type(error).__name__}")
    if raw is not None:
        print("\nRaw registers")
        # The dump arrives address-ordered; sorting keys would undo that.
        print(json.dumps(raw, indent=2))
    print(f"\n{poll_reads} Modbus reads, {_timings(poll_stats)}")
    return 0


raise SystemExit(asyncio.run(main()))
