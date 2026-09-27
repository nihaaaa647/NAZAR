"""Data-quality engine: turns the ingestion pipeline's per-row validation
codes and amount normalization results into standalone quality alerts.

These alerts never contribute to fraud risk. They are a separate signal
about how much analytical confidence a record deserves, kept structurally
apart from signals_json / risk_score (see backend/main.py's /works and
/quality endpoints, which never share a table or a score).

## Trigger table - exact condition for every quality code

| code                          | severity | fires when                                                                                          |
|-------------------------------|----------|-------------------------------------------------------------------------------------------------------|
| work_id_missing               | critical | `has_completed_record` is true and `work_id` is blank (sanctioned-only rows never fire this - no portal WORK_ID exists yet by construction). |
| work_id_duplicate             | critical | the same non-blank `work_id` appears on more than one `WORK_RECOMMENDATION_DTL_ID`.                  |
| amount_parsing_failed         | critical | `amount_normalize.normalize_amount` returns `unparseable` for `actual_amount`/`sanction_amount`.      |
| amount_unit_ambiguous         | warning  | `amount_normalize.normalize_amount` returns `ambiguous_unit` (a number parsed but its unit did not resolve to one INR figure). |
| amount_missing                | warning  | the field is expected (`has_completed_record` for actual_amount, `has_sanctioned_record` for sanction_amount) and the raw value is blank. |
| amount_negative                | critical | the normalized amount parses and is < 0.                                                              |
| amount_zero                    | warning  | the normalized amount parses and equals 0.                                                            |
| date_missing_or_invalid       | warning  | the field is expected (per the same has_completed/has_sanctioned rule as amounts) and could not be parsed as a date. |
| date_sequence_invalid          | critical | `actual_end_date < sanction_date` (completion before sanction) or `sanction_date < recommendation_date` (sanction before recommendation) - a direct chronological impossibility, not an inference. |
| location_missing_or_invalid   | warning  | `state_name` or `constituency` is blank.                                                              |
| category_unknown              | info     | `work_category` is blank, or (when a `known_categories` set is supplied) not a member of it.          |
| record_malformed              | critical | `work_description`, `mp_name` and `state_name` are all blank on the same row - too little survived ingestion to identify the record at all. |
| image_expected_missing        | info     | the ingest-time `attachment_missing` check fired: a filename listed in `local_image_filenames` does not exist on disk. |
| sanctioned_stage_incomplete   | info     | both a completed and a sanctioned record exist for this work, and the *sanctioned-table's own* `WORK_STAGE` field is not `'Work Completed'`. This is a completeness note about one shadow field, not a staleness claim - the corpus carries no reliable per-record update timestamp and no defensible expected update interval, so `SOURCE_RECORD_STALE` is never used here (see docs/DECISIONS.md, 2026-09-25 Phase 2 entry). It never touches `affected_analyses` because the canonical `work_stage` this app actually uses is already overridden to `'Work Completed'` whenever `has_completed_record` is true (pipelines/ingest.py) - only the sanctioned table's own copy lags. |

`affected_analyses` lists which fraud-review signals (backend/main.py's
`SIGNAL_LABELS` keys) would be corrupted if the raw/ambiguous value were used
directly instead of being excluded - not "this record is risky."
"""
from __future__ import annotations

import hashlib
import json

QUALITY_DETECTOR_VERSION = 'quality-checks-v2'

