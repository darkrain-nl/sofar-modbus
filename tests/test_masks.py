"""The AddressMask blocks, decoded over the mock backend."""

from __future__ import annotations

import logging

import pytest
from modbus_connection import (
    IllegalDataAddressError,
    ModbusConnectionError,
    ModbusTimeoutError,
)
from modbus_connection.mock import MockModbusUnit

from sofar_modbus import SofarInverter
from sofar_modbus.variants import (
    EPS,
    GEN,
    HYBRID,
    MPPT4,
    MPPT6,
    PM,
    PV,
    X1,
    X3,
    InverterType,
)

from .conftest import HYBRID_SERIAL, MODERN_HOLDING

# Captured from a 4.4 KTLX-G3; pins the register order against hardware.
GRID_OUTPUT_MASK = [0x1C00, 0x8218, 0x4308, 0x617F]

# The same unit's energy block: solar generation only, no meter.
UNMETERED_ENERGY_MASK = [0x0000, 0x0000, 0x0000, 0x00FF]
# The meter registers 0x0688-0x0693 declared valid alongside it.
METERED_ENERGY_MASK = [0x0000, 0x0000, 0x000F, 0xFFFF]
# A mask denying even its own four registers, so not a mask at all.
SELF_DENYING_MASK = [0x0000, 0x0000, 0x0000, 0x00F0]

# Every block this library reads registers from, spelled out so a change
# to MASK_BLOCKS has to be made here too.
MODELED_BLOCKS = [
    0x0400,
    0x0440,
    0x0480,
    0x0500,
    0x0580,
    0x05C0,
    0x0600,
    0x0640,
    0x0680,
    0x06C0,
    0x1000,
    0x1040,
    0x1100,
    0x1180,
]
TOWER_BLOCKS = [0x9000, 0x9040]

UNKNOWN_SERIAL = "NOPE000000001"

# A diagnostics download from the same 4.4 KTLX-G3, keyed by block base.
KTLX_G3_MASKS = {
    0x0400: 0x0003FFC00581FFFF,
    0x0440: 0x0000003FFFFFEFEF,
    0x0480: 0x1C0082184308617F,
    0x0500: 0x000000000000000F,
    0x0580: 0x00000000000003FF,
    0x05C0: 0x000000000000001F,
    0x0600: 0x000000000000000F,
    0x0640: 0x000000000000000F,
    0x0680: 0x00000000000000FF,
    0x06C0: 0x00000000000071DF,
    0x1000: 0x001F41FE0006FFFF,
    0x1040: 0x000000000000000F,
    0x1100: 0x000000000000001F,
    0x1180: 0x000000000000000F,
}

# A single-phase hybrid with four strings, spelled out from the spec.
SINGLE_PHASE_GRID_MASK = 0x0F | 1 << 0x0D  # voltage L1 only
FOUR_STRING_PV_MASK = 0xFFFF  # 0x0584-0x058F
FIVE_STRING_PV_MASK = 0x3FFFF  # 0x0584-0x0592
TWO_BATTERY_MASK = 0x3FFFF  # 0x0604-0x0611
TOWER_MASK = 0x0F


def mask_registers(mask: int) -> list[int]:
    """Split a mask into its four registers, most significant first."""
    return [mask >> shift & 0xFFFF for shift in (48, 32, 16, 0)]


def unknown_inverter(
    unit: MockModbusUnit, masks: dict[int, int], *, read_pm: bool = False
) -> SofarInverter:
    """An inverter whose serial is unknown, publishing ``masks``."""
    unit.holding.update(MODERN_HOLDING)
    for base, mask in masks.items():
        unit.holding[base] = mask_registers(mask)
    return SofarInverter(unit, serial_number=UNKNOWN_SERIAL, read_pm=read_pm)


@pytest.fixture
def pv_inverter(mock_modbus_unit: MockModbusUnit) -> SofarInverter:
    """A PV-only inverter, which has no battery tower to ask about."""
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    return SofarInverter(
        mock_modbus_unit, serial_number=HYBRID_SERIAL, inverter_type=PV | X1
    )


