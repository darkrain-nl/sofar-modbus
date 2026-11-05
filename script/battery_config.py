#!/usr/bin/env python3

"""Read, and on request write, a Sofar battery's discharge limits."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from modbus_connection import ModbusError, ModbusUnit
from modbus_connection.cli_helper import add_connection_args, connect_from_args

from sofar_modbus import SofarInverter
from sofar_modbus.modern.enums import BatConfigCellType
from sofar_modbus.variants import HYBRID, X3

CONNECTIONS = (("tcp", "rtu"), ("tcp", "socket"), ("serial", "rtu"))

BLOCK = 0x1044
BLOCK_COUNT = 23  # through 0x105A, the last documented register
WRITE_COUNT = 19  # the G3 sheet's length for 3PH and BTS batteries
CHARGE_CUTOFF = 0x105B  # reserved in the spec, so read on its own
DOD, EOD, CELL_TYPE, EPS_BUFFER, CONTROL = 0x104D, 0x104E, 0x1051, 0x1052, 0x1053
COMMIT = 1
POLL_STEP = 0.5

NAMES = {
    0x1044: "BatConfig_ID",
    0x1045: "BatConfig_Address",
    0x1046: "BatConfig_Protocol",
    0x1047: "BatConfig_Voltage_Over",
    0x1048: "BatConfig_Voltage_Charge",
    0x1049: "BatConfig_Voltage_Lack",
    0x104A: "BatConfig_Voltage_Discharge_Stop",
    0x104B: "BatConfig_Current_Charge_Limit",
    0x104C: "BatConfig_Current_Discharge_Limit",
    0x104D: "BatConfig_Depth_of_Discharge",
    0x104E: "BatConfig_End_of_Discharge",
    0x104F: "BatConfig_Capacity",
    0x1050: "BatConfig_Voltage_Nominal",
    0x1051: "BatConfig_Cell_Type",
    0x1052: "BatConfig_EPS_Buffer",
    0x1053: "BatConfig_Control",
    0x1054: "BatConfig_Address2",
    0x1055: "BatConfig_Address3",
    0x1056: "BatConfig_Address4",
    0x1057: "BatConfig_TEMPCO",
    0x1058: "BatConfig_Voltage_Recovery_Buffer",
    0x1059: "BatConfig_Control_Bits",
    0x105A: "BatConfig_Voltage_Float",
    0x105B: "charge cut-off SOC (reserved in the spec)",
}

STATUS = {
    0x0000: "success",
    0x0001: "in progress",
    0xFFFB: "refused, controller busy or misconfigured",
    0xFFFC: "no answer from the controller",
    0xFFFD: "function disabled",
    0xFFFE: "storage failed",
    0xFFFF: "bad input",
}

LEAD_ACID = {
    BatConfigCellType.LEAD_ACID,
    BatConfigCellType.AGM,
    BatConfigCellType.GEL,
    BatConfigCellType.FLOODED,
}

EXAMPLES = """steps (nothing is written without --write):
  # (a) read the block and keep a copy to restore from
  uv run script/battery_config.py 192.168.1.50 --save before.json
  # (b) write the same values back and watch the commit status
  uv run script/battery_config.py 192.168.1.50 --rewrite --write
  # (c) on-grid cut-off to 28 %, then put the saved values back
  uv run script/battery_config.py 192.168.1.50 --on-grid 28 --write
  uv run script/battery_config.py 192.168.1.50 --restore before.json --write
  # (d) a combination the app refuses, to see what the inverter says
  uv run script/battery_config.py 192.168.1.50 --on-grid 10 --off-grid 20 \\
      --unchecked --write
  # charge cut-off 95 %: 0x105B alone, or 24 registers from 0x1044
  uv run script/battery_config.py 192.168.1.50 --charge 95 --method single --write
  uv run script/battery_config.py 192.168.1.50 --charge 95 --method block --write
