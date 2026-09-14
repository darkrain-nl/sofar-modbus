# sofar-modbus

Read Sofar Solar inverters over Modbus, as typed Python objects rather than
register numbers.

The library maps Sofar's register set onto
[modbus-connection](https://github.com/home-assistant-libs/modbus-connection)'s device model:
you hand it a `ModbusUnit`, call `async_update()`, and read sub-systems as
attributes. It owns no connection and no I/O policy — the caller does.

## Supported devices

Sofar ships two quite different register maps, so there are two device objects.

**`SofarInverter` — the current generation.** HYD hybrids and KTL-X / KTLM PV
inverters, over the 0x0400 (state and identity), 0x0480 (grid), 0x0500
(off-grid), 0x0580 (PV), 0x0600 (battery), 0x0680 (energy), 0x1000 (settings)
and 0x9000 (BTS battery tower) blocks. Serial prefixes: `SP1`, `SP2`, `ZP1`,
`ZP2`, `SM2E`, `ZM2E`, `SH3E`, `SS2E`, `ZS2E`, `SQ1ES1`, `SA1`, `SB1`, `SC1`,
`SD1`, `SF4`, `SH1`, `SL1`, `SJ2`, `SS1`. Includes the Azzurro and ZCS
rebadges. This is the only generation with writable registers.

**`SofarLegacyInverter` — the older generation.** The earlier PV inverters
(`SA1`, `SA3`, `SB1`, `ZA3`, `SC1`, `SD1`, `SF4`, `SH1`, `SJ2`, `SL1`, `SM1`)
and the `SE1E` / `SM1E` / `ZE1E` / `ZM1E` storage inverters, over the 0x0000 and
0x0200 blocks, with the serial number in the input-register space. Read-only.

Within a generation, what an inverter serves depends on its model: single or
three phase, PV-only or hybrid, how many MPPT trackers, whether off-grid (EPS)
and parallel-system registers exist. The first update reads the serial number
and settles this into an `InverterType` bitmask; each component declares the
mask it applies to, and a poll reads only the matching ones. Nothing else is
touched — an inverter without batteries never sees a battery register.

## Usage

```python
import asyncio

from modbus_connection import ModbusSerialParams
from modbus_connection.tmodbus import ModbusConnection
from sofar_modbus import SofarInverter


async def main() -> None:
    connection = ModbusConnection(
        ModbusSerialParams(device="socket://192.168.1.50:8899")
    )
    try:
        inverter = SofarInverter(connection.for_unit(1))
        await inverter.async_update()

        print("Model:", inverter.model, inverter.serial_number)
        print("State:", inverter.state.system_state)
        print("Grid power:", inverter.grid.active_power_output_total, "kW")
        print("PV power:", inverter.pv_1_2.pv_power_total, "kW")
        print("Battery SoC:", inverter.battery_totals.battery_capacity_total, "%")
        print("Solar today:", inverter.energy.solar_generation_today, "kWh")
    finally:
        await connection.close()


asyncio.run(main())
```

A poll reads each sub-system independently, the way the integration reads its
blocks: one slow or refused block does not take the rest of the poll with it.
The exception is a run of registers several sub-systems tile — the older
generation's storage block and its three-phase PV block — where a read of one
already spans the others, so they are pooled into that single request and
reported under one name (`storage_block`, `pv_block`).
Every update method returns an `UpdateReport` — a failed component keeps its
previous values, does not notify its listeners, and is listed by attribute
name with its error, while every other component refreshes and notifies once
the whole poll is done. A dead link (`ModbusConnectionError`) raises, and so
does a timeout before any component has answered — an inverter that is simply
not responding is not walked block by block, paying a timeout for each:

```python
report = await inverter.async_update()
for name, error in report.failed.items():
    print(f"{name} kept its previous values: {error}")
```

### Faults are grouped by subsystem, not by register

The inverter reports faults as 26 bitmask registers, `state.fault_1` through
`state.fault_30`. A register is wire format: `fault_11` happens to hold four
shutdown bits and seven fan bits, and battery faults are spread over nine
different registers. Several bits are set at once, so no single one of them is
"the" fault.

`state.active_faults` decodes the lot into the subsystem each bit belongs to:

```python
from sofar_modbus.modern import FaultCategory

faults = inverter.state.active_faults
for fault in faults:
    print(fault.id, fault.key, fault.category)

if any(fault.category is FaultCategory.BATTERY for fault in faults):
    print("something is wrong with the battery")
```

Each `Fault` carries the vendor's ID, a stable snake_case `key`, and one of the
17 `FaultCategory` members. `FAULTS` is the full table of the 353 faults the
register map defines, and `FAULTS_BY_ID` indexes it. A register that has not
been read yet contributes nothing, so `active_faults` never reports a fault the
inverter did not actually answer for.

### Measurements and settings refresh separately

`SofarInverter` splits its poll by what it reads:

- `async_update_readings()` — what the inverter measures: power, yield, battery,
  state, faults.
- `async_update_settings()` — what it has been configured to do, plus the
  identity: registers that change when something writes them, not on their own.
- `async_update()` — both, in one merged report, for a caller that does not want
  to schedule them apart.

A report names only what the method it came from polled, and listeners fire at
the end of the poll that read them, so a settings poll does not hold up the
measurements. A settings poll is also how a write is read back: run one after
writing a register to see what took effect.

```python
await inverter.async_update_readings()  # every cycle
await inverter.async_update_settings()  # rarely, and after a write
```

This is worth scheduling: a three-phase HYD hybrid polls 276 registers in 31 blocks,
of which the settings are 65 registers in 13 blocks — the 0x1000 settings block,
and `identity`, which holds a serial number, firmware versions and the clock
`async_set_time()` writes. A single-phase KTL-M splits 135 registers in 11 blocks into
110 read and 25 configured.

`SofarLegacyInverter` has no writable settings, so it refreshes all of its
served components in one pass through `async_update()`, and does not offer the
two split update methods.

Writing works the same way — a plain field write for the registers that take
one, and a method for the registers the device insists on receiving as a block:

```python
from sofar_modbus.modern import ChargerUseMode, FeedinLimitationMode

await inverter.charger.write("charger_use_mode", ChargerUseMode.PASSIVE_MODE)
await inverter.feed_in.async_write_limit(FeedinLimitationMode.DISABLED, 3000)
await inverter.passive.async_write_power(
    grid_power=-2000, battery_min=0, battery_max=5000
)
await inverter.active_power_control.async_write_active_power_limit(True, 70)
```

`active_power_control` is a live throttle on the inverter's own output — distinct
from `feed_in`, which caps power exported to the grid. It applies to PV-only
inverters as well as hybrids, and takes effect within seconds.

A BTS battery tower multiplexes every pack onto one register block, so packs are
read one at a time rather than polled:

```python
if inverter.has_battery_tower:
    pack = await inverter.async_read_pack(pack_nr=0)
    print(pack.pack_serial_number, pack.soc, pack.cell_1_voltage)
```

How many packs there are to read is `parallel_group_count`, the high byte of
0x900D. Its low byte is `series_cell_count`, how many cells a pack has in
series, which is not a second dimension to iterate: a tower of four 16-cell
packs reports 0x0410, and reading that as four packs of sixteen asks for 64
packs that do not exist. Once a pack answers, `packs_in_group` and
`cells_in_pack` confirm both counts from the pack's own registers.

Asking for the pack a tower already serves writes nothing to the selection
register, so a tower that rejects that register still reports its current pack.

For an issue report, `async_read_raw()` dumps every register the inverter reads
undecoded, keyed by address space and address — every block a poll covers, for
the sub-systems this model serves. It fires no update listeners — a download is
not a poll, though the fields it reads do refresh. The pack block is not in it:
a dump of it would be whichever pack happened to be selected, with nothing to
say which.

`async_read_masks()` is the other half of an issue report. Every 64-address
block of this generation opens with a four-register mask naming which of its
registers the model actually serves, and this returns one per block, keyed by
the block's base address; bit *n* of a mask is `base + n`. It is worth having
because an inverter answers a register it does not serve rather than refusing
it, usually with zeros but not always, so the mask is the only dependable
statement of what a model supports. Blocks answering no mask are left out, and
the battery tower's blocks are only asked for when the inverter reports a tower,
since asking without one buys a timeout. Nothing decides what to poll from these
yet: today they are for reading, not for detection.

## Checking a real inverter

`script/query.py` reads one inverter once and prints every value it serves,
which is the quickest way to see whether an inverter is reachable, addressed
correctly, and detected as the model you expect:

```bash
uv run script/query.py socket://192.168.1.50:8899 --transport serial --unit 1
uv run script/query.py /dev/ttyUSB0 --transport serial --unit 1 --legacy
uv run script/query.py 192.168.1.50 --unit 1 --raw
```

The two generations share serial prefixes, so the script does not guess which
one it is talking to: pass `--legacy` for an older inverter. It prints the read
count as well, so a poll's request budget is visible against real hardware
rather than only in the tests. It follows the count with how long those reads
took, median, p95 and slowest, which is what to judge a timeout against.
`--raw` adds every register it read, undecoded, which is what an issue about a
wrong value should quote.

## Naming the link

An inverter answers RTU on its RS-485 line, so how to name the link depends on
what sits between you and that line, not on the inverter:

| Between you and the line | Parameters |
| :--- | :--- |
| Nothing: a USB or serial adapter | `ModbusSerialParams(device="/dev/ttyUSB0")` |
| A box forwarding the RTU frames | `ModbusSerialParams(device="socket://host:port")` |
| A gateway answering Modbus TCP | `ModbusTcpParams(host=...)` |

The second one is what `ModbusTcpParams(framer="rtu")` used to spell, which
modbus-connection 4.12 deprecates: those frames are a serial line however they
reach you, so a consumer pooling connections by endpoint opened two links onto
one half-duplex bus when two callers spelled it differently.

ASCII framing is unsupported either way. This library never accepts or forwards
it, and it exposes no connect helper that could, since the caller builds the
`ModbusUnit` and hands it over. An ASCII-framed link is untested here and
nothing works around it.

## How long a request waits

The timeout is spent per request, not per poll, so it is what a poll loses on
every register block that goes unanswered. Setup spends it deliberately: probing
for off-grid registers, or for a battery tower that is not there, means waiting
one out. An inverter itself is quick, and a 48-register block came back in a
median 243 ms on a 4.4 KTLX-G3 over TCP, but what sits between it and you varies
far more than the inverter does, so neither device object guesses a value. The
connection's own default, 10 seconds, applies.

Measure before choosing one. `sofar_modbus.tuning.TimedUnit` wraps a
`ModbusUnit` and times every request that passes through it, which is where
`query.py`'s numbers come from. Hand the wrapper to the inverter instead of the
unit and read its `stats` for the same figures in your own application.

A caller who has measured their link states it with `timeout=` on either
constructor, which asks for it through `ModbusUnit.require_timeout()`. Two
things to know before setting one: the connection runs with the largest value
any of its units asks for, so a device sharing the link can raise it, and a
lowered value takes effect at the next connect rather than on the link already
open.

### Or let the link say it itself

`LinkTuner` does the measuring and the asking, for a caller that would rather
not pick a number. Give it the same wrapper the inverter reads through, and
hand it each poll's report:

```python
from sofar_modbus.tuning import LinkTuner, TimedUnit

timed = TimedUnit(connection.for_unit(1))
inverter = SofarInverter(timed)
tuner = LinkTuner(timed)

while True:
    try:
        tuner.observe(await inverter.async_update_readings())
    except ModbusError as err:
        tuner.observe_failure(err)
        raise
```

Both halves matter. A poll gives up and raises rather than reporting when the
link is down, or when it times out before anything has answered, and that
second case is exactly what a timeout asked for too tightly looks like. A
consumer that only calls `observe()` would leave the tuner holding an ask the
link can no longer meet.

It tunes two things, from what the polls tell it.

**The timeout.** After five polls with nothing timing out, it asks for four
times the slowest request it saw, which on a link answering in 370 ms is about
1.5 seconds instead of ten. It only ever lowers: a link too slow to be worth
asking about keeps its own default, and a timeout under a value the tuner asked
for withdraws that ask entirely and waits twice as long before trying again,
whether the poll reported that timeout or raised it. So the worst it can do is
hand the link back what it started with.

**The gap between frames.** A device that cannot take requests back to back
says so by answering the wrong exchange (`ModbusDesyncError`), by reporting
itself busy, or by going quiet on a component that was answering a moment ago.
A desync widens the gap at once, the other two after three polls, up to 200 ms.
Twenty quiet polls give a step back, and each widening doubles the patience
before that is tried again. A `budget=` caps the whole thing: the gap is never
wider than that many seconds spread over the reads one poll makes, so a poll
cannot outgrow its interval. Registers a model has never served are exempt,
since chasing an absent block would widen the gap forever.

**The pause after the link opens.** Some devices are not ready to answer the
moment the socket is. Two opening requests that go unanswered earn a quarter
second, then half, then one, then two. This one is never given back: it costs a
single wait per connect, and a device that needed it still does.

`tuner.tuning` is what it asks of the link and how often it has had to give up,
which is worth putting in a diagnostics download, and worth storing:

```python
tuner.restore(saved)  # before the first poll
...
save(tuner.tuning)  # whenever it changes
```

Restoring brings back the patience that came with it, so a link that had to
hand a timeout back is not asked the same question after every restart.

The gap is per unit, so it paces this inverter's own frames and no one else's.
A line shared with another device cannot be quieted from here, only from
whoever builds the connection.

## Attribution

The register maps are derived from
[homeassistant-solax-modbus](https://github.com/wills106/homeassistant-solax-modbus)
(Apache-2.0), specifically its `plugin_sofar.py` and `plugin_sofar_old.py`. This
library keeps that project's field keys, scale factors, units and per-model
filtering, and is released under the same licence.

Where upstream declares the same key twice, this library keeps both fields and
the docstring on each carries upstream's name. Addresses follow the
manufacturer's protocol spec where the two disagree: PV string 6's power is read
at 0x0595, not aliased onto string 6's current register as upstream has it.
