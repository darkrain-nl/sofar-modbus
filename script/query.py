#!/usr/bin/env python3

"""Query a Sofar inverter and print every value.

Reads one inverter once and dumps it to the terminal — the quickest way to
check a real inverter with no application around it.

::

    uv run script/query.py 192.168.1.50 --unit 1 --framer rtu
    uv run script/query.py /dev/ttyUSB0 --transport serial --unit 1 --legacy
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from modbus_connection import ModbusError
from modbus_connection.cli_helper import (
    CountingUnit,
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

# RS-485 RTU, reached directly or through a gateway that either forwards the
# frames untouched (rtu) or converts them to native Modbus TCP (socket). ASCII
# is left out — the library does not support it.
CONNECTIONS = (("tcp", "rtu"), ("tcp", "socket"), ("serial", "rtu"))

Inverter = SofarInverter | SofarLegacyInverter


def served_components(inverter: Inverter) -> list[tuple[str, Component]]:
    """The components this inverter serves; ``battery_pack`` needs the tower flag."""
    inverter_type = inverter.inverter_type
    assert inverter_type is not None  # the update below set the inverter up
    has_tower = isinstance(inverter, SofarInverter) and inverter.has_battery_tower
    return [
        (name, component)
        for name, component in vars(inverter).items()
        if isinstance(component, SofarComponentBase)
        and matches(inverter_type, component.applies_to)
        and (name != "battery_pack" or has_tower)
    ]


async def main() -> int:
    """Read one inverter and print it."""
    # The backend logs a failed connect at ERROR with its traceback; the
    # messages below say it in one line.
    logging.getLogger().addHandler(logging.NullHandler())

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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
    args = parser.parse_args()

    try:
        connection = await connect_from_args(args)
    except ModbusError as err:
        # A connect timeout arrives with no message of its own.
        detail = str(err) or type(err).__name__
        print(f"Could not connect to {args.target}: {detail}")
        return 1

    counting = CountingUnit(connection.for_unit(args.unit))
    inverter: Inverter = (
        SofarLegacyInverter(counting)
        if args.legacy
        else SofarInverter(counting, read_pm=args.pm)
    )
    try:
        report = await inverter.async_update()  # the first update sets the inverter up
    except ModbusError as err:
        print(f"Could not read the inverter: {str(err) or type(err).__name__}")
        return 1
    finally:
        await connection.close()

    print(f"Serial number  {inverter.serial_number}")
    if isinstance(inverter, SofarInverter):
        print(f"Model          {inverter.model}")
    if inverter.inverter_type is not None:
        print(f"Type           {inverter.inverter_type.name}")
    for name, component in served_components(inverter):
        print()
        print_component(component, title=name)
    if report.failed:
        print("\nFailed to read:")
        for name, error in report.failed.items():
            print(f"  {name}: {str(error) or type(error).__name__}")
    print(f"\n{counting.reads} Modbus reads")
    return 0


raise SystemExit(asyncio.run(main()))
