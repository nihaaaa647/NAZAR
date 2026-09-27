"""Phase 4 section J: conditional satellite change-screening eligibility gate.

This module makes ONE decision: given what's known about a work's location,
its available before/after imagery, and its asset category, should a
satellite change-detection result even be attempted/shown at all? It never
runs change detection itself (see ml/cv/satellite_change.py, built earlier
for this project's Branch A/B satellite module) and never modifies that
module's files - it's a standalone, additive gate any caller can run the
already-available inputs through before deciding whether to display a
result. Deliberately conservative: small assets (a toilet, a borewell, a
streetlight, a minor drain, indoor renovation) are assumed below Sentinel-2's
~10m/pixel resolution unless proven otherwise, per the Phase 4 instructions.

None of ELIGIBILITY_STATUSES other than 'eligible' are risk signals - they
are reasons a check could not be attempted, exactly like
pipeline/detection_contract.py's 'unavailable' status, and must never be
silently treated as "no change found"."""
from __future__ import annotations

from dataclasses import dataclass, field

ELIGIBILITY_STATUSES = frozenset({
    'eligible', 'location_unavailable', 'geocode_low_confidence', 'imagery_unavailable',
    'cloud_obstructed', 'asset_below_resolution', 'inconclusive',
})

# Sentinel-2 true-colour bands (what pipeline/fetch_satellite_pairs.py pulls)
# are ~10m/pixel - the one resolution figure this module treats as ground
# truth about the imagery source actually in use.
SATELLITE_RESOLUTION_M = 10
# Minimum plausible footprint (metres, smaller dimension) for a category to
# be visible at all at that resolution - conservative, erring toward
# 'asset_below_resolution' rather than a false confident result. Categories
# not listed default to "unknown" -> 'inconclusive', never assumed eligible.
# Keyed by exact lowercase category AND matched by keyword (real source data
# is free-text, e.g. "Installing tube-wells and borewells", "Street lights") -
# see _visible_size_for_category below.
ASSET_MIN_VISIBLE_SIZE_M = {
    'road': 20, 'building': 15, 'community_hall': 15, 'community_centre': 15, 'dam': 30,
    'pond': 20, 'playground': 25, 'gym': 10, 'laborator': 10, 'cctv': 1,
    'toilet': 3, 'bore_well': 2, 'borewell': 2, 'tube_well': 2, 'streetlight': 1, 'street_light': 1,
    'light': 1, 'drain_minor': 2, 'indoor_renovation': 0, 'hand_pump': 1, 'furniture': 0,
}
# Ordered (longest/most-specific keyword first) so e.g. "community centre"
# matches before a shorter, less specific keyword might.
_CATEGORY_KEYWORDS = sorted(ASSET_MIN_VISIBLE_SIZE_M, key=len, reverse=True)


def _visible_size_for_category(asset_category: str | None) -> float | None:
    if not asset_category:
        return None
    text = asset_category.lower().replace('-', ' ').replace('_', ' ')
    exact = ASSET_MIN_VISIBLE_SIZE_M.get(text.replace(' ', '_'))
    if exact is not None:
        return exact
    for keyword in _CATEGORY_KEYWORDS:
        if keyword.replace('_', ' ') in text:
            return ASSET_MIN_VISIBLE_SIZE_M[keyword]
    return None
DEFAULT_MAX_CLOUD_COVER_PCT = 30  # matches pipeline/fetch_satellite_pairs.py's existing STAC query filter.
DEFAULT_MIN_GEOCODE_CONFIDENCE = 0.6  # below this, a coordinate is not trusted enough to screen against.
# How many days a project's own completion window may differ from the
# available before/after imagery dates and still be considered "aligned" -
# imagery from years off the actual work timeline can't screen it.
DEFAULT_MAX_IMAGERY_DATE_SKEW_DAYS = 365


