from decimal import Decimal

import pytest

from pipeline.amount_normalize import normalize_amount


def test_plain_dataset_format_is_unchanged():
    r = normalize_amount('1010000.0')
    assert r.normalization_status == 'ok'
    assert r.normalized_inr == Decimal('1010000.0')
    assert r.unit_source == 'implicit_bare_number_is_inr'


def test_indian_comma_grouping():
    r = normalize_amount('12,34,567')
    assert r.normalization_status == 'ok'
    assert r.normalized_inr == Decimal('1234567')


def test_western_comma_grouping_is_not_supported():
    r = normalize_amount('1,234,567')
    assert r.normalization_status == 'unparseable'
    assert r.normalized_inr is None


@pytest.mark.parametrize('raw,expected', [
    ('Rs. 5 Lakh', Decimal('500000')),
    ('₹12.5 Cr', Decimal('125000000')),
    ('5L', Decimal('500000')),
    ('2Cr', Decimal('20000000')),
    ('1.5 thousand', Decimal('1500')),
    ('3 lakhs', Decimal('300000')),
    ('50000/-', Decimal('50000')),
])
def test_unit_and_currency_variants(raw, expected):
    r = normalize_amount(raw)
    assert r.normalization_status == 'ok'
    assert r.normalized_inr == expected


def test_conflicting_units_are_ambiguous_not_guessed():
    r = normalize_amount('5 lakh crore')
    assert r.normalization_status == 'ambiguous_unit'
    assert r.normalized_inr is None
    # The parsed number is preserved even though the unit isn't resolved.
    assert r.parsed_value == Decimal('5')


def test_missing_value():
    for raw in (None, '', '   ', float('nan')):
        r = normalize_amount(raw)
        assert r.normalization_status == 'missing'
        assert r.normalized_inr is None


def test_garbled_text_is_unparseable_not_zero():
    r = normalize_amount('N/A')
    assert r.normalization_status == 'unparseable'
    assert r.normalized_inr is None


def test_negative_and_zero_round_trip_exactly():
    assert normalize_amount('-5').normalized_inr == Decimal('-5')
    assert normalize_amount('0').normalized_inr == Decimal('0')


def test_uses_decimal_not_float():
    # A value float can't represent exactly - Decimal must round-trip it exactly.
    r = normalize_amount('0.1')
    assert r.normalized_inr == Decimal('0.1')
    assert isinstance(r.normalized_inr, Decimal)


def test_never_infers_unit_from_magnitude():
    # A huge bare number never gets treated as crore/lakh just because it's
    # large - only an explicit unit word changes the multiplier.
    r = normalize_amount('50000000')
    assert r.unit_source == 'implicit_bare_number_is_inr'
    assert r.normalized_inr == Decimal('50000000')
