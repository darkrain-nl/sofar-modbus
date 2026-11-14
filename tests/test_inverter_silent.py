"""A silent inverter behind an open link raises its own error."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from modbus_connection import (
    GatewayTargetError,
    IllegalDataAddressError,
    ModbusTimeoutError,
)
from modbus_connection.mock import MockModbusConnection, MockModbusUnit

from sofar_modbus import SofarInverter, UpdateReport
from sofar_modbus.modern import (
    BatteryTowerSilentError,
    InverterSilentError,
    SilentError,
)

from .conftest import HYBRID_SERIAL, MODERN_HOLDING, drop_link_on_read

STATE_REGISTER = 0x0404
GRID_REGISTER = 0x0484
RATING_REGISTER = 0x06ED
SERIAL_REGISTER = 0x0445
RTC_SYNC_REGISTER = 0x100A


def answer_with(
    monkeypatch: pytest.MonkeyPatch, unit: MockModbusUnit, errors: dict[int, Exception]
) -> None:
    """Fail every read, with ``errors`` per address and a gateway error else."""

    async def read(address: int, count: int) -> list[int]:
        raise errors.get(address, GatewayTargetError())

    monkeypatch.setattr(unit, "read_holding_registers", read)


@pytest.mark.parametrize(
    ("poll", "address"),
    [
        pytest.param(
            SofarInverter.async_update_readings, STATE_REGISTER, id="readings"
        ),
        pytest.param(
            SofarInverter.async_update_settings, RTC_SYNC_REGISTER, id="settings"
        ),
        pytest.param(SofarInverter.async_update, STATE_REGISTER, id="update"),
    ],
)
async def test_a_first_up_timeout_on_an_open_link_is_silence(
    hybrid: SofarInverter,
    mock_modbus_unit: MockModbusUnit,
    poll: Callable[[SofarInverter], Awaitable[UpdateReport]],
    address: int,
) -> None:
    await hybrid.async_update()
    timeout = ModbusTimeoutError("inverter asleep")
    mock_modbus_unit.fail_read(address, timeout)

    with pytest.raises(InverterSilentError, match="inverter asleep") as info:
        await poll(hybrid)

    assert info.value.__cause__ is timeout
    assert hybrid.connected


async def test_a_timeout_during_setup_on_an_open_link_is_silence(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    mock_modbus_unit.fail_read(RATING_REGISTER, ModbusTimeoutError("no rating"))
    inverter = SofarInverter(mock_modbus_unit, serial_number=HYBRID_SERIAL)

    with pytest.raises(InverterSilentError):
        await inverter.async_update_readings()


SETUP_POLLS = [
    SofarInverter.async_update_readings,
    SofarInverter.async_update_settings,
    SofarInverter.async_update,
    SofarInverter.async_update_packs,
]


@pytest.mark.parametrize("poll", SETUP_POLLS)
@pytest.mark.parametrize(
    "serial_number",
    [
        pytest.param(HYBRID_SERIAL, id="pv_tier"),
        pytest.param("NOPE000000001", id="detect_type"),
    ],
)
async def test_a_gateway_during_setup_on_an_open_link_is_silence(
    mock_modbus_unit: MockModbusUnit,
    poll: Callable[[SofarInverter], Awaitable[UpdateReport]],
    serial_number: str,
) -> None:
    gateway = GatewayTargetError()
    mock_modbus_unit.fail_requests(gateway)
    inverter = SofarInverter(mock_modbus_unit, serial_number=serial_number)

    with pytest.raises(InverterSilentError) as info:
        await poll(inverter)

    assert info.value.__cause__ is gateway


async def test_a_gateway_rating_during_setup_is_silence(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    mock_modbus_unit.fail_read(RATING_REGISTER, GatewayTargetError())
    inverter = SofarInverter(mock_modbus_unit, serial_number=HYBRID_SERIAL)

    with pytest.raises(InverterSilentError):
        await inverter.async_update_readings()


async def test_a_gateway_during_setup_on_a_closed_link_stays_raw(
    mock_modbus_connection: MockModbusConnection,
    mock_modbus_unit: MockModbusUnit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_modbus_unit.fail_requests(GatewayTargetError())
    drop_link_on_read(monkeypatch, mock_modbus_connection, mock_modbus_unit)
    inverter = SofarInverter(mock_modbus_unit, serial_number=HYBRID_SERIAL)

    with pytest.raises(GatewayTargetError):
        await inverter.async_update_readings()


async def test_a_timeout_that_closes_the_link_stays_a_plain_timeout(
    hybrid: SofarInverter,
    mock_modbus_connection: MockModbusConnection,
    mock_modbus_unit: MockModbusUnit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await hybrid.async_update()
    drop_link_on_read(monkeypatch, mock_modbus_connection, mock_modbus_unit)
    mock_modbus_unit.fail_read(STATE_REGISTER, ModbusTimeoutError("adapter gone"))

    with pytest.raises(ModbusTimeoutError) as info:
        await hybrid.async_update_readings()

    assert type(info.value) is ModbusTimeoutError


async def test_a_timeout_after_an_answer_stays_a_plain_timeout(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """Something answered, so the inverter is not silent."""
    await hybrid.async_update()
    mock_modbus_unit.fail_read(GRID_REGISTER, ModbusTimeoutError("slow grid block"))

    report = await hybrid.async_update_readings()

    assert type(report.failed["grid"]) is ModbusTimeoutError


async def test_detection_on_an_open_link_raises_silence(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    mock_modbus_unit.fail_read(SERIAL_REGISTER, ModbusTimeoutError("asleep"))

    with pytest.raises(InverterSilentError):
        await SofarInverter.async_detect(mock_modbus_unit)


async def test_detection_keeps_a_gateway_error(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """The config flow reports a gateway error as is."""
    mock_modbus_unit.fail_requests(GatewayTargetError())

    with pytest.raises(GatewayTargetError):
        await SofarInverter.async_detect(mock_modbus_unit)


@pytest.mark.parametrize(
    "poll",
    [
        SofarInverter.async_update_readings,
        SofarInverter.async_update_settings,
        SofarInverter.async_update,
    ],
)
@pytest.mark.parametrize(
    "errors",
    [
        pytest.param({}, id="gateway"),
        pytest.param({GRID_REGISTER: ModbusTimeoutError("no grid")}, id="with_timeout"),
    ],
)
async def test_a_silent_gateway_poll_raises(
    hybrid: SofarInverter,
    mock_modbus_unit: MockModbusUnit,
    monkeypatch: pytest.MonkeyPatch,
    poll: Callable[[SofarInverter], Awaitable[UpdateReport]],
    errors: dict[int, Exception],
) -> None:
    await hybrid.async_update()
    answer_with(monkeypatch, mock_modbus_unit, errors)

    with pytest.raises(InverterSilentError) as info:
        await poll(hybrid)

    assert isinstance(info.value.__cause__, ExceptionGroup)


async def test_a_refusal_proves_the_inverter_is_there(
    hybrid: SofarInverter,
    mock_modbus_unit: MockModbusUnit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await hybrid.async_update()
    answer_with(
        monkeypatch, mock_modbus_unit, {GRID_REGISTER: IllegalDataAddressError()}
    )

    report = await hybrid.async_update_readings()

    assert not report.updated
    assert isinstance(report.failed["grid"], IllegalDataAddressError)


async def test_a_silent_gateway_poll_on_a_closed_link_raises_a_plain_timeout(
    hybrid: SofarInverter,
    mock_modbus_connection: MockModbusConnection,
    mock_modbus_unit: MockModbusUnit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await hybrid.async_update()
    mock_modbus_unit.fail_requests(GatewayTargetError())
    drop_link_on_read(monkeypatch, mock_modbus_connection, mock_modbus_unit)

    with pytest.raises(ModbusTimeoutError) as info:
        await hybrid.async_update_readings()

    assert type(info.value) is ModbusTimeoutError
    assert isinstance(info.value.__cause__, ExceptionGroup)


async def test_an_empty_poll_reports(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """An unknown serial without masks polls nothing at all."""
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    inverter = SofarInverter(mock_modbus_unit, serial_number="NOPE000000001")

    report = await inverter.async_update_readings()

    assert report == UpdateReport()


def test_every_silence_is_one_catchable_timeout() -> None:
    assert issubclass(InverterSilentError, SilentError)
    assert issubclass(BatteryTowerSilentError, SilentError)
    assert issubclass(SilentError, ModbusTimeoutError)
    assert not issubclass(BatteryTowerSilentError, InverterSilentError)
