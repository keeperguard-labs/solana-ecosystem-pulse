#!/usr/bin/env python3
"""Generate an auditable Solana ecosystem report without API keys.

The live path is intentionally dependency-free. Tests use the pure functions
and the sample snapshot, so they never contact a network.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_RPC_URL = "https://api.mainnet-beta.solana.com"
COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/simple/price?ids=solana&"
    "vs_currencies=usd&include_24hr_change=true"
)
DEFILLAMA_URL = "https://api.llama.fi/v2/historicalChainTvl/Solana"
LAMPORTS_PER_SOL = 1_000_000_000


class SourceError(RuntimeError):
    """A source failed but the report can still be generated."""


@dataclass
class SourceStatus:
    name: str
    url: str
    ok: bool
    fetched_at: str
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "name": self.name,
            "url": self.url,
            "ok": self.ok,
            "fetchedAt": self.fetched_at,
        }
        if self.error:
            value["error"] = self.error
        return value


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def http_json(url: str, *, payload: Any = None, timeout: float = 20) -> Any:
    headers = {"Accept": "application/json", "User-Agent": "solana-ecosystem-pulse/1.0"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method="POST")
    else:
        request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise SourceError(f"{type(exc).__name__}: {exc}") from exc


def rpc_call(rpc_url: str, method: str, params: list[Any] | None = None) -> Any:
    response = http_json(
        rpc_url,
        payload={"jsonrpc": "2.0", "id": method, "method": method, "params": params or []},
    )
    if response.get("error"):
        raise SourceError(f"RPC {method}: {response['error']}")
    return response.get("result")


def safe_number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def round_or_none(value: Any, places: int = 2) -> float | None:
    if value is None:
        return None
    return round(safe_number(value), places)


def calculate_performance(samples: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(samples)
    total_slots = sum(safe_number(row.get("numSlots")) for row in rows)
    total_transactions = sum(safe_number(row.get("numTransactions")) for row in rows)
    total_seconds = sum(safe_number(row.get("samplePeriodSecs")) for row in rows)
    tps = total_transactions / total_seconds if total_seconds else None
    slot_time = total_seconds / total_slots if total_slots else None
    return {
        "sampleCount": len(rows),
        "slots": int(total_slots),
        "transactions": int(total_transactions),
        "sampleSeconds": round_or_none(total_seconds, 2),
        "transactionsPerSecond": round_or_none(tps, 2),
        "secondsPerSlot": round_or_none(slot_time, 4),
    }


def validator_metrics(vote_accounts: dict[str, Any]) -> dict[str, Any]:
    current = vote_accounts.get("current", []) or []
    delinquent = vote_accounts.get("delinquent", []) or []
    total_stake = sum(safe_number(row.get("activatedStake")) for row in current)
    top = sorted(current, key=lambda row: safe_number(row.get("activatedStake")), reverse=True)[:10]
    top_rows = []
    for row in top:
        stake = safe_number(row.get("activatedStake"))
        top_rows.append(
            {
                "voteAccount": row.get("voteAccountPubkey"),
                "node": row.get("nodePubkey"),
                "activatedStakeSol": round(stake / LAMPORTS_PER_SOL, 2),
                "sharePercent": round(stake / total_stake * 100, 2) if total_stake else None,
            }
        )
    return {
        "active": len(current),
        "delinquent": len(delinquent),
        "totalActivatedStakeSol": round(total_stake / LAMPORTS_PER_SOL, 2),
        "topValidators": top_rows,
    }


def supply_metrics(supply: dict[str, Any]) -> dict[str, Any]:
    return {
        "totalSol": round(safe_number(supply.get("total")) / LAMPORTS_PER_SOL, 2),
        "circulatingSol": round(safe_number(supply.get("circulating")) / LAMPORTS_PER_SOL, 2),
        "nonCirculatingSol": round(safe_number(supply.get("nonCirculating")) / LAMPORTS_PER_SOL, 2),
    }


def fetch_solana(rpc_url: str) -> tuple[dict[str, Any], SourceStatus]:
    fetched_at = utc_now()
    try:
        health = rpc_call(rpc_url, "getHealth")
        slot = rpc_call(rpc_url, "getSlot")
        epoch = rpc_call(rpc_url, "getEpochInfo")
        block_time = rpc_call(rpc_url, "getBlockTime", [slot])
        samples = rpc_call(rpc_url, "getRecentPerformanceSamples", [5]) or []
        accounts = rpc_call(rpc_url, "getVoteAccounts") or {}
        supply = rpc_call(rpc_url, "getSupply") or {}
        result = {
            "health": health,
            "slot": slot,
            "epoch": {
                "epoch": epoch.get("epoch"),
                "slotIndex": epoch.get("slotIndex"),
                "slotsInEpoch": epoch.get("slotsInEpoch"),
                "absoluteSlot": epoch.get("absoluteSlot"),
                "blockHeight": epoch.get("blockHeight"),
                "transactionCount": epoch.get("transactionCount"),
            },
            "blockTime": block_time,
            "performance": calculate_performance(samples),
            "validators": validator_metrics(accounts),
            "supply": supply_metrics(supply.get("value", supply)),
        }
        return result, SourceStatus("Solana JSON-RPC", rpc_url, True, fetched_at)
    except SourceError as exc:
        return {}, SourceStatus("Solana JSON-RPC", rpc_url, False, fetched_at, str(exc))


def fetch_market() -> tuple[dict[str, Any], list[SourceStatus]]:
    statuses: list[SourceStatus] = []
    market: dict[str, Any] = {}
    fetched_at = utc_now()
    try:
        data = http_json(COINGECKO_URL)
        sol = data.get("solana", {})
        market["solUsd"] = round_or_none(sol.get("usd"), 4)
        market["sol24hChangePercent"] = round_or_none(sol.get("usd_24h_change"), 2)
        statuses.append(SourceStatus("CoinGecko", COINGECKO_URL, True, fetched_at))
    except SourceError as exc:
        statuses.append(SourceStatus("CoinGecko", COINGECKO_URL, False, fetched_at, str(exc)))
    try:
        data = http_json(DEFILLAMA_URL)
        if data:
            latest = data[-1]
            market["tvlUsd"] = round_or_none(latest.get("tvl"), 2)
            market["tvlTimestamp"] = latest.get("date")
        statuses.append(SourceStatus("DefiLlama", DEFILLAMA_URL, True, fetched_at))
    except (SourceError, IndexError, AttributeError) as exc:
        statuses.append(SourceStatus("DefiLlama", DEFILLAMA_URL, False, fetched_at, str(exc)))
    return market, statuses


def numeric_at(report: dict[str, Any], path: tuple[str, ...]) -> float | None:
    value: Any = report
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    if value is None:
        return None
    return safe_number(value, default=float("nan")) if isinstance(value, (int, float)) else None


def detect_anomalies(current: dict[str, Any], previous: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not previous:
        return []
    checks = [
        (("solana", "performance", "transactionsPerSecond"), "TPS", -0.30, "drop"),
        (("solana", "validators", "delinquent"), "delinquent validators", 5, "increase"),
        (("market", "tvlUsd"), "TVL", -0.15, "drop"),
        (("market", "solUsd"), "SOL price", -0.10, "drop"),
    ]
    anomalies: list[dict[str, Any]] = []
    for path, label, threshold, direction in checks:
        now = numeric_at(current, path)
        old = numeric_at(previous, path)
        if now is None or old is None or math.isnan(now) or math.isnan(old):
            continue
        delta = now - old
        if direction == "drop" and old and delta / old <= threshold:
            anomalies.append({"metric": label, "severity": "warning", "changePercent": round(delta / old * 100, 2), "message": f"{label} dropped {abs(delta / old * 100):.1f}% since the previous snapshot."})
        elif direction == "increase" and delta >= threshold:
            anomalies.append({"metric": label, "severity": "warning", "change": round(delta, 2), "message": f"{label} increased by {delta:.0f} since the previous snapshot."})
    return anomalies


def sample_snapshot() -> dict[str, Any]:
    return {
        "generatedAt": "2026-07-31T12:00:00Z",
        "rpcUrl": DEFAULT_RPC_URL,
        "solana": {
            "health": "ok",
            "slot": 365_012_345,
            "epoch": {"epoch": 845, "slotIndex": 120_000, "slotsInEpoch": 432_000, "absoluteSlot": 365_012_345, "blockHeight": 342_000_000, "transactionCount": 220_000_000_000},
            "blockTime": 1_754_000_000,
            "performance": {"sampleCount": 5, "slots": 1_000, "transactions": 2_450_000, "sampleSeconds": 20, "transactionsPerSecond": 122_500, "secondsPerSlot": 0.02},
            "validators": {"active": 1_250, "delinquent": 7, "totalActivatedStakeSol": 390_000_000, "topValidators": []},
            "supply": {"totalSol": 610_000_000, "circulatingSol": 490_000_000, "nonCirculatingSol": 120_000_000},
        },
        "market": {"solUsd": 182.42, "sol24hChangePercent": 2.8, "tvlUsd": 12_400_000_000},
        "sources": [
            SourceStatus("Solana JSON-RPC", DEFAULT_RPC_URL, True, "2026-07-31T12:00:00Z").as_dict(),
            SourceStatus("CoinGecko", COINGECKO_URL, True, "2026-07-31T12:00:00Z").as_dict(),
            SourceStatus("DefiLlama", DEFILLAMA_URL, True, "2026-07-31T12:00:00Z").as_dict(),
        ],
        "anomalies": [],
    }


def make_report(rpc_url: str, previous: dict[str, Any] | None = None, *, sample: bool = False) -> dict[str, Any]:
    if sample:
        report = sample_snapshot()
        report["anomalies"] = detect_anomalies(report, previous)
        return report
    solana, rpc_status = fetch_solana(rpc_url)
    market, market_statuses = fetch_market()
    report = {
        "generatedAt": utc_now(),
        "rpcUrl": rpc_url,
        "solana": solana,
        "market": market,
        "sources": [rpc_status.as_dict(), *(status.as_dict() for status in market_statuses)],
        "anomalies": [],
    }
    report["anomalies"] = detect_anomalies(report, previous)
    return report


def markdown_report(report: dict[str, Any]) -> str:
    sol = report.get("solana", {})
    perf = sol.get("performance", {})
    val = sol.get("validators", {})
    market = report.get("market", {})
    lines = [
        "# Solana Ecosystem Pulse",
        "",
        f"Generated: `{report.get('generatedAt', 'unknown')}`",
        "",
        "## Executive summary",
        "",
        f"- Network health: **{sol.get('health', 'unavailable')}**",
        f"- Current slot: **{sol.get('slot', 'unavailable')}**",
        f"- Recent throughput: **{perf.get('transactionsPerSecond', 'unavailable')} TPS**",
        f"- Validators: **{val.get('active', 'unavailable')} active**, **{val.get('delinquent', 'unavailable')} delinquent**",
        f"- SOL price: **${market.get('solUsd', 'unavailable')}**",
        f"- Solana TVL: **${market.get('tvlUsd', 'unavailable')}**",
        "",
        "## Network details",
        "",
        f"- Epoch: `{sol.get('epoch', {}).get('epoch', 'unavailable')}`",
        f"- Block height: `{sol.get('epoch', {}).get('blockHeight', 'unavailable')}`",
        f"- Sample window: `{perf.get('sampleSeconds', 'unavailable')} seconds`",
        f"- Activated stake: `{val.get('totalActivatedStakeSol', 'unavailable')} SOL`",
        "",
        "## Alerts",
        "",
    ]
    anomalies = report.get("anomalies", [])
    lines.extend([f"- {item['message']}" for item in anomalies] or ["- No threshold alerts in this snapshot."])
    lines += ["", "## Source health", ""]
    for source in report.get("sources", []):
        status = "OK" if source.get("ok") else "FAILED"
        suffix = f" — {source['error']}" if source.get("error") else ""
        lines.append(f"- **{source.get('name')}**: {status}{suffix}")
    return "\n".join(lines) + "\n"


def write_outputs(report: dict[str, Any], root: Path) -> None:
    reports = root / "reports"
    web = root / "web"
    reports.mkdir(parents=True, exist_ok=True)
    web.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    (reports / "latest.json").write_text(payload, encoding="utf-8")
    (reports / "latest.md").write_text(markdown_report(report), encoding="utf-8")
    (web / "latest.json").write_text(payload, encoding="utf-8")
    (web / "index.html").write_text(render_dashboard(), encoding="utf-8")


def render_dashboard() -> str:
    # The page is self-contained apart from the generated latest.json file.
    return r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Solana Ecosystem Pulse</title>
<style>
:root{color-scheme:dark;--bg:#0b1020;--panel:#141b2f;--muted:#98a2b3;--text:#f5f7fb;--accent:#7c9cff;--good:#45d483;--warn:#ffc857;--bad:#ff6b6b}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top right,#1b2850 0,#0b1020 42%);color:var(--text);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}main{max-width:1180px;margin:auto;padding:40px 20px 64px}header{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;margin-bottom:30px}h1{font-size:clamp(28px,5vw,48px);line-height:1.05;margin:0 0 8px}h2{font-size:20px;margin:0 0 16px}p{color:var(--muted);margin:0}.stamp{color:var(--muted);font-size:13px;text-align:right}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin-bottom:24px}.card,.panel{background:color-mix(in srgb,var(--panel) 90%,transparent);border:1px solid #293453;border-radius:16px;box-shadow:0 12px 28px #0003}.card{padding:18px}.label{font-size:12px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted)}.value{font-size:28px;font-weight:700;margin-top:5px}.unit{font-size:13px;color:var(--muted);font-weight:400}.panel{padding:22px;margin-top:16px}.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:760px){header{display:block}.stamp{text-align:left;margin-top:12px}.two{grid-template-columns:1fr}}table{width:100%;border-collapse:collapse}th,td{text-align:left;border-bottom:1px solid #293453;padding:9px 5px;font-size:13px}th{color:var(--muted);font-weight:500}.pill{display:inline-flex;border-radius:999px;padding:3px 9px;font-size:12px;font-weight:600}.ok{background:#123d2a;color:var(--good)}.warn{background:#4b3b12;color:var(--warn)}.bad{background:#4c2026;color:var(--bad)}.empty{color:var(--muted);padding:8px 0}.source{display:flex;justify-content:space-between;gap:10px;padding:9px 0;border-bottom:1px solid #293453}.source:last-child{border-bottom:0}.source small{color:var(--muted);word-break:break-word}a{color:var(--accent)}footer{color:var(--muted);font-size:12px;margin-top:24px}
</style></head><body><main><header><div><div class="label">Live network intelligence</div><h1>Solana Ecosystem Pulse</h1><p>Auditable, API-key-free network report with conservative anomaly signals.</p></div><div id="stamp" class="stamp">Loading snapshot…</div></header><section id="cards" class="grid"></section><div class="two"><section class="panel"><h2>Epoch & supply</h2><div id="epoch"></div></section><section class="panel"><h2>Alerts</h2><div id="alerts"></div></section></div><section class="panel"><h2>Validator health</h2><div id="validators"></div></section><section class="panel"><h2>Source health</h2><div id="sources"></div></section><footer>Refresh with <code>python solana_report.py</code>. Optional market feeds are best-effort; unavailable values are never fabricated.</footer></main>
<script>
const fmt=(n,d=2)=>n===null||n===undefined?'—':Number(n).toLocaleString(undefined,{maximumFractionDigits:d});
const money=n=>n===null||n===undefined?'—':'$'+fmt(n,2);
const pill=(text,kind='ok')=>`<span class="pill ${kind}">${text}</span>`;
function render(r){const s=r.solana||{},p=s.performance||{},v=s.validators||{},m=r.market||{};document.querySelector('#stamp').innerHTML=`${r.generatedAt||'—'}<br><a href="${r.rpcUrl||'#'}">RPC endpoint</a>`;document.querySelector('#cards').innerHTML=[['Network health',s.health||'—',s.health==='ok'?'ok':'warn'],['Current slot',fmt(s.slot,0),'ok'],['Throughput',fmt(p.transactionsPerSecond)+' TPS','ok'],['Active validators',fmt(v.active,0),'ok'],['SOL price',money(m.solUsd), 'ok'],['TVL',money(m.tvlUsd),'ok']].map(x=>`<article class="card"><div class="label">${x[0]}</div><div class="value">${x[1]}</div>${pill(x[2]==='ok'?'healthy':'review',x[2])}</article>`).join('');const e=s.epoch||{},su=s.supply||{};document.querySelector('#epoch').innerHTML=`<table><tr><th>Epoch</th><td>${fmt(e.epoch,0)}</td></tr><tr><th>Block height</th><td>${fmt(e.blockHeight,0)}</td></tr><tr><th>Epoch progress</th><td>${e.slotIndex&&e.slotsInEpoch?fmt(e.slotIndex/e.slotsInEpoch*100,2)+'%':'—'}</td></tr><tr><th>Circulating supply</th><td>${fmt(su.circulatingSol)} SOL</td></tr><tr><th>24h SOL change</th><td>${m.sol24hChangePercent===undefined?'—':fmt(m.sol24hChangePercent)+'%'}</td></tr></table>`;const a=r.anomalies||[];document.querySelector('#alerts').innerHTML=a.length?a.map(x=>`<div class="source">${pill(x.severity||'warning','warn')}<span>${x.message}</span></div>`).join(''):'<div class="empty">No threshold alerts in this snapshot.</div>';const tops=(v.topValidators||[]).slice(0,10);document.querySelector('#validators').innerHTML=`<p>${fmt(v.active,0)} active · ${fmt(v.delinquent,0)} delinquent · ${fmt(v.totalActivatedStakeSol)} SOL activated stake</p>`+(tops.length?`<table><tr><th>Vote account</th><th>Stake</th><th>Share</th></tr>${tops.map(x=>`<tr><td>${x.voteAccount||'—'}</td><td>${fmt(x.activatedStakeSol)} SOL</td><td>${fmt(x.sharePercent)}%</td></tr>`).join('')}</table>`:'<div class="empty">Top-validator detail unavailable.</div>');document.querySelector('#sources').innerHTML=(r.sources||[]).map(x=>`<div class="source"><div>${pill(x.ok?'OK':'FAILED',x.ok?'ok':'bad')} <strong>${x.name}</strong><br><small>${x.error||x.url}</small></div><small>${x.fetchedAt||''}</small></div>`).join('')||'<div class="empty">No source metadata.</div>'}
fetch('latest.json').catch(()=>fetch('sample.json')).then(x=>x.json()).then(render).catch(e=>{document.querySelector('#stamp').textContent='Snapshot unavailable: '+e.message});
</script></body></html>'''


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def run_once(root: Path, rpc_url: str, use_sample: bool) -> dict[str, Any]:
    previous = load_json(root / "reports" / "latest.json")
    report = make_report(rpc_url, previous, sample=use_sample)
    if previous:
        (root / "reports" / "previous.json").write_text(json.dumps(previous, indent=2) + "\n", encoding="utf-8")
    write_outputs(report, root)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc", default=DEFAULT_RPC_URL, help="Solana JSON-RPC URL")
    parser.add_argument("--output", default=".", help="Project output directory")
    parser.add_argument("--sample", action="store_true", help="Generate a deterministic offline sample")
    parser.add_argument("--interval", type=int, default=0, help="Repeat every N seconds")
    args = parser.parse_args(argv)
    root = Path(args.output).resolve()
    if args.interval < 0:
        parser.error("--interval must be non-negative")
    while True:
        report = run_once(root, args.rpc, args.sample)
        ok = sum(1 for source in report.get("sources", []) if source.get("ok"))
        print(f"Wrote snapshot at {report['generatedAt']} ({ok}/{len(report.get('sources', []))} sources healthy)")
        if not args.interval:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
