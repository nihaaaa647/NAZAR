from pipeline.satellite_eligibility import (
    check_eligibility, ELIGIBILITY_STATUSES, CHANGE_DETECTED_LANGUAGE, NO_CHANGE_LANGUAGE, FORBIDDEN_CLAIM,
)

BASE = dict(has_coordinates=True, geocode_confidence=0.9, has_before_image=True, has_after_image=True,
            imagery_date_skew_days=10, cloud_cover_pct=5, asset_category='road')


def test_eligible_when_every_gate_passes():
    result = check_eligibility(**BASE)
    assert result.status == 'eligible'


def test_missing_coordinates_is_location_unavailable():
    result = check_eligibility(**{**BASE, 'has_coordinates': False})
    assert result.status == 'location_unavailable'


def test_low_confidence_coordinates_gated_separately_from_missing():
    result = check_eligibility(**{**BASE, 'geocode_confidence': 0.2})
    assert result.status == 'geocode_low_confidence'
    # Distinct from location_unavailable - a coordinate exists, it's just untrustworthy.
    assert result.status != 'location_unavailable'


def test_missing_imagery_is_imagery_unavailable():
    result = check_eligibility(**{**BASE, 'has_after_image': False})
    assert result.status == 'imagery_unavailable'


def test_imagery_misaligned_with_project_timeline_is_imagery_unavailable():
    result = check_eligibility(**{**BASE, 'imagery_date_skew_days': 2000})
    assert result.status == 'imagery_unavailable'


def test_cloud_cover_gates_independently_of_imagery_presence():
    result = check_eligibility(**{**BASE, 'cloud_cover_pct': 95})
    assert result.status == 'cloud_obstructed'


def test_small_asset_categories_are_below_resolution():
    for category in ('toilet', 'borewell', 'streetlight', 'drain_minor', 'indoor_renovation'):
        result = check_eligibility(**{**BASE, 'asset_category': category})
        assert result.status == 'asset_below_resolution', category


def test_large_asset_categories_are_eligible():
    for category in ('road', 'building', 'dam'):
        result = check_eligibility(**{**BASE, 'asset_category': category})
        assert result.status == 'eligible', category


def test_unknown_asset_category_is_inconclusive_not_eligible():
    result = check_eligibility(**{**BASE, 'asset_category': 'mystery_category'})
    assert result.status == 'inconclusive'


def test_none_of_the_non_eligible_statuses_are_risk_signals():
    # Every status is a defined, non-scoring gate outcome - there is no
    # numeric score or risk field on the dataclass at all.
    result = check_eligibility(**{**BASE, 'has_coordinates': False})
    assert not hasattr(result, 'score')
    assert not hasattr(result, 'risk_eligible')


def test_all_statuses_are_declared():
    assert check_eligibility(**BASE).status in ELIGIBILITY_STATUSES


def test_language_constants_never_declare_non_existence():
    assert 'not built' not in CHANGE_DETECTED_LANGUAGE.lower()
    assert 'not built' not in NO_CHANGE_LANGUAGE.lower()
    assert FORBIDDEN_CLAIM == 'The project was not built.'  # documented as forbidden, not used by any caller
