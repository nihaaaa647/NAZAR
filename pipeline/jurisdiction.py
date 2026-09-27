"""Jurisdiction-string normalization for RBAC matching (Phase 3).

This is explicitly a demo-grade fallback, not a stable government identifier
system: MPLADS's own CSVs give no stable per-MP/district/state code that
every record reliably carries (the corpus's `mp_code`, parsed from
`LETTER_NO`, exists but only for rows with a parseable letter number - see
docs/DECISIONS.md's Phase 2 entry). Normalizing the strings (trim, casefold,
a short documented alias table for well-known official renames) reduces
false negatives from stray whitespace or a since-renamed state name, but it
is still name matching, not an authoritative registry lookup. Never present
`normalize()` output as equivalent to an official code."""
from __future__ import annotations

# Official renames/variant spellings seen across MPLADS-adjacent sources.
# Deliberately short and documented, not an exhaustive gazetteer - add an
# entry only when you can name the source of the rename.
CANONICAL_ALIASES = {
    'ORISSA': 'ODISHA',                              # renamed 2011 (Odisha (Alteration of Name) Act, 2011)
    'PONDICHERRY': 'PUDUCHERRY',                     # renamed 2006
    'UTTARANCHAL': 'UTTARAKHAND',                    # renamed 2007
    'NCT OF DELHI': 'DELHI',
    'NATIONAL CAPITAL TERRITORY OF DELHI': 'DELHI',
}


def normalize(value) -> str | None:
    """Trim + apply the alias table + casefold. None/blank -> None (never an
    empty string, which would otherwise wrongly equal another blank value)."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    canonical = CANONICAL_ALIASES.get(text.upper(), text)
    return canonical.casefold()


def matches(row_value, allowed_values) -> bool:
    """True if row_value normalizes to the same thing as any of allowed_values."""
    target = normalize(row_value)
    if target is None:
        return False
    return any(normalize(v) == target for v in allowed_values)
