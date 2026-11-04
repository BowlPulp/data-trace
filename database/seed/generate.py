#!/usr/bin/env python3
"""
Deterministic generator for the DATA TRACE demo warehouse (stdlib only, Python 3.10+).

Writes CSVs to database/seed/data/. Re-running with the same SEED gives identical output.

NOTE: this file documents the planted data problems. Investigation agents must NOT be
given read access to database/seed/ or the `verification` schema.

Loading is split in two so the stale-model problem can be reproduced for real:
  *_initial.csv  rows that existed when the monthly dbt job ran (2026-11-01 01:00 IST)
  *_late.csv     rows that arrived afterwards
"""
from __future__ import annotations

import csv
import json
import random
import string
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 20261104
IST = timezone(timedelta(hours=5, minutes=30))
OUT = Path(__file__).resolve().parent / "data"

ORDERS_START = datetime(2026, 9, 1, tzinfo=IST)
ORDERS_END = datetime(2026, 11, 1, tzinfo=IST)          # exclusive
NOW = datetime(2026, 11, 4, 9, 0, tzinfo=IST)           # "today" in the demo
MONTHLY_BUILD_AT = datetime(2026, 11, 1, 1, 0, tzinfo=IST)

WINDOW = timedelta(hours=6)                              # payments ingestion window
AUTOPAY_LAUNCH = datetime(2026, 10, 10, tzinfo=IST)      # provider adds status 'auto_captured'
AUTOPAY_SHARE_OF_UPI = 0.15
REJECT_WINDOWS = [datetime(2026, 10, 22, 6, tzinfo=IST), datetime(2026, 10, 22, 12, tzinfo=IST)]
DUPLICATE_WINDOWS = [datetime(2026, 10, 9, 0, tzinfo=IST), datetime(2026, 10, 9, 6, tzinfo=IST)]
LATE_FROM = datetime(2026, 10, 31, 6, tzinfo=IST)        # windows from here to ORDERS_END fail, backfilled later
LATE_LOADED_AT = datetime(2026, 11, 2, 3, 10, tzinfo=IST)

SUCCESS = ("captured", "auto_captured")                 # provider statuses meaning funds collected

rng = random.Random(SEED)


def ts(d: datetime | None) -> str:
    return "" if d is None else d.isoformat(timespec="seconds")


def rid(prefix: str, n: int = 14) -> str:
    return prefix + "".join(rng.choices(string.ascii_lowercase + string.digits, k=n))


def money(x: float) -> int:
    return int(round(x))


