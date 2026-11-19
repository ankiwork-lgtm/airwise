"""Unit tests for the Impact_Engine (Requirements 5.11, 5.12, 13.1)."""

import pytest

from airwise.errors import InvalidInput
from airwise.models import AirReading, HouseholdProfile
from airwise.services.impact import RULES, compute_impact


def _reading(aqi: int) -> AirReading:
    return AirReading(
        location_name="Delhi",
        latitude=28.6,
        longitude=77.2,
        pm2_5=10.0,
        pm10=20.0,
        aqi=aqi,
        band="Good",
        grap_stage="none",
        source="live",
    )


CLEAN_PROFILE = HouseholdProfile(
    city="Delhi",
    kids=False,
    elderly=False,
    respiratory=False,
    commute="walk_cycle",
    cooking_fuel="lpg",
    heating="none",
    has_purifier=True,
    ventilation="mostly_closed",
)

WORST_PROFILE = HouseholdProfile(
    city="Delhi",
    kids=True,
    elderly=True,
    respiratory=True,
    commute="car",
    cooking_fuel="biomass",
    heating="biomass_burning",
    has_purifier=False,
    ventilation="open_often",
)


def test_clean_air_profile_gives_no_rows_and_zero_score():
    result = compute_impact(CLEAN_PROFILE, _reading(50))
    assert result.rows == []
    assert result.exposure_score == 0


def test_worst_case_profile_gives_all_nine_rows():
    result = compute_impact(WORST_PROFILE, _reading(400))
    assert len(RULES) == 9
    assert len(result.rows) == 9
    assert [r.id for r in result.rows] == [r.id for r in RULES]
    assert 0 < result.exposure_score <= 100


def test_same_inputs_give_same_output():
    assert compute_impact(WORST_PROFILE, _reading(400)) == compute_impact(
        WORST_PROFILE, _reading(400)
    )


@pytest.mark.parametrize(
    "profile, reading, field",
    [
        (None, _reading(50), "profile"),
        ({"city": "Delhi"}, _reading(50), "profile"),
        (CLEAN_PROFILE, None, "reading"),
        (CLEAN_PROFILE, {"aqi": 50}, "reading"),
        (
            CLEAN_PROFILE,
            AirReading.model_construct(**{**_reading(50).model_dump(), "aqi": 9999}),
            "aqi",
        ),
        (
            CLEAN_PROFILE,
            AirReading.model_construct(**{**_reading(50).model_dump(), "aqi": -1}),
            "aqi",
        ),
        (
            HouseholdProfile.model_construct(
                **{**CLEAN_PROFILE.model_dump(), "commute": "teleport"}
            ),
            _reading(50),
            "commute",
        ),
        (
            HouseholdProfile.model_construct(**{**CLEAN_PROFILE.model_dump(), "city": ""}),
            _reading(50),
            "city",
        ),
    ],
)
def test_invalid_direct_inputs_raise_invalid_input_and_return_nothing(profile, reading, field):
    result = None
    with pytest.raises(InvalidInput) as exc_info:
        result = compute_impact(profile, reading)
    assert result is None
    assert field in exc_info.value.fields
