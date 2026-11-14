"""The inverter bitmask and the matching rule ported from the plugins."""

from __future__ import annotations

from sofar_modbus.variants import (
    BAT_BTS,
    EPS,
    GEN,
    HYBRID,
    MPPT4,
    MPPT6,
    MPPT8,
    MPPT10,
    PM,
    PV,
    X1,
    X3,
    InverterType,
    matches,
)


def test_a_group_the_mask_ignores_matches_anything() -> None:
    """A mask naming no bit of a group puts no condition on that group."""
    assert matches(HYBRID | X3 | GEN, PV | HYBRID)  # says nothing about phase
    assert matches(HYBRID | X1 | GEN, PV | HYBRID)


def test_bits_within_a_group_are_or_ed() -> None:
    assert matches(PV | X1, PV | HYBRID)  # PV or hybrid: PV qualifies
    assert matches(HYBRID | X1, PV | HYBRID)
    assert not matches(X1 | GEN, PV | HYBRID)  # neither PV nor hybrid


def test_groups_are_and_ed() -> None:
    """A three-phase-only mask must not match a single-phase inverter."""
    assert matches(HYBRID | X3 | EPS, X3 | HYBRID | EPS)
    assert not matches(HYBRID | X1 | EPS, X3 | HYBRID | EPS)  # wrong phase
    assert not matches(HYBRID | X3, X3 | HYBRID | EPS)  # EPS not enabled


def test_mppt_tiers_gate_the_extra_strings() -> None:
    """A four-MPPT inverter reads strings 3 and 4, not 5 and up."""
    four = PV | X3 | GEN | MPPT4
    string_4 = GEN | PV | HYBRID | MPPT4 | MPPT6 | MPPT8 | MPPT10
    string_5 = GEN | PV | HYBRID | MPPT6 | MPPT8 | MPPT10
    assert matches(four, string_4)
    assert not matches(four, string_5)
    assert matches(PV | X3 | GEN | MPPT10, string_5)


def test_a_mask_with_no_mppt_bit_applies_to_every_inverter() -> None:
    assert matches(PV | X1 | GEN, GEN | PV | HYBRID)


def test_optional_feature_groups_are_independent() -> None:
    assert matches(HYBRID | X3 | PM, X3 | PV | HYBRID | PM)
    assert not matches(HYBRID | X3, X3 | PV | HYBRID | PM)


def test_bat_bts_belongs_to_no_group_so_it_filters_nothing() -> None:
    assert matches(HYBRID | X3 | BAT_BTS, BAT_BTS)
    assert matches(HYBRID | X3, BAT_BTS)
    assert matches(InverterType(0), BAT_BTS)


def test_an_unrecognised_inverter_matches_nothing_that_names_a_group() -> None:
    assert not matches(InverterType(0), PV | HYBRID)
    assert matches(InverterType(0), InverterType(0))  # an empty mask is universal