def window_start(d: datetime) -> datetime:
    k = int((d - ORDERS_START) // WINDOW)
    return ORDERS_START + k * WINDOW


def month_of(d: datetime) -> str:
    return d.astimezone(IST).strftime("%Y-%m-01")


# ---------------------------------------------------------------- reference data
CATEGORIES = {
    "Electronics": (["Wireless Earbuds", "Smartwatch", "Bluetooth Speaker", "Power Bank 20000mAh",
                     "Mechanical Keyboard", "USB-C Hub", "Noise Cancelling Headphones", "Webcam 1080p"],
                    (1299, 8999)),
    "Apparel": (["Cotton Kurta", "Denim Jacket", "Running Shoes", "Linen Shirt", "Track Pants",
                 "Silk Saree", "Hoodie", "Leather Belt"], (499, 4999)),
    "Home": (["Pressure Cooker 5L", "Non-stick Tawa", "Bedsheet Set", "Table Lamp", "Air Purifier",
              "Steel Water Bottle", "Wall Clock", "Storage Organizer"], (399, 7999)),
    "Beauty": (["Vitamin C Serum", "Sunscreen SPF50", "Hair Dryer", "Beard Trimmer", "Face Wash",
                "Perfume 100ml", "Lip Care Kit", "Ayurvedic Hair Oil"], (249, 3499)),
    "Books": (["Data Engineering Handbook", "Indian History Atlas", "Cookbook: Regional Thalis",
               "Startup Playbook", "Mystery Novel Box Set", "Learn Python", "Poetry Anthology",
               "Children's Encyclopedia"], (199, 1999)),
}
FIRST = ["Aarav", "Vivaan", "Aditya", "Ishaan", "Kabir", "Rohan", "Arjun", "Sai", "Ananya", "Diya",
         "Saanvi", "Aadhya", "Meera", "Kavya", "Priya", "Neha", "Rahul", "Vikram", "Pooja", "Sneha",
         "Harpreet", "Simran", "Farhan", "Zoya", "Karthik", "Lakshmi", "Nikhil", "Tanvi"]
LAST = ["Sharma", "Verma", "Iyer", "Reddy", "Nair", "Gupta", "Singh", "Khan", "Patel", "Mehta",
        "Das", "Bose", "Kulkarni", "Joshi", "Chopra", "Malhotra", "Pillai", "Rao", "Gill", "Kapoor"]
CITIES = ["Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Pune", "Kolkata", "Ahmedabad",
          "Jaipur", "Chandigarh", "Lucknow", "Kochi", "Indore", "Gurugram", "Noida"]
UPI_HANDLES = ["okaxis", "okhdfcbank", "oksbi", "okicici", "ybl", "paytm", "ibl"]


@dataclass
class Payment:
    payment_id: str
    order_id: str
    provider_txn_id: str
    amount: int
    method: str
    status: str
    upi_vpa: str | None
    created_at: datetime
    captured_at: datetime | None
    batch_id: str = ""
    loaded_at: datetime | None = None    # None => never loaded into raw (rejected)
    duplicate_loaded_at: datetime | None = None


@dataclass
class Refund:
    refund_id: str
    payment_id: str
    order_id: str
    provider_refund_id: str
    amount: int
    reason: str
    created_at: datetime
    processed_at: datetime
    loaded_at: datetime


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # products
    products = []
    n = 1
    for cat, (names, (lo, hi)) in CATEGORIES.items():
        for name in names:
            price = rng.randint(lo // 10, hi // 10) * 10 - 1
            products.append({"product_id": f"PRD-{n:04d}", "product_name": name, "category": cat,
                             "list_price": price, "is_active": "true"})
            n += 1

    # customers
    customers = []
    for i in range(1, 1101):
        f, l = rng.choice(FIRST), rng.choice(LAST)
        signup = datetime(2025, 1, 1, tzinfo=IST) + timedelta(minutes=rng.randint(0, 600 * 24 * 60))
        customers.append({"customer_id": f"CUS-{i:05d}", "full_name": f"{f} {l}",
                          "email": f"{f.lower()}.{l.lower()}{i}@example.com",
                          "city": rng.choice(CITIES), "signup_at": signup})

    # orders + payments + refunds
    orders, payments, refunds = [], [], []
    oid = 0
    day = ORDERS_START
    while day < ORDERS_END:
        base = 31 if day.month == 9 else 38
        if day.weekday() >= 5:
            base *= 1.2
        if datetime(2026, 10, 17, tzinfo=IST) <= day <= datetime(2026, 10, 21, tzinfo=IST):
            base *= 1.45   # Dussehra sale
        for _ in range(max(0, int(rng.gauss(base, base * 0.12)))):
            oid += 1
            order_id = f"ORD-{oid:06d}"
            ordered_at = day + timedelta(seconds=rng.randint(8 * 3600, 24 * 3600 - 1))
            cust = rng.choice(customers)
            if cust["signup_at"] > ordered_at:
                cust = customers[0]
            prod = rng.choices(products, weights=[1.0 / (p["list_price"] ** 0.25) for p in products])[0]
            qty = rng.choices([1, 2, 3], weights=[72, 21, 7])[0]
            gross = prod["list_price"] * qty
            discount = money(gross * 0.1) if rng.random() < 0.15 else 0
            total = gross - discount
            r = rng.random()
            status = "cancelled" if r < 0.04 else "pending_payment" if r < 0.055 else "completed"
            orders.append({"order_id": order_id, "customer_id": cust["customer_id"],
                           "product_id": prod["product_id"], "quantity": qty,
                           "unit_price": prod["list_price"], "discount_amount": discount,
                           "order_total": total, "order_status": status, "ordered_at": ordered_at})

            t = ordered_at + timedelta(seconds=rng.randint(40, 420))

            def make(amount, method, st, at):
                vpa = (f"{cust['full_name'].split()[0].lower()}{rng.randint(10, 999)}@{rng.choice(UPI_HANDLES)}"
                       if method == "upi" else None)
                cap = at + timedelta(seconds=rng.randint(3, 90)) if st in SUCCESS else None
                p = Payment(rid("pay_"), order_id, rid("txn_"), amount, method, st, vpa, at, cap)
                p.payment_id = f"PAY-{len(payments) + 1:07d}"
                payments.append(p)
                return p

            if status == "cancelled":
                make(total, rng.choice(["card", "upi"]), "failed", t)
                continue
            if status == "pending_payment":
                make(total, "netbanking", "pending", t)
                continue
            if rng.random() < 0.09:  # failed first attempt, then retry succeeds
                make(total, rng.choice(["card", "upi", "netbanking"]), "failed", t)
                t += timedelta(seconds=rng.randint(60, 600))

            def success_status(method, at):
                if method == "upi" and at >= AUTOPAY_LAUNCH and rng.random() < AUTOPAY_SHARE_OF_UPI:
                    return "auto_captured"
                return "captured"

            split = total >= 1500 and rng.random() < 0.10
            if split:
                wallet_amt = min(rng.randint(20, 150) * 10, total - 500)
                make(wallet_amt, "wallet", "captured", t)
                main_pay = make(total - wallet_amt, "card", "captured", t + timedelta(seconds=rng.randint(5, 40)))
            else:
                method = rng.choices(["upi", "card", "netbanking", "wallet"], weights=[55, 28, 9, 8])[0]
                main_pay = make(total, method, success_status(method, t), t)

            # refunds (always against one specific payment)
            p_ref = 0.25 if split else 0.07
            if rng.random() < p_ref:
                full = (not split) and rng.random() < 0.5
                amt = main_pay.amount if full else max(50, money(main_pay.amount * rng.uniform(0.2, 0.6) / 10) * 10)
                created = main_pay.captured_at + timedelta(days=rng.randint(1, 9), hours=rng.randint(0, 20))
                processed = created + timedelta(hours=rng.randint(2, 70))
                if processed <= NOW:
                    refunds.append(Refund(f"REF-{len(refunds) + 1:06d}", main_pay.payment_id, order_id,
                                          rid("rfnd_"), amt,
                                          rng.choice(["damaged_item", "size_issue", "late_delivery",
                                                      "customer_cancelled", "wrong_item"]),
                                          created, processed, processed + timedelta(minutes=rng.randint(10, 50))))
        day += timedelta(days=1)

    # ------------------------------------------------------------ ingestion simulation (payments)
    windows = defaultdict(list)
    for p in payments:
        windows[window_start(p.created_at)].append(p)

    runs, dead_letter = [], []
    run_no = 0

    def add_run(batch_id, ws, started, finished, status, received, loaded, rejected, err):
        nonlocal run_no
        run_no += 1
        runs.append({"run_id": run_no, "source": "payments_api", "batch_id": batch_id,
                     "window_start": ts(ws), "window_end": ts(ws + WINDOW), "started_at": ts(started),
                     "finished_at": ts(finished), "status": status, "rows_received": received,
                     "rows_loaded": loaded, "rows_rejected": rejected, "error_summary": err or ""})

    ws = ORDERS_START
    while ws < ORDERS_END:
        rows = sorted(windows.get(ws, []), key=lambda p: p.created_at)
        batch_id = f"pay_{ws.strftime('%Y%m%dT%H%M')}"
        start = ws + WINDOW + timedelta(minutes=15)
        if ws >= LATE_FROM:
            add_run(batch_id, ws, start, start + timedelta(minutes=2), "failed", 0, 0, 0,
                    "provider API returned HTTP 503 Service Unavailable after 5 retries")
            for p in rows:
                p.batch_id, p.loaded_at = batch_id, LATE_LOADED_AT
        elif ws in REJECT_WINDOWS:
            # provider maintenance: captured_at arrived as epoch-millis strings; loader rejected the rows
            fin = start + timedelta(minutes=3)
            for p in rows:
                p.batch_id = batch_id
                payload = {"id": p.provider_txn_id, "merchant_order_ref": p.order_id, "amount": p.amount * 100,
                           "currency": "INR", "method": p.method, "status": p.status, "vpa": p.upi_vpa,
                           "created_at": int(p.created_at.timestamp() * 1000),
                           "captured_at": str(int(p.captured_at.timestamp() * 1000)) if p.captured_at else None}
                dead_letter.append({"batch_id": batch_id, "received_at": ts(fin), "error":
                                    f'invalid input syntax for type timestamp with time zone: "{payload["captured_at"]}"'
                                    if payload["captured_at"] else
                                    'invalid input syntax for type timestamp with time zone: "' + str(payload["created_at"]) + '"',
                                    "payload": json.dumps(payload, separators=(",", ":"))})
            add_run(batch_id, ws, start, fin, "succeeded", len(rows), 0, len(rows),
                    f"{len(rows)} rows rejected: timestamp parse error (see ops.ingestion_dead_letter)")
        else:
            fin = start + timedelta(seconds=rng.randint(40, 240))
            for p in rows:
                p.batch_id, p.loaded_at = batch_id, fin
            add_run(batch_id, ws, start, fin, "succeeded", len(rows), len(rows), 0, None)
            if ws in DUPLICATE_WINDOWS:
                # scheduler retried a batch it wrongly thought had timed out -> rows delivered twice
                rstart = fin + timedelta(hours=1, minutes=5)
                rfin = rstart + timedelta(seconds=150)
                for p in rows:
                    p.duplicate_loaded_at = rfin
                add_run(batch_id + "_retry1", ws, rstart, rfin, "succeeded", len(rows), len(rows), 0,
                        "manual retry after scheduler timeout alert")
        ws += WINDOW

    lw = LATE_FROM
    while lw < ORDERS_END:   # backfill
        rows = windows.get(lw, [])
        add_run(f"pay_{lw.strftime('%Y%m%dT%H%M')}", lw, LATE_LOADED_AT - timedelta(minutes=4),
                LATE_LOADED_AT, "succeeded", len(rows), len(rows), 0, "backfill after provider outage")
        lw += WINDOW

    # ------------------------------------------------------------ metric calculations
    def correct_net(month, pays, refs):
        gross = sum(p.amount for p in pays if p.status in SUCCESS and month_of(p.captured_at) == month)
        refd = sum(r.amount for r in refs if month_of(r.processed_at) == month)
        return gross, refd, gross - refd

    def pipeline_net(month, pays, refs, *, status_bug, fanout_bug):
        """Mirror of the dbt models: dedup payments, filter status, ledger of payments(+) and refunds(-)."""
        ok = SUCCESS[:1] if status_bug else SUCCESS
        kept = [p for p in pays if p.status in ok]
        by_order = defaultdict(list)
        for p in kept:
            by_order[p.order_id].append(p)
        by_id = {p.payment_id: p for p in kept}
        total = sum(p.amount for p in kept if month_of(p.captured_at) == month)
        for r in refs:
            if month_of(r.processed_at) != month:
                continue
            matches = by_order[r.order_id] if fanout_bug else ([by_id[r.payment_id]] if r.payment_id in by_id else [])
            total -= r.amount * len(matches)
        return total

    loaded_all = [p for p in payments if p.loaded_at is not None]
    loaded_at_build = [p for p in loaded_all if p.loaded_at <= MONTHLY_BUILD_AT]
    refunds_at_build = [r for r in refunds if r.loaded_at <= MONTHLY_BUILD_AT]
    refunds_loaded = refunds  # all loaded by NOW

    expected, issues = [], []
    for month in ("2026-09-01", "2026-10-01"):
        g, rf, net = correct_net(month, payments, refunds)
        expected += [
            {"metric": "gross_revenue", "month": month, "value": g, "note": "ground truth: all successful payments"},
            {"metric": "refunds", "month": month, "value": rf, "note": "ground truth: refunds processed in month"},
            {"metric": "net_revenue", "month": month, "value": net, "note": "ground truth; equals provider net_collections"},
            {"metric": "net_revenue_reported_monthly_model", "month": month,
             "value": pipeline_net(month, loaded_at_build, refunds_at_build, status_bug=True, fanout_bug=True),
             "note": "expected value of analytics.monthly_revenue (built 2026-11-01 01:00 IST, all bugs)"},
            {"metric": "net_revenue_fct_current", "month": month,
             "value": pipeline_net(month, loaded_all, refunds_loaded, status_bug=True, fanout_bug=True),
             "note": "expected sum of analytics.fct_revenue after the nightly job (not stale)"},
        ]

    m = "2026-10-01"
    truth = correct_net(m, payments, refunds)[2]
    iso = {
        "ISSUE-1": truth - correct_net(m, loaded_all, refunds)[2],
        "ISSUE-2": truth - pipeline_net(m, payments, refunds, status_bug=True, fanout_bug=False),
        "ISSUE-3": truth - pipeline_net(m, payments, refunds, status_bug=False, fanout_bug=True),
        "ISSUE-4": truth - correct_net(m, [p for p in payments if p.loaded_at is None or p.loaded_at <= MONTHLY_BUILD_AT], refunds_at_build)[2],
    }
    issues = [
        {"issue_id": "ISSUE-1", "title": "Payments missing from ingestion",
         "mechanism": "Two payments_api batches on 2026-10-22 had every row rejected (epoch-millis timestamps); run marked succeeded; rows only in ops.ingestion_dead_letter",
         "oct_isolated_impact": iso["ISSUE-1"]},
        {"issue_id": "ISSUE-2", "title": "Valid payment status excluded",
         "mechanism": "stg_payments keeps status = 'captured' only; provider added 'auto_captured' (UPI AutoPay) on 2026-10-10",
         "oct_isolated_impact": iso["ISSUE-2"]},
        {"issue_id": "ISSUE-3", "title": "Refund fan-out",
         "mechanism": "int_transactions joins refunds to payments on order_id instead of payment_id; split-payment orders subtract refunds twice",
         "oct_isolated_impact": iso["ISSUE-3"]},
        {"issue_id": "ISSUE-4", "title": "Stale monthly model",
         "mechanism": "monthly_revenue was built by the month_close job before the Oct 31 payments were backfilled; the nightly job only rebuilds +fct_revenue, so monthly_revenue is never refreshed",
         "oct_isolated_impact": iso["ISSUE-4"]},
        {"issue_id": "DECOY-1", "title": "Duplicate raw payment rows (not a revenue bug)",
         "mechanism": "2026-10-09 batches delivered twice; stg_payments deduplicates by payment_id, so revenue is unaffected",
         "oct_isolated_impact": 0},
    ]

    # provider statement (independent of warehouse)
    statement = []
    for month in ("2026-09-01", "2026-10-01"):
        g, rf, net = correct_net(month, payments, refunds)
        statement.append({"statement_month": month, "gross_collections": g, "refunds": rf, "net_collections": net,
                          "successful_payments": sum(1 for p in payments if p.status in SUCCESS and month_of(p.captured_at) == month),
                          "refund_count": sum(1 for r in refunds if month_of(r.processed_at) == month),
                          "generated_at": ts(datetime(2026, 11, 3, 6, 0, tzinfo=IST))})

    # ------------------------------------------------------------ write CSVs
    def write(name, header, rows):
        with open(OUT / f"{name}.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(rows)

    load_ts = lambda d: d + timedelta(minutes=12)
    write("raw_products_initial", ["product_id", "product_name", "category", "list_price", "is_active", "_loaded_at"],
          [[p["product_id"], p["product_name"], p["category"], p["list_price"], p["is_active"], ts(ORDERS_START - timedelta(days=30))] for p in products])
    write("raw_customers_initial", ["customer_id", "full_name", "email", "city", "signup_at", "_loaded_at"],
          [[c["customer_id"], c["full_name"], c["email"], c["city"], ts(c["signup_at"]), ts(load_ts(c["signup_at"]))] for c in customers])
    write("raw_orders_initial", ["order_id", "customer_id", "product_id", "quantity", "unit_price", "discount_amount",
                                 "order_total", "order_status", "ordered_at", "_loaded_at"],
          [[o["order_id"], o["customer_id"], o["product_id"], o["quantity"], o["unit_price"], o["discount_amount"],
            o["order_total"], o["order_status"], ts(o["ordered_at"]), ts(load_ts(o["ordered_at"]))] for o in orders])

    pay_hdr = ["payment_id", "order_id", "provider_txn_id", "amount", "currency", "payment_method", "status",
               "upi_vpa", "created_at", "captured_at", "_batch_id", "_loaded_at"]
    pay_rows = []
    for p in payments:
        if p.loaded_at is None:
            continue
        base = [p.payment_id, p.order_id, p.provider_txn_id, p.amount, "INR", p.method, p.status,
                p.upi_vpa or "", ts(p.created_at), ts(p.captured_at)]
        pay_rows.append((p.loaded_at, base + [p.batch_id, ts(p.loaded_at)]))
        if p.duplicate_loaded_at:
            pay_rows.append((p.duplicate_loaded_at, base + [p.batch_id + "_retry1", ts(p.duplicate_loaded_at)]))
    pay_rows.sort(key=lambda x: x[0])
    write("raw_payments_initial", pay_hdr, [r for t, r in pay_rows if t <= MONTHLY_BUILD_AT])
    write("raw_payments_late", pay_hdr, [r for t, r in pay_rows if t > MONTHLY_BUILD_AT])

    ref_hdr = ["refund_id", "payment_id", "order_id", "provider_refund_id", "amount", "reason", "status",
               "created_at", "processed_at", "_loaded_at"]
    ref_rows = [[r.refund_id, r.payment_id, r.order_id, r.provider_refund_id, r.amount, r.reason, "processed",
                 ts(r.created_at), ts(r.processed_at), ts(r.loaded_at)] for r in sorted(refunds, key=lambda r: r.loaded_at)]
    write("raw_refunds_initial", ref_hdr, [r for r, x in zip(ref_rows, sorted(refunds, key=lambda r: r.loaded_at)) if x.loaded_at <= MONTHLY_BUILD_AT])
    write("raw_refunds_late", ref_hdr, [r for r, x in zip(ref_rows, sorted(refunds, key=lambda r: r.loaded_at)) if x.loaded_at > MONTHLY_BUILD_AT])

    prov = []
    for p in payments:
        prov.append([p.provider_txn_id, "payment", p.order_id, p.amount, "INR", p.method, p.status, ts(p.captured_at or p.created_at)])
    for r in refunds:
        prov.append([r.provider_refund_id, "refund", r.order_id, r.amount, "INR", "", "processed", ts(r.processed_at)])
    prov.sort(key=lambda x: x[7])
    write("provider_payment_report", ["provider_txn_id", "txn_type", "merchant_order_ref", "amount", "currency",
                                      "method", "status", "txn_at"], prov)
    write("provider_monthly_statement", list(statement[0].keys()), [list(s.values()) for s in statement])

    run_hdr = list(runs[0].keys())
    write("ops_ingestion_runs_initial", run_hdr, [list(r.values()) for r in runs if r["finished_at"] <= ts(MONTHLY_BUILD_AT)])
    write("ops_ingestion_runs_late", run_hdr, [list(r.values()) for r in runs if r["finished_at"] > ts(MONTHLY_BUILD_AT)])
    write("ops_ingestion_dead_letter", ["batch_id", "received_at", "error", "payload"],
          [list(d.values()) for d in dead_letter])

    write("verification_expected_metrics", ["metric", "month", "value", "note"], [list(e.values()) for e in expected])
    write("verification_planted_issues", ["issue_id", "title", "mechanism", "oct_isolated_impact"], [list(i.values()) for i in issues])

    # ------------------------------------------------------------ summary
    def inr(x):
        return f"₹{x:,.0f}"
    print(f"orders={len(orders)} payments={len(payments)} refunds={len(refunds)} "
          f"raw_payment_rows={len(pay_rows)} dead_letter={len(dead_letter)}")
    for e in expected:
        print(f"  {e['month']} {e['metric']:<38} {inr(e['value'])}")
    for i in issues:
        print(f"  {i['issue_id']:<8} isolated Oct impact {inr(i['oct_isolated_impact'])}  {i['title']}")


if __name__ == "__main__":
    main()
