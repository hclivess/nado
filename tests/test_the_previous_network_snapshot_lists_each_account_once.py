"""doc/previous-network-snapshot.md lists each account of the previous network ONCE, and its summary is computed from
its own rows (accounts, total held), and the README's holder count agrees.

The first export (c6aecc1e, 2026-07-09) repeated two accounts' rows 670 and 550 times — 2,801 rows for 1,583 accounts —
and its summary counted them: 792,670 NADO held where the rows hold 125,129. A public record of balances that overstates
them six-fold is the kind of number someone eventually acts on. Pure file read; no node import.

Run: python3 tests/test_the_previous_network_snapshot_lists_each_account_once.py
"""
import os, re, sys
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import _harness
_report = _harness.Report()
check = _report.check


doc = open(os.path.join(ROOT, "doc", "previous-network-snapshot.md"), encoding="utf-8").read()
rows = re.findall(r"^\| (\d+) \| `([^`]+)` \| ([^|]+) \| ([^|]+) \|$", doc, re.M)
addrs = [a for _, a, _, _ in rows]
check("the table has rows", len(rows) > 1000, len(rows))
dups = sorted({a for a in addrs if addrs.count(a) > 1})
check("each account appears once", not dups, dups[:5])
check("rows are numbered 1..n in order", [int(i) for i, *_ in rows] == list(range(1, len(rows) + 1)))
total = sum(Decimal(b.strip()) for _, _, b, _ in rows)
m_n = re.search(r"\| Accounts with a balance \(excl\. premine & burn\) \| ([\d,]+) \|", doc)
m_t = re.search(r"\| Total held \(excl\. premine & burn\) \| ([\d.]+) NADO \|", doc)
check("the summary's account count is the number of rows", m_n and int(m_n.group(1).replace(",", "")) == len(rows),
      m_n and m_n.group(1))
check("the summary's total is the sum of the rows", m_t and Decimal(m_t.group(1)) == total, (m_t and m_t.group(1), total))
check("balances are sorted descending", all(Decimal(rows[i][2]) >= Decimal(rows[i + 1][2]) for i in range(len(rows) - 1)))
readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
check("the README's holder count agrees", f"({len(rows):,} holders)" in readme)
print("ALL PASS — the previous-network snapshot lists each account once" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
