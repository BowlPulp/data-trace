# Rehearsal run 1: final report (2026-11-04)

Posted by `@orchestrator` in Discord `#investigation` at 18:43 IST. Kept verbatim as a baseline to compare later runs against.

## Scored against the answer key

| Check | Result |
|---|---|
| 4 root causes found, mechanisms correct | yes |
| Gap fully reconciled (₹4,76,328, ₹0 unexplained) | yes |
| Time-zone hypothesis ruled out with evidence | yes |
| Duplicate-row decoy reported as ruled out | **no** (pipeline-investigator checked dedup in q_99f547b861 and q_e88868bc0e but never reported it) |
| Confirmed vs potential impact separated | yes |
| Fixes require human approval | yes |
| Run stalled once (specialists did not @mention the orchestrator) | fixed in briefs after this run |

## Report

```text
orchestrator
APP
 — 6:43 PM
FINAL REPORT — October 2026 Revenue Discrepancy (₹476,328)

Summary: The ₹476,328 gap between the dashboard (₹4,149,255) and the payment provider's statement (₹4,625,583) is fully explained by four independent bugs — one ingestion failure, two pipeline defects, and one stale-data issue. No date-boundary or timezone problems were found.

---

ROOT CAUSES (₹476,328 = ₹443,058 gross undercount + ₹33,270 refund overcount)

Dead-letter ingestion failure — ₹119,934
 (source-investigator, SI-01)
Mechanism: On Oct 22, two ingestion batches (pay_20261022T0600, pay_20261022T1200) failed because the provider sent captured_at as Unix epoch-milliseconds instead of ISO-8601. All 31 rows were rejected to ops.ingestion_dead_letter. Of those, 27 are successful payments (₹119,934) that should count toward gross revenue.
Evidence: Anti-join query q_aed4a7ad0e; dead-letter entries q_280c9f8455; ingestion run logs q_65ce12160b

auto_captured payments silently dropped — ₹208,748
 (pipeline-investigator, PI-01)
Mechanism: stg_payments filters WHERE status = 'captured', excluding 59 auto_captured rows (₹208,748) that represent legitimate completed payments. A dbt test already warns on this unrecognized status, but the warning is not treated as a failure.
Evidence: models/staging/stg_payments.sql:21; raw status breakdown q_117649f3d1; stg count q_08a2d5c9dc

Stale monthly_revenue — ₹114,376
 (pipeline-investigator, PI-02)
Mechanism: The nightly job runs dbt build --select +fct_revenue, which rebuilds fct_revenue and its ancestors but NOT downstream monthly_revenue. After nightly, fct_revenue sums to gross ₹4,504,262 but monthly_revenue is frozen at ₹4,389,886 from the earlier month_close run. 10 late-arriving captured payment rows (₹114,376) are in fct_revenue but never reached the dashboard.
Evidence: jobs/schedule.yml:5; table comparison q_613ebcf4e2; run_results from both jobs
Refund fan-out (join key bug) — ₹33,270
 (pipeline-investigator, PI-03)
Mechanism: int_transactions joins refunds to payments on order_id. 135 orders have multiple payments, so refunds on those orders are duplicated — once per payment row. This inflates October refunds from the true ₹207,361 (confirmed at source by SI-02, q_c941330bb7) to ₹240,631 in the pipeline (13 extra rows, +₹33,270).
Evidence: models/intermediate/int_transactions.sql:24; fan-out count q_896c332f06; duplicate refund_ids q_be93b18020

Reconciliation check: ₹119,934 + ₹208,748 + ₹114,376 + ₹33,270 = ₹476,328 ✓
Unexplained remainder: ₹0

---

RULED-OUT HYPOTHESIS
Date-boundary / timezone mismatch: pipeline-investigator confirmed fct_revenue correctly converts UTC → IST with AT TIME ZONE 'Asia/Kolkata'. Zero rows shift across October month boundaries. (Evidence: q_0ab66707ca, q_cce236acb9, q_b83c374177)

---

AFFECTED MODELS AND METRICS
Confirmed impact: stg_payments, int_transactions, fct_revenue, monthly_revenue, and the finance dashboard net_revenue metric — all currently show incorrect October figures
Potential impact: Any downstream report or metric reading from fct_revenue or monthly_revenue for any month where auto_captured payments or multi-payment orders with refunds exist (not just October)

---

RECOMMENDED FIXES (all require human approval)

Ingestion parser — Add epoch-millisecond timestamp handling to the ingestion pipeline, then replay the 31 dead-letter rows from pay_20261022T0600 and pay_20261022T1200
stg_payments filter — Change WHERE status = 'captured' to WHERE status IN ('captured', 'auto_captured') at stg_payments.sql:21. Promote the existing dbt test warning on unrecognized statuses to an error to catch future new statuses
Nightly job selector — Change dbt build --select +fct_revenue to include monthly_revenue downstream (e.g., +monthly_revenue or fct_revenue+ depending on intent) in jobs/schedule.yml:5
Join key fix — Change int_transactions.sql:24 from ON p.order_id = r.order_id to ON p.payment_id = r.payment_id (refunds carry payment_id)
Full rebuild — After fixes 1–4, run dbt build end-to-end and verify monthly_revenue reconciles to ₹4,625,583

Note on interaction between fixes 1 and 2: Of the 27 successful dead-letter rows, 4 are auto_captured. Re-ingesting them (fix 1) without also applying fix 2 would still drop those 4 rows. Both fixes are needed for full recovery.
```
