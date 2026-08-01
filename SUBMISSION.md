# Superteam submission — Solana Ecosystem Pulse

## Summary

Solana Ecosystem Pulse is an API-key-free, dependency-free report generator
and dark interactive dashboard for the current state of the Solana ecosystem.
It combines direct Solana JSON-RPC telemetry with best-effort public market
context and records source health, timestamps, and conservative anomaly alerts.

## Links

- Source: https://github.com/keeperguard-labs/solana-ecosystem-pulse
- Live dashboard: https://keeperguard-labs.github.io/solana-ecosystem-pulse/
- Reproducible sample: `examples/sample.json` and `examples/sample.md`

## What is included

- Core network health, slot/epoch/block height, throughput, validator health,
  stake concentration, and supply metrics.
- Public CoinGecko SOL price and DefiLlama Solana TVL as optional context.
- Source-health metadata; optional-source failures never fabricate values or
  hide the core RPC report.
- Threshold-based anomaly detection against the previous snapshot.
- JSON, Markdown, and responsive dark HTML outputs.
- Offline unit tests covering throughput, validator ranking, anomaly detection,
  and output generation.

## Reproduction

```powershell
python solana_report.py --sample
python -m unittest discover -s tests -v
python solana_report.py
python -m http.server 8000 --directory web
```

The live command uses `https://api.mainnet-beta.solana.com` by default and can
be pointed at another RPC endpoint with `--rpc`. No API key or social account is
needed. The static dashboard opens with the checked-in sample fallback before
the first live refresh.

## Design notes

The report deliberately prefers transparent, auditable measurements over
unverifiable social scraping. Each source is time-stamped and marked healthy or
failed, while alerts explain the threshold that triggered them. This makes the
dashboard useful in CI or a scheduled task as well as in a browser.