"""


def _status(value: int) -> str:
    return f"0x{value:04X} ({STATUS.get(value, 'not in the spec')})"


def app_terms(words: dict[int, int]) -> dict[str, int | None]:
    """The limits as the SofarCloud app shows them, in %."""
    off_grid = 100 - words[EOD]
    return {
        "on_grid_cutoff": 100 - words[DOD],
        "off_grid_cutoff": off_grid,
        "off_grid_recovery": off_grid + words[EPS_BUFFER],
        "charge_cutoff": words.get(CHARGE_CUTOFF),
    }


def problems(on_grid: int, off_grid: int, recovery: int) -> list[str]:
    """Where the limits break the spec's DOD, EOD and buffer rules."""
    found = []
    for name, value in (("on-grid", on_grid), ("off-grid", off_grid)):
        if not 10 <= value <= 99:
            found.append(f"{name} cut-off {value} is outside 10-99")
    if on_grid < off_grid:
        found.append(f"on-grid cut-off {on_grid} is below off-grid {off_grid}")
    if not off_grid + 5 <= recovery <= 100:
        found.append(f"recovery {recovery} is outside {off_grid + 5}-100")
    return found


async def read_config(unit: ModbusUnit) -> dict[int, int]:
    """The block from 0x1044 and the charge cut-off, keyed by address."""
    words = {
        BLOCK + offset: value
        for offset, value in enumerate(
            await unit.read_holding_registers(BLOCK, BLOCK_COUNT)
        )
    }
    # A refusal here must not hide the documented block above it.
    try:
        words[CHARGE_CUTOFF] = (await unit.read_holding_registers(CHARGE_CUTOFF, 1))[0]
    except ModbusError as err:
        print(f"0x105B unreadable: {str(err) or type(err).__name__}")
    return words


def print_config(words: dict[int, int], planned: dict[int, int] | None = None) -> None:
    """Each register, and with ``planned`` what a write would change."""
    for address, value in words.items():
        line = f"  0x{address:04X}  {value:>5}  0x{value:04X}  {NAMES[address]}"
        if planned is not None and address in planned:
            if planned[address] != value:
                line += f"  -> {planned[address]}"
        print(line)
    print(f"  status   {_status(words[CONTROL])}")
    for name, term in app_terms(words).items():
        print(f"  {name:<18}{term}")


async def watch(unit: ModbusUnit, address: int, seconds: float) -> None:
    """Print ``address`` every POLL_STEP, to see a commit settle."""
    start = time.monotonic()
    while (elapsed := time.monotonic() - start) <= seconds:
        try:
            value = (await unit.read_holding_registers(address, 1))[0]
        except ModbusError as err:
            print(f"  +{elapsed:4.1f}s  {str(err) or type(err).__name__}")
        else:
            print(
                f"  +{elapsed:4.1f}s  0x{address:04X} = "
                f"{_status(value) if address == CONTROL else value}"
            )
        await asyncio.sleep(POLL_STEP)


async def send(
    unit: ModbusUnit, address: int, values: list[int], args: argparse.Namespace
) -> None:
    """Write ``values`` at ``address`` with --write, then show the result."""
    print(f"\nWrite at 0x{address:04X}, {len(values)} registers: {values}")
    if not args.write:
        print("Dry run: add --write to send it.")
        return
    await unit.write_registers(address, values)
    print("Written. Watching:")
    await watch(
        unit, CHARGE_CUTOFF if address == CHARGE_CUTOFF else CONTROL, args.watch
    )
    print("\nRead back:")
    print_config(
        await read_config(unit),
        {address + offset: value for offset, value in enumerate(values)},
    )


def refusal(inverter: SofarInverter, words: dict[int, int]) -> str | None:
    """Why this inverter is not one the 19-register write is documented for."""
    if not (HYBRID in inverter.inverter_type and X3 in inverter.inverter_type):
        return f"type {inverter.inverter_type.name} is not a three-phase hybrid"
    if words[CELL_TYPE] in LEAD_ACID:
        return "lead-acid batteries take a 23-register write"
    if words[CONTROL] == 0x0001:
        return "the last battery config write is still in progress"
    return None


