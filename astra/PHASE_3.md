# PHASE 3 — Deterministic Engines: Rules, Idle Funds, Absorption Forecast

Assumes the repository produced by Phase 2: canonical data loaded, evaluation harness and
metrics in place, injected cases available.

## OBJECTIVE

Implement blueprint Engines 1, 5 and 6 — the interpretable, zero-training layer that the
government audience actually needs — and measure each against the harness.

## CONTEXT

Corrections 1, 4, 5, 6, 7 and 9 from the master prompt land here. In particular: the rule
engine's legal content changes. The unsourced ₹10 lakh threshold is out as a legal claim; the
75-day recommendation-to-sanction deadline, the ₹5 crore entitlement, the ₹75 lakh
trust/society ceiling and the ₹25 lakh outside-constituency limit are in.

## TASKS

1. **Engine 1 — PolicyCode MPLADS** (`ml/rules/`). Each rule is a self-contained unit
   declaring: id, human-readable name, legal source (or `heuristic` with no source), the
   predicate, the threshold and where the threshold came from, the officer-readable
   explanation template, and the severity tier. Implement:
   - **Sanction-deadline breach**: `sanction_date - recommendation_date > 75 days`
     (MPLADS Guidelines 2023). Sourced, dated, citable. Report the observed distribution of
     this gap before setting anything.
   - **Sequencing integrity**: recommendation → sanction → completion must be monotonic;
     `LETTER_NO` must exist and parse.
   - **Cost-per-unit outlier**: robust z-score / MAD within `peer_group_key`, with the
     fallback ladder and a minimum group size. State the group size on every flag.
   - **Implausibly fast execution**: `duration_days` below the peer group's low percentile,
     using the real `SANCTION_DATE` where available and the proxy (labelled) where not.
   - **Missing completion evidence**: zero attachments, or only `junk_watermark` attachments,
     on a completed work. Note that ~37% of rows have zero attachments — this is a low-weight
     advisory signal, not a phantom-work accusation. Say so in the explanation string.
   - **Underspend vs sanction**: `actual_amount` materially below `sanction_amount`
     (short-execution pattern). Also implement the sanction-**breach** check and expect zero
     (Correction 7); report it as a verified-clean control.
   - **Non-standard implementing agency**: classify `IDA_NAME` into district collector /
     municipal / zilla parishad / PWD division / trust / cooperative society / other. Report
     the distribution before trusting the classifier, and apply the ₹75 lakh
     trust/society ceiling where the type is trust or society.
   - **Fiscal-year-end clustering**: share of an MP's or agency's completions in the final
     ~45 days of the fiscal year versus the peer average.
   - Optionally, as an explicitly unsourced heuristic: round-number and just-under-round-number
     amount clustering (717 of 5,133 amounts are exact ₹1 lakh multiples).
2. **Engine 5 — Idle Sanctioned-Fund Detector** (`ml/rules/idle_funds.py`). Rebuilt on
   `WORK_STAGE` and real `SANCTION_DATE`, not `FILE_STATUS`. Peer-percentile threshold among
   works at a comparable stage. Output must be labelled "needs inquiry", never fraud.
   Coverage is limited by the sanctioned-table backfill — state the coverage on the output.
3. **Engine 6 — Fund-Absorption Forecast** (`ml/forecast/`). Utilisation computed against the
   ₹5 crore per-MP annual entitlement (cite the guideline), using sanctioned **and** completed
   amounts. Simple trend extrapolation, a confidence band, and an explicit low-confidence
   label given roughly two fiscal years of partial data. This is a portfolio KPI, not a
   per-work fraud signal.
4. Every rule writes a `risk_signal` row with `engine_name`, `raw_score`,
   `normalized_score` in [0,1], `rule_triggered`, and a `detail_json` carrying the numbers
   behind the explanation.
5. Run the harness. Record per-rule flag rate over the real corpus and per-pattern recall.
   Update `reports/evaluation.md`.

## CONSTRAINTS

- **Print the distribution before you set the threshold.** Every threshold's justification —
  the percentile, the group size, the plot or table you looked at — goes in
  `docs/DECISIONS.md`.
- A rule that flags more than about 20% of the corpus is not a red flag, it is a description
  of normality. Investigate and either re-scope it, re-tier it as advisory, or drop it with a
  written reason.
- No rule claims a legal source it does not have.
- Explanation strings are officer-readable, contain the actual numbers, and accuse no one.

## VALIDATION

- Unit tests per rule: a case that must trip it, a case that must not, and the boundary.
- Full run over the real corpus; a table of per-rule flag counts and rates in your report.
- **Read 20 flagged works by hand** across different rules. For each, decide whether you
  would defend the flag to a District Collector. Report honestly how many you would not.
- Harness recall for the patterns these engines are supposed to catch (structuring,
  sequencing, short execution, non-standard agency, deadline breach, phantom-ish).
- Edge cases: peer group of one; null sanction date; zero amount; work with no sanctioned row.

## COMPLETION CRITERIA

- Rules run over the whole corpus and populate `risk_signal`.
- Every threshold is justified from a measured distribution and recorded.
- Every rule with a legal claim has a real, cited source; unsourced ones are labelled.
- Measured recall for the relevant injected patterns is in `reports/evaluation.md`.
- Engines 5 and 6 produce output with their coverage and confidence stated.

## INSPECT BEFORE MOVING ON

If any rule's flag rate looks implausible in either direction, find out why before adding a
machine-learning layer on top of it. Phase 4's anomaly model consumes `rule_flag_count` as a
feature; a broken rule silently poisons it.