@dataclass
class SatelliteEligibility:
    status: str
    reason: str
    resolution_m: float | None = None
    asset_min_visible_size_m: float | None = None
    cloud_cover_pct: float | None = None
    geocode_confidence: float | None = None


def check_eligibility(*, has_coordinates: bool, geocode_confidence: float | None,
                       has_before_image: bool, has_after_image: bool,
                       imagery_date_skew_days: float | None, cloud_cover_pct: float | None,
                       asset_category: str | None, asset_min_dimension_m: float | None = None,
                       min_geocode_confidence: float = DEFAULT_MIN_GEOCODE_CONFIDENCE,
                       max_cloud_cover_pct: float = DEFAULT_MAX_CLOUD_COVER_PCT,
                       max_imagery_date_skew_days: float = DEFAULT_MAX_IMAGERY_DATE_SKEW_DAYS,
                       resolution_m: float = SATELLITE_RESOLUTION_M) -> SatelliteEligibility:
    """Every gate is checked independently and in the order the Phase 4 brief
    lists them; the first one that fails determines the status. Order
    matters for the REASON shown to a reviewer, not for correctness - a work
    failing multiple gates still just needs one fixed to move to the next."""
    if not has_coordinates:
        return SatelliteEligibility('location_unavailable', 'No coordinates are recorded or geocoded for this work.')
    if geocode_confidence is None or geocode_confidence < min_geocode_confidence:
        return SatelliteEligibility('geocode_low_confidence',
                                     f'Coordinate confidence ({geocode_confidence}) is below the {min_geocode_confidence} floor for screening.',
                                     geocode_confidence=geocode_confidence)
    if not (has_before_image and has_after_image):
        return SatelliteEligibility('imagery_unavailable', 'No suitable before/after imagery pair is available for this location.')
    if imagery_date_skew_days is not None and imagery_date_skew_days > max_imagery_date_skew_days:
        return SatelliteEligibility('imagery_unavailable',
                                     f'Available imagery is {imagery_date_skew_days:.0f} days off the project timeline - beyond the '
                                     f'{max_imagery_date_skew_days:.0f}-day alignment window.')
    if cloud_cover_pct is not None and cloud_cover_pct > max_cloud_cover_pct:
        return SatelliteEligibility('cloud_obstructed', f'Cloud cover ({cloud_cover_pct:.0f}%) exceeds the '
                                     f'{max_cloud_cover_pct:.0f}% usable-imagery threshold.', cloud_cover_pct=cloud_cover_pct)
    min_size = asset_min_dimension_m if asset_min_dimension_m is not None else _visible_size_for_category(asset_category)
    if min_size is None:
        return SatelliteEligibility('inconclusive', f'No known visibility floor for asset category {asset_category!r} - '
                                     'cannot determine whether it would be visible at the available resolution.',
                                     resolution_m=resolution_m)
    if min_size < resolution_m:
        return SatelliteEligibility('asset_below_resolution',
                                     f'{asset_category} typically spans ~{min_size}m - below the {resolution_m}m/pixel '
                                     'resolution of the available imagery. A small asset like this is not expected to be '
                                     'visible regardless of whether the work exists.',
                                     resolution_m=resolution_m, asset_min_visible_size_m=min_size)
    return SatelliteEligibility('eligible', 'Coordinates, imagery and asset size all support attempting a screening.',
                                 resolution_m=resolution_m, asset_min_visible_size_m=min_size,
                                 cloud_cover_pct=cloud_cover_pct, geocode_confidence=geocode_confidence)


# Language constants - used verbatim by callers so the wording specified in
# the Phase 4 brief is never paraphrased into something stronger.
CHANGE_DETECTED_LANGUAGE = 'Visible change detected near the reported location.'
NO_CHANGE_LANGUAGE = 'No reliable change visible at the available resolution.'
# Never say this - a screening result cannot prove non-existence:
FORBIDDEN_CLAIM = 'The project was not built.'