async def test_a_mask_decodes_most_significant_register_first(
    pv_inverter: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """Bit n is base + n, with the block's first register holding the top bits."""
    mock_modbus_unit.holding[0x0480] = GRID_OUTPUT_MASK
    masks = await pv_inverter.async_read_masks()
    assert masks[0x0480] == 0x1C0082184308617F
    assert masks[0x0480] >> (0x0484 - 0x0480) & 1  # grid frequency, served
    assert masks[0x0480] >> (0x0498 - 0x0480) & 1  # voltage L2, served
    assert not masks[0x0480] >> (0x048C - 0x0480) & 1  # unused, not served


async def test_every_modeled_block_is_read(pv_inverter: SofarInverter) -> None:
    """One mask per block holding registers this library decodes."""
    assert sorted(await pv_inverter.async_read_masks()) == MODELED_BLOCKS


async def test_an_unanswered_block_is_left_out(
    pv_inverter: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """A model without the block simply has no mask for it."""
    mock_modbus_unit.fail_read(0x0500, IllegalDataAddressError())
    masks = await pv_inverter.async_read_masks()
    assert 0x0500 not in masks
    assert len(masks) == len(MODELED_BLOCKS) - 1


async def test_a_timed_out_block_is_left_out(
    pv_inverter: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """Absent blocks time out rather than refusing; that is not a mask either."""
    mock_modbus_unit.fail_read(0x1180, ModbusTimeoutError("no answer"))
    assert 0x1180 not in await pv_inverter.async_read_masks()


async def test_a_dead_link_is_not_read_as_an_absent_mask(
    pv_inverter: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """A broken connection has to surface, not read as a model without blocks."""
    mock_modbus_unit.fail_read(0x0600, ModbusConnectionError("link down"))
    with pytest.raises(ModbusConnectionError):
        await pv_inverter.async_read_masks()


async def test_the_tower_blocks_are_skipped_without_a_tower(
    pv_inverter: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """Asking a tower-less inverter for the BMS blocks only buys a timeout."""
    await pv_inverter.async_read_masks()
    assert not any(
        event.address in TOWER_BLOCKS for event in mock_modbus_unit.read_events
    )


async def test_the_tower_blocks_are_read_for_a_battery_tower(
    hybrid: SofarInverter,
) -> None:
    """A BTS inverter answers the BMS blocks, so they are worth asking for."""
    assert sorted(await hybrid.async_read_masks()) == MODELED_BLOCKS + TOWER_BLOCKS


async def test_reading_masks_needs_no_setup(
    pv_inverter: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """The serial settles the tower, so no EPS probe precedes a download."""
    await pv_inverter.async_read_masks()
    assert pv_inverter.readings_components == ()
    assert all(event.address & 0x3F == 0 for event in mock_modbus_unit.read_events)


async def test_a_denied_meter_block_is_not_polled(
    pv_inverter: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """An unmetered model reads indeterminate values there, never zeros."""
    mock_modbus_unit.holding[0x0680] = UNMETERED_ENERGY_MASK
    mock_modbus_unit.holding[0x068A] = [0, 500]
    await pv_inverter.async_update()
    assert "meter_energy" not in pv_inverter.readings_components
    assert "energy" in pv_inverter.readings_components
    assert pv_inverter.meter_energy.load_consumption_total is None


async def test_a_denied_meter_block_is_logged(
    pv_inverter: SofarInverter,
    mock_modbus_unit: MockModbusUnit,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="sofar_modbus")
    mock_modbus_unit.holding[0x0680] = UNMETERED_ENERGY_MASK
    await pv_inverter.async_update()
    assert (
        "Inverter SP1ES12345678 denies 0x0688 in its mask, dropping meter_energy"
        in caplog.messages
    )


async def test_a_served_meter_block_is_polled(
    pv_inverter: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """A metered model measures load and import for real, so keep them."""
    mock_modbus_unit.holding[0x0680] = METERED_ENERGY_MASK
    mock_modbus_unit.holding[0x068A] = [0, 500]
    await pv_inverter.async_update()
    assert "meter_energy" in pv_inverter.readings_components
    assert pv_inverter.meter_energy.load_consumption_total == pytest.approx(50.0)


async def test_a_model_publishing_no_mask_keeps_the_meter_block(
    pv_inverter: SofarInverter,
) -> None:
    """Silence decides nothing; only an explicit denial drops a component."""
    await pv_inverter.async_update()
    assert "meter_energy" in pv_inverter.readings_components


async def test_a_self_denying_mask_is_not_trusted(
    pv_inverter: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """A real mask always declares its own four registers valid."""
    mock_modbus_unit.holding[0x0680] = SELF_DENYING_MASK
    await pv_inverter.async_update()
    assert "meter_energy" in pv_inverter.readings_components


async def test_an_unanswered_energy_block_keeps_the_meter_block(
    pv_inverter: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """A model that refuses the mask has not denied anything."""
    mock_modbus_unit.fail_read(0x0680, IllegalDataAddressError())
    await pv_inverter.async_update()
    assert "meter_energy" in pv_inverter.readings_components


async def test_a_model_without_the_component_is_not_asked(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """No point paying for a mask read to gate what is never polled."""
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    device = SofarInverter(
        mock_modbus_unit, serial_number=HYBRID_SERIAL, inverter_type=GEN | X1
    )
    await device.async_update()
    assert "meter_energy" not in device.readings_components
    assert not any(event.address == 0x0680 for event in mock_modbus_unit.read_events)


async def test_an_unknown_serial_takes_its_type_from_the_masks(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """Hardware masks must land on what the SS2E prefix gives that unit."""
    device = unknown_inverter(mock_modbus_unit, KTLX_G3_MASKS)
    await device.async_update()
    assert device.inverter_type == GEN | X3 | PV
    assert device.readings_components == ("state", "grid", "pv_1_2", "energy")
    assert device.model is None


async def test_a_hybrid_is_detected_from_its_battery_and_strings(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    device = unknown_inverter(
        mock_modbus_unit,
        {
            0x0480: SINGLE_PHASE_GRID_MASK,
            0x0580: FOUR_STRING_PV_MASK,
            0x0600: TWO_BATTERY_MASK,
        },
    )
    await device.async_update()
    assert device.inverter_type == GEN | X1 | HYBRID | MPPT4 | EPS
    assert not device.has_battery_tower
    assert device.readings_components == (
        "state",
        "grid",
        "offgrid",
        "offgrid_single_phase",
        "pv_1_2",
        "pv_3",
        "pv_4",
        "battery_1_2",
        "battery_3_8",
        "battery_totals",
        "energy",
        "meter_energy",
        "battery_energy",
    )


async def test_a_hybrid_with_a_tower_mask_has_a_tower(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    device = unknown_inverter(
        mock_modbus_unit,
        {
            0x0480: SINGLE_PHASE_GRID_MASK,
            0x0580: FOUR_STRING_PV_MASK,
            0x0600: TWO_BATTERY_MASK,
            0x9000: TOWER_MASK,
        },
    )
    await device.async_update()
    assert device.has_battery_tower


async def test_a_pv_inverter_is_not_asked_about_a_tower(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """Asking a tower-less inverter for the BMS mask only buys a timeout."""
    device = unknown_inverter(mock_modbus_unit, KTLX_G3_MASKS)
    await device.async_update()
    assert not any(event.address >= 0x9000 for event in mock_modbus_unit.read_events)


async def test_an_odd_string_count_polls_the_whole_pair(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """Dropping string 5 would hide a real reading to avoid a denied one."""
    device = unknown_inverter(
        mock_modbus_unit,
        {
            0x0480: KTLX_G3_MASKS[0x0480],
            0x0580: FIVE_STRING_PV_MASK,
            0x0600: KTLX_G3_MASKS[0x0600],
        },
    )
    await device.async_update()
    assert device.inverter_type == GEN | X3 | PV | MPPT6


async def test_detection_reads_only_the_blocks_it_decides_on(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    device = unknown_inverter(mock_modbus_unit, KTLX_G3_MASKS)
    await device.async_ensure_setup()
    masks_read = [
        event.address
        for event in mock_modbus_unit.read_events
        if event.address & 0x3F == 0
    ]
    assert masks_read == [0x0480, 0x0600, 0x0580, 0x0680]


async def test_a_model_publishing_no_mask_stays_unknown(
    mock_modbus_unit: MockModbusUnit, caplog: pytest.LogCaptureFixture
) -> None:
    """Without a usable mask nothing changes: the type stays empty."""
    caplog.set_level(logging.DEBUG, logger="sofar_modbus")
    device = unknown_inverter(mock_modbus_unit, {})
    await device.async_update()
    assert device.inverter_type == InverterType(0)
    assert device.readings_components == ()
    assert (
        "Inverter NOPE000000001 publishes no usable mask, its type stays unknown"
        in caplog.messages
    )


@pytest.mark.parametrize("refused", [0x0480, 0x0600, 0x0580])
async def test_one_refused_block_decides_nothing(
    mock_modbus_unit: MockModbusUnit, refused: int
) -> None:
    """A half-known type would poll the wrong phase count or battery."""
    device = unknown_inverter(mock_modbus_unit, KTLX_G3_MASKS)
    mock_modbus_unit.fail_read(refused, IllegalDataAddressError())
    await device.async_update()
    assert device.inverter_type == InverterType(0)


async def test_a_detected_type_is_logged(
    mock_modbus_unit: MockModbusUnit, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="sofar_modbus")
    device = unknown_inverter(mock_modbus_unit, KTLX_G3_MASKS)
    await device.async_update()
    assert (
        "Inverter NOPE000000001 declares itself GEN|X3|PV in its masks"
        in caplog.messages
    )


async def test_detection_keeps_read_pm(mock_modbus_unit: MockModbusUnit) -> None:
    """Parallel-system registers are the caller's call, not the mask's."""
    device = unknown_inverter(mock_modbus_unit, KTLX_G3_MASKS, read_pm=True)
    await device.async_update()
    assert device.inverter_type == GEN | X3 | PV | PM


async def test_a_known_serial_reads_no_mask_to_detect(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """The prefix table already settled it, so detection never runs."""
    await hybrid.async_update()
    assert not any(
        event.address in (0x0480, 0x0580, 0x0600)
        for event in mock_modbus_unit.read_events
    )