async def run(unit: ModbusUnit, args: argparse.Namespace) -> int:
    """Read the block, then do the one step the arguments ask for."""
    inverter = await SofarInverter.async_detect(unit)
    print(f"Serial {inverter.serial_number}, type {inverter.inverter_type.name}")
    words = await read_config(unit)
    print("\nBattery config")
    print_config(words)
    if args.save:
        args.save.write_text(
            json.dumps(
                {
                    "serial": inverter.serial_number,
                    "read_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "registers": {f"0x{a:04X}": v for a, v in words.items()},
                },
                indent=2,
            )
            + "\n"
        )
        print(f"\nSaved to {args.save}")
    if not (
        args.rewrite
        or args.restore
        or args.charge is not None
        or any(v is not None for v in (args.on_grid, args.off_grid, args.recovery))
    ):
        return 0
    if (reason := refusal(inverter, words)) is not None:
        print(f"\nNot writing: {reason}.")
        return 2

    if args.charge is not None:
        if args.method == "single":
            await send(unit, CHARGE_CUTOFF, [args.charge], args)
            return 0
        block = [words[BLOCK + offset] for offset in range(BLOCK_COUNT)]
        block[CONTROL - BLOCK] = COMMIT
        await send(unit, BLOCK, [*block, args.charge], args)
        return 0

    block = [words[BLOCK + offset] for offset in range(WRITE_COUNT)]
    if args.restore:
        saved = json.loads(args.restore.read_text())
        if saved["serial"] != inverter.serial_number:
            print(f"\nNot writing: {args.restore} is from {saved['serial']}.")
            return 2
        block = [saved["registers"][f"0x{BLOCK + o:04X}"] for o in range(WRITE_COUNT)]
        if (charge := saved["registers"].get("0x105B")) != words.get(CHARGE_CUTOFF):
            print(f"Charge cut-off was {charge}: restore it with --charge.")
    elif not args.rewrite:
        on_grid = 100 - words[DOD] if args.on_grid is None else args.on_grid
        off_grid = 100 - words[EOD] if args.off_grid is None else args.off_grid
        # Moving off-grid alone keeps the buffer, not the recovery SOC.
        recovery = (
            off_grid + words[EPS_BUFFER] if args.recovery is None else args.recovery
        )
        if (found := problems(on_grid, off_grid, recovery)) and not args.unchecked:
            print("\nNot writing: " + "; ".join(found) + " (--unchecked sends it).")
            return 2
        block[DOD - BLOCK] = 100 - on_grid
        block[EOD - BLOCK] = 100 - off_grid
        block[EPS_BUFFER - BLOCK] = recovery - off_grid
    block[CONTROL - BLOCK] = COMMIT
    await send(unit, BLOCK, block, args)
    return 0


async def main() -> int:
    """Connect, run one step and close."""
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
    parser.add_argument("--save", type=Path, help="save the block read as JSON")
    step = parser.add_mutually_exclusive_group()
    step.add_argument(
        "--rewrite", action="store_true", help="write the values read back"
    )
    step.add_argument("--restore", type=Path, help="write a --save file back")
    step.add_argument("--charge", type=int, help="charge cut-off SOC, in %%")
    parser.add_argument("--on-grid", type=int, help="on-grid cut-off SOC, in %%")
    parser.add_argument("--off-grid", type=int, help="off-grid cut-off SOC, in %%")
    parser.add_argument("--recovery", type=int, help="off-grid recovery SOC, in %%")
    parser.add_argument(
        "--method",
        choices=("single", "block"),
        default="single",
        help="with --charge: 0x105B alone, or 24 registers from 0x1044",
    )
    parser.add_argument(
        "--unchecked", action="store_true", help="skip the app's limit checks"
    )
    parser.add_argument(
        "--watch", type=float, default=10, help="seconds to watch after a write"
    )
    parser.add_argument("--write", action="store_true", help="really write")
    args = parser.parse_args()
    if any(v is not None for v in (args.on_grid, args.off_grid, args.recovery)) and (
        args.rewrite or args.restore or args.charge is not None
    ):
        parser.error("set limits on their own, not with another step")

    try:
        connection = await connect_from_args(args)
    except ModbusError as err:
        print(f"Could not connect to {args.target}: {str(err) or type(err).__name__}")
        return 1
    try:
        return await run(connection.for_unit(args.unit), args)
    except ModbusError as err:
        print(f"Modbus error: {str(err) or type(err).__name__}")
        return 1
    finally:
        await connection.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
