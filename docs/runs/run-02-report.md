# Rehearsal run 2: investigation → reviewed fixes → verified sandbox run (6–7 Nov 2026)

Room: Discord `#investigation2` (Switch room), one thread. Started 4 Nov 19:50 IST; the agents'
sessions dropped and the warehouse was offline, so the investigation resumed on 6 Nov 21:41 IST
and closed 7 Nov 02:40 IST. First run to go all the way through remediation.

## Scorecard (against the hidden answer key)

| Check | Result |
|---|---|
| 4 root causes found, mechanisms correct | ✅ |
| Gap fully reconciled (₹4,76,328, ₹0 unexplained) | ✅ |
| Time-zone hypothesis checked with evidence | ✅ (month-boundary queries, e.g. `q_9716d34baf`) |
| Duplicate-row decoy investigated | ✅ checked and shown not to reach `stg_payments` (`q_bdca267fd7`, `q_412322376f`, `q_c3416ff02b`) — run 1 missed this |
| Provider fees / adjustments hypothesis ruled out | ✅ (`q_fc1297b1dc`, metrics recompute from provider export) |
| One fix proposal per root cause, each with evidence | ✅ 4 proposals |
| Every proposal correct on first submission | ❌ 2 of 4 rejected in human review (below) |
| Human approval before any change | ✅ |
| Sandbox run verified against provider statement | ✅ `R-20261107-023815`, both months match exactly |
| Agents blocked cleanly when the warehouse was down | ✅ posted a BLOCKER with the fix command instead of guessing |

Agent query volume this run (from `logs/agent_queries/`): source 29, pipeline 60, metrics 19.

## Findings (October 2026)

| Cause | Found by | Impact |
|---|---|---|
| Oct 22 ingestion batches rejected to dead letter (epoch-ms timestamps) | source-investigator, confirmed by metrics | ₹1,19,934 |
| `stg_payments` drops `auto_captured` | pipeline-investigator | ₹2,08,748 |
| `monthly_revenue` stale: nightly job builds only `+fct_revenue` | pipeline-investigator | ₹1,14,376 |
| Refund fan-out: `int_transactions` joins refunds on `order_id` | pipeline-investigator, refunds confirmed at source | ₹33,270 |
| **Total** | | **₹4,76,328** |

## Remediation

### Proposals and human review

| Id | Fix | Kind | Outcome |
|---|---|---|---|
| P-001 | `stg_payments`: keep `captured` + `auto_captured`; `accepted_values` test on status → `severity: error` | code_patch | approved, applied |
| P-002 | `int_transactions`: join refunds on `payment_id` (inner join) | code_patch | **rejected** |
| P-003 | Nightly job: `dbt build --select +monthly_revenue` | code_patch | approved, applied |
| P-004 | Backfill the 31 dead-lettered payments | backfill_sql | **rejected** |
| P-005 | P-002 v2: `left join` on `payment_id`, refund keeps its own `payment_id` | code_patch | approved, applied |
| P-006 | P-004 v2: backfill with the real payload mapping | backfill_sql | approved, applied |

**Why P-004 was rejected.** The SQL was written from assumed column names rather than the payload.
It read `payload->>'payment_id'`, `'order_id'`, `'provider_txn_id'`, `'payment_method'` — none
exist (the keys are `id, merchant_order_ref, amount, currency, method, status, vpa, created_at,
captured_at`). It would have inserted NULL into the NOT NULL `payment_id` and crashed the apply;
it also took `amount` as rupees (the payload is in **paise**, so revenue would have been 100×),
cast the epoch-ms `created_at` as a timestamp, and omitted the NOT NULL `currency` and `_batch_id`.

**Why P-002 was rejected.** Four refunds (REF-000141/142/143/145) belong to payments that exist
only in the dead letter; their `payment_id`s are not in the payload, so no backfill can restore
them. An inner join on `payment_id` would silently drop them and overstate October net revenue by
₹4,030. Finance's definition counts every processed refund, so the join must be a left join.

The pipeline investigator re-proposed both within minutes (P-005, P-006), citing the review, and
checked the orphaned-refund count against the warehouse (`q_8b06d27272`).

### Sandbox run `R-20261107-023815`

Applied P-001, P-003, P-005, P-006 on branch `remediation/R-20261107-023815` against
`datatrace_sandbox` (production untouched):

1. worktree + branch created; sandbox rebuilt from a production copy
2. code patches applied and committed; `dbt parse` ok
3. P-006 backfill executed in the sandbox
4. changed models deployed: `dbt run --select int_transactions stg_payments`
5. patched nightly job: `dbt build --select +monthly_revenue` → **PASS=18 WARN=0 ERROR=0**
   (the status warning that hid the `auto_captured` bug is gone; the test is now an error)

| Month | Provider net_collections | Sandbox dashboard | Match |
|---|---|---|---|
| Sep 2026 | ₹33,29,525 | ₹33,29,525 | ✅ |
| Oct 2026 | ₹46,25,583 | ₹46,25,583 | ✅ |

`monthly_revenue.built_at` is fresh from this run. Verdict: **VERIFIED**. The orchestrator posted
the proposal status and verdict in the thread and closed the investigation.

## Out of scope (flagged by the agents)

The ingestion service's timestamp parser still rejects epoch-ms values; it lives outside the dbt
project, so it was reported as a separate follow-up rather than proposed as a patch.

## Lessons

- **Human review earned its place.** Every claim in the investigation had evidence, yet 2 of 4 fixes
  were wrong in ways only visible by checking the actual payload and the refund→payment links.
  Validation would have caught P-004 only by crashing; P-002 would have *passed* dbt and failed
  verification by ₹4,030.
- **Infrastructure drops are handled honestly.** When Docker stopped, agents reported a blocker and
  the exact command to fix it instead of inventing numbers.
- **Next brief change:** the pipeline investigator should query the source rows (dead-letter payload,
  orphaned keys) before writing any backfill or join change, and cite those query_ids in the proposal.
