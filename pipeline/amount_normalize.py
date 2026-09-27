"""Rupee amount normalization — raw value in, Decimal INR value out, with the
full parse recorded rather than discarded.

The corpus observed so far (mplads_india/**/works_*.csv) stores every amount
as a plain numeric string — no comma grouping, no unit words, no currency
symbol. This module still supports the formats the MPLADS ecosystem is known
to use elsewhere (Indian comma grouping, Rs./INR/₹ prefixes, thousand/lakh/
crore words and abbreviations) so a future source file in either format
normalizes correctly instead of silently mis-parsing — but it never *guesses*
a unit that isn't written down. An unrecognized or missing-but-needed unit
stays unresolved; see NormalizedAmount.normalization_status.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation
import math
import re

TRANSFORMATION_VERSION = 'amount-normalize-v1'

# Longest-first so "lakhs" doesn't get cut short by a "lakh" match, etc.
UNIT_MULTIPLIERS = {
    'thousand': Decimal(1_000), 'k': Decimal(1_000),
    'lakhs': Decimal(100_000), 'lakh': Decimal(100_000),
    'lacs': Decimal(100_000), 'lac': Decimal(100_000), 'l': Decimal(100_000),
    'crores': Decimal(10_000_000), 'crore': Decimal(10_000_000), 'cr': Decimal(10_000_000),
}
_UNIT_ALTS = sorted(UNIT_MULTIPLIERS, key=len, reverse=True)
UNIT_PATTERN = re.compile(r'(?<![a-z])(' + '|'.join(_UNIT_ALTS) + r')(?![a-z])', re.IGNORECASE)
CURRENCY_TOKEN = re.compile(r'(?<![a-z])(?:₹|rs\.?|inr|re\.?)(?![a-z])', re.IGNORECASE)
NUMBER_TOKEN = re.compile(r'[-+]?\d[\d,]*(?:\.\d+)?')
# Full-string Indian grouping: last group of 3 digits, then groups of 2
# (12,34,567). Only checked when the number contains a comma at all - an
# uncommaed run of digits of any length (this dataset's actual format,
# e.g. "1010000") needs no grouping validation.
INDIAN_GROUPING = re.compile(r'^[-+]?\d{1,2}(,\d{2})*,\d{3}(\.\d+)?$')

# Statuses:
#  ok                 - a single unambiguous number, unit resolved (explicit or the
#                        dataset's documented bare-number-is-INR convention).
#  missing             - raw value was empty/null.
#  unparseable          - no single clean number could be extracted (garbled text,
#                        multiple numbers, invalid comma grouping, etc).
#  ambiguous_unit      - a number was found but its unit could not be resolved
#                        (conflicting/duplicate unit words). Never guessed from
#                        magnitude.


@dataclass
class NormalizedAmount:
    raw_value: str | None
    raw_unit: str | None
    parsed_value: Decimal | None
    normalized_inr: Decimal | None
    unit_source: str | None
    normalization_status: str
    transformation_version: str = TRANSFORMATION_VERSION

    def to_dict(self) -> dict:
        d = asdict(self)
        d['parsed_value'] = str(self.parsed_value) if self.parsed_value is not None else None
        d['normalized_inr'] = str(self.normalized_inr) if self.normalized_inr is not None else None
        return d


def _is_missing(raw) -> bool:
    if raw is None:
        return True
    if isinstance(raw, float) and math.isnan(raw):
        return True
    text = str(raw).strip()
    return text == '' or text.lower() in ('nan', 'none', 'na', '<na>')


def normalize_amount(raw) -> NormalizedAmount:
    """Parse one raw amount value. Uses Decimal throughout — never float — so a
    normalized value is exact down to the paisa. Ambiguous unit -> the parsed
    number is kept (for lineage/display) but normalized_inr stays None so the
    value is excluded from any cost-based detector that reads normalized_inr."""
    if _is_missing(raw):
        return NormalizedAmount(raw_value=None, raw_unit=None, parsed_value=None,
                                 normalized_inr=None, unit_source=None, normalization_status='missing')
    text = str(raw).strip()
    cleaned = CURRENCY_TOKEN.sub('', text)
    cleaned = cleaned.replace('/-', '').strip()
    unit_matches = [m.group(1).lower() for m in UNIT_PATTERN.finditer(cleaned)]
    numberless = UNIT_PATTERN.sub('', cleaned)
    numberless = CURRENCY_TOKEN.sub('', numberless).strip()
    number_matches = NUMBER_TOKEN.findall(numberless)
    if len(number_matches) != 1:
        return NormalizedAmount(raw_value=text, raw_unit=None, parsed_value=None, normalized_inr=None,
                                 unit_source=None, normalization_status='unparseable')
    number_text = number_matches[0]
    if ',' in number_text and not INDIAN_GROUPING.match(number_text):
        # Comma-grouped but not valid Indian grouping (e.g. Western 1,234,567)
        # - not a format this normalizer resolves; preserve raw, flag it.
        return NormalizedAmount(raw_value=text, raw_unit=None, parsed_value=None, normalized_inr=None,
                                 unit_source=None, normalization_status='unparseable')
    try:
        parsed = Decimal(number_text.replace(',', ''))
    except InvalidOperation:
        return NormalizedAmount(raw_value=text, raw_unit=None, parsed_value=None, normalized_inr=None,
                                 unit_source=None, normalization_status='unparseable')
    distinct_units = set(unit_matches)
    if len(distinct_units) > 1:
        # Conflicting unit words in the same value (e.g. "5 lakh 2 crore") - the
        # amount cannot be resolved to a single INR figure without guessing.
        return NormalizedAmount(raw_value=text, raw_unit=','.join(sorted(distinct_units)), parsed_value=parsed,
                                 normalized_inr=None, unit_source='conflicting_unit_tokens',
                                 normalization_status='ambiguous_unit')
    if distinct_units:
        unit = next(iter(distinct_units))
        return NormalizedAmount(raw_value=text, raw_unit=unit, parsed_value=parsed,
                                 normalized_inr=parsed * UNIT_MULTIPLIERS[unit], unit_source='explicit_unit_text',
                                 normalization_status='ok')
    # No unit word and no currency symbol survives past this point either - by
    # this dataset's documented convention (every observed ACTUAL_AMOUNT /
    # SANCTION_AMOUNT is a bare rupee figure) a bare number is treated as INR
    # outright, not inferred from its size.
    return NormalizedAmount(raw_value=text, raw_unit=None, parsed_value=parsed, normalized_inr=parsed,
                             unit_source='implicit_bare_number_is_inr', normalization_status='ok')


def normalize_amount_series(series) -> list[NormalizedAmount]:
    return [normalize_amount(v) for v in series]