# code -> (severity, human explanation template, affected analyses, recommended action)
_SPEC = {
    'work_id_missing': ('critical', 'This record has no WORK_ID.',
                         ['cost_peer', 'missing_evidence', 'anomaly', 'photo_identical',
                          'photo_similar', 'text_exact', 'text_similar', 'entitlement_pace'],
                         'Trace the record back to its source CSV and confirm the correct WORK_ID before it enters any analysis.'),
    'work_id_duplicate': ('critical', 'This WORK_ID appears on more than one canonical record.',
                           ['cost_peer', 'missing_evidence', 'anomaly', 'photo_identical',
                            'photo_similar', 'text_exact', 'text_similar', 'entitlement_pace'],
                           'Confirm which record is authoritative; a duplicated WORK_ID can double-count one work or silently merge two different works.'),
    'amount_parsing_failed': ('critical', 'The amount could not be parsed into a number.',
                               ['cost_peer', 'anomaly', 'entitlement_pace'],
                               'Check the source value against the portal; the raw text does not match any supported amount format.'),
    'amount_unit_ambiguous': ('warning', 'The amount has a unit that could not be resolved to a single INR figure.',
                               ['cost_peer', 'anomaly', 'entitlement_pace'],
                               'Confirm the intended unit at the source; the value is excluded from cost-based analyses until resolved.'),
    'amount_missing': ('warning', 'No amount value is present where one is expected.',
                        ['cost_peer', 'anomaly', 'entitlement_pace'],
                        'Confirm whether the amount is genuinely unrecorded or was dropped during ingestion.'),
    'amount_negative': ('critical', 'The amount is negative.',
                         ['cost_peer', 'anomaly', 'entitlement_pace'],
                         'A negative amount is not a valid sanction/expenditure figure; verify against the source record.'),
    'amount_zero': ('warning', 'The amount is exactly zero.',
                     ['cost_peer', 'anomaly', 'entitlement_pace'],
                     'Confirm whether zero is a genuine value (e.g. a cancelled work) or a missing figure recorded as 0.'),
    'date_missing_or_invalid': ('warning', 'An expected date is missing or could not be parsed.',
                                 ['anomaly'],
                                 'Confirm the date at the source; duration-based analyses cannot use this record until it is fixed.'),
    'date_sequence_invalid': ('critical', 'This record’s dates are out of the order they should occur in.',
                               ['anomaly'],
                               'Verify the recorded dates against the source portal; an impossible sequence usually means a data-entry error.'),
    'location_missing_or_invalid': ('warning', 'State or constituency is missing.',
                                     ['cost_peer', 'anomaly'],
                                     'Confirm the location fields at the source; peer-group comparisons need a valid state and constituency.'),
    'category_unknown': ('info', 'Work category is missing or not recognized.',
                          ['cost_peer'],
                          'Confirm the work category at the source so this record can be grouped with the right cost peers.'),
    'record_malformed': ('critical', 'This record is missing core identifying fields.',
                          ['cost_peer', 'missing_evidence', 'anomaly', 'photo_identical',
                           'photo_similar', 'text_exact', 'text_similar', 'entitlement_pace'],
                          'This record needs to be re-extracted from source; too little identifying information survived ingestion.'),
    'image_expected_missing': ('info', 'A listed attachment file could not be found where expected.',
                                ['missing_evidence', 'photo_identical', 'photo_similar'],
                                'Confirm the attachment was actually uploaded to the source portal, or re-run the image download step.'),
    'sanctioned_stage_incomplete': ('info', 'The sanctioned-table record’s own WORK_STAGE field was never updated to ‘Work Completed’, even though a completed-table record for this work exists.',
                                     [],
                                     'No action needed for review purposes - the app already uses the completed-table record’s status. Worth fixing only if the sanctioned-table export itself is being corrected at the source.'),
}

QUALITY_CODES = frozenset(_SPEC)


def _fingerprint(raw_value) -> str:
    text = '' if raw_value is None else str(raw_value)
    return hashlib.sha1(text.encode('utf-8')).hexdigest()[:8]


def alert_id(work_id: str, quality_code: str, field: str, raw_value=None) -> str:
    """Stable id across identical pipeline reruns: (work_id, quality_code,
    field) pin down *which* issue this is, and a short fingerprint of the raw
    value pins down *which state* of that issue this is. A resolution
    recorded against one id keeps matching after a rerun as long as nothing
    about the underlying value changed. If the raw value later changes, this
    function returns a different id - the previous id's resolution is never
    deleted (it stays in the resolutions/audit store as history for the old
    value), and a new, currently-open alert is generated for the new value.
    See tests/test_data_quality.py::test_resolution_survives_identical_rerun
    and ::test_raw_value_change_creates_new_alert_and_keeps_history."""
    digest = hashlib.sha1(f'{work_id}\x1f{quality_code}\x1f{field}\x1f{_fingerprint(raw_value)}'.encode('utf-8')).hexdigest()
    return digest[:16]


def make_alert(work_id, quality_code, field, raw_value, *, detector_version=QUALITY_DETECTOR_VERSION,
               explanation=None, extra_context=None, jurisdiction=None) -> dict:
    severity, default_explanation, affected_analyses, recommended_action = _SPEC[quality_code]
    text = explanation or default_explanation
    if extra_context:
        text = f'{text} {extra_context}'
    j = jurisdiction or {}
    return {
        'id': alert_id(str(work_id), quality_code, field, raw_value),
        'work_id': None if work_id is None else str(work_id),
        'quality_code': quality_code,
        'severity': severity,
        'field': field,
        'raw_value': None if raw_value is None else str(raw_value),
        'explanation': text,
        'affected_analyses': list(affected_analyses),
        'recommended_action': recommended_action,
        'status': 'open',
        'detector_version': detector_version,
        # Coarse grouping key so a UI can collapse many alerts that share the
        # same rule+field (e.g. thousands of identical low-severity notes)
        # into one root-cause group instead of listing each individually.
        'group_key': f'{quality_code}|{field}',
        'mp_name': j.get('mp_name'), 'state_name': j.get('state_name'), 'constituency': j.get('constituency'),
    }


def _blank(value) -> bool:
    if value is None:
        return True
    try:
        import pandas as pd
        if pd.isna(value):
            return True
    except (ImportError, TypeError, ValueError):
        pass
    return str(value).strip() == ''


