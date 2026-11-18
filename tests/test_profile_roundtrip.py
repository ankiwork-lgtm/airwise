import json

from hypothesis import given, settings

from airwise.models import HouseholdProfile
from tests.strategies import profiles


# Feature: airwise, Property 6: Household_Profile JSON round trip
# **Validates: Requirements 4.8**
@settings(max_examples=100)
@given(profiles())
def test_profile_json_round_trip(profile: HouseholdProfile):
    text = json.dumps(profile.model_dump(mode="json"))
    assert HouseholdProfile.model_validate_json(text) == profile