def run_quality_checks(df, *, known_categories: set | None = None,
                        detector_version: str = QUALITY_DETECTOR_VERSION) -> list[dict]:
    """df is pipelines.ingest.build_works's canonical `out` frame (or anything
    with the same column names): one row per WORK_RECOMMENDATION_DTL_ID,
    amount/date fields already split into *_raw and normalized, plus
    validation_issues (the ingest-time per-row code list). See the module
    docstring for the exact trigger condition of every code below."""
    alerts: list[dict] = []

    seen_work_ids: dict = {}
    for _, row in df.iterrows():
        work_id = row.get('work_id')
        record_id = row.get('record_id')
        display_id = None if _blank(work_id) else str(work_id)
        key_id = display_id or (None if _blank(record_id) else f'record:{record_id}')
        jurisdiction = {'mp_name': None if _blank(row.get('mp_name')) else str(row.get('mp_name')),
                         'state_name': None if _blank(row.get('state_name')) else str(row.get('state_name')),
                         'constituency': None if _blank(row.get('constituency')) else str(row.get('constituency'))}

        def add(quality_code, field, raw_value, **kw):
            alerts.append(make_alert(key_id, quality_code, field, raw_value, jurisdiction=jurisdiction, **kw))

        if _blank(work_id):
            # A sanctioned-only record has no portal-assigned WORK_ID yet by
            # construction (it's issued once the work is marked complete) -
            # only flag this for records that should already have one.
            if row.get('has_completed_record'):
                add('work_id_missing', 'work_id', row.get('work_id'))
        else:
            seen_work_ids.setdefault(str(work_id), []).append((record_id, jurisdiction))

        if _blank(row.get('work_description')) and _blank(row.get('mp_name')) and _blank(row.get('state_name')):
            add('record_malformed', 'record', f'record_id={record_id}',
                extra_context='WORK_DESCRIPTION, MP_NAME and STATE_NAME are all missing.')

        for amount_field in ('actual_amount', 'sanction_amount'):
            status = row.get(f'{amount_field}_status')
            raw = row.get(f'{amount_field}_raw')
            if status == 'unparseable':
                add('amount_parsing_failed', amount_field, raw)
            elif status == 'ambiguous_unit':
                unit = row.get(f'{amount_field}_raw_unit')
                add('amount_unit_ambiguous', amount_field, raw,
                    extra_context=f'Conflicting unit text: {unit}.' if unit else None)
            expected = row.get('has_completed_record') if amount_field == 'actual_amount' else row.get('has_sanctioned_record')
            value = row.get(amount_field)
            if expected and status == 'missing':
                add('amount_missing', amount_field, raw)
            if value is not None and not _blank(value):
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    numeric = None
                if numeric is not None:
                    if numeric < 0:
                        add('amount_negative', amount_field, raw)
                    elif numeric == 0:
                        add('amount_zero', amount_field, raw)

        for date_field, expected_flag in (('actual_end_date', 'has_completed_record'),
                                           ('sanction_date', 'has_sanctioned_record'),
                                           ('recommendation_date', 'has_sanctioned_record')):
            if row.get(expected_flag) and _blank(row.get(date_field)):
                add('date_missing_or_invalid', date_field, row.get(f'{date_field}_raw'))

        issues = row.get('validation_issues')
        codes = json.loads(issues) if isinstance(issues, str) else (issues or [])
        if 'completion_before_sanction' in codes:
            add('date_sequence_invalid', 'actual_end_date',
                f'{row.get("actual_end_date_raw")} before {row.get("sanction_date_raw")}',
                extra_context='Completion date falls before the sanction date.')
        if 'sanction_before_recommendation' in codes:
            add('date_sequence_invalid', 'sanction_date',
                f'{row.get("sanction_date_raw")} before {row.get("recommendation_date_raw")}',
                extra_context='Sanction date falls before the recommendation date.')
        if 'attachment_missing' in codes:
            add('image_expected_missing', 'attachment_filenames', row.get('attachment_filenames'))
        if 'source_stage_disagreement' in codes:
            add('sanctioned_stage_incomplete', 'work_stage', row.get('sanctioned_work_stage'))

        if _blank(row.get('state_name')) or _blank(row.get('constituency')):
            add('location_missing_or_invalid', 'state_name/constituency',
                f'state={row.get("state_name")!r} constituency={row.get("constituency")!r}')

        category = row.get('work_category')
        if _blank(category) or (known_categories is not None and str(category).strip().upper() not in known_categories):
            add('category_unknown', 'work_category', category)

    for wid, occurrences in seen_work_ids.items():
        if len(occurrences) > 1:
            record_ids = [r for r, _ in occurrences]
            alerts.append(make_alert(wid, 'work_id_duplicate', 'work_id', wid, jurisdiction=occurrences[0][1],
                                      extra_context=f'{len(record_ids)} source records share this WORK_ID: {sorted(str(r) for r in record_ids)}.'))

    for a in alerts:
        a['detector_version'] = detector_version
    return alerts
