# Solana Ecosystem Pulse

An API-key-free Solana network report and dark interactive dashboard. It collects
network data through public Solana JSON-RPC, optionally enriches it with public
CoinGecko and DefiLlama endpoints, and emits JSON, Markdown, and an interactive
HTML dashboard.

## Quick start

Requires Python 3.10+ and only the standard library.

```powershell
python solana_report.py --sample
python -m http.server 8000 --directory web
```

Open <http://localhost:8000>. The sample command is deterministic and works
offline. For live data, run:

```powershell
python solana_report.py
```

The default RPC endpoint is `https://api.mainnet-beta.solana.com`. Use
`--rpc` to point at another public or private Solana JSON-RPC endpoint. No RPC
key is required by the default configuration.

## Outputs

- `reports/latest.json`: machine-readable snapshot with source health and alerts.
- `reports/latest.md`: human-readable report.
- `web/index.html`: dark responsive dashboard.
- `web/latest.json`: dashboard data copy for static hosting.

The same static bundle is mirrored in `docs/` so it can be served directly by
GitHub Pages without a build step.

The repository also includes a deterministic `web/sample.json` fallback so the
dashboard opens immediately after cloning, before the first live refresh.

The generator keeps a previous snapshot in `reports/previous.json`. Anomaly
signals are deliberately conservative and explain their threshold in the JSON
and Markdown output.

## Data sources

The core report uses only public Solana JSON-RPC methods: `getHealth`,
`getSlot`, `getEpochInfo`, `getBlockTime`, `getRecentPerformanceSamples`,
`getVoteAccounts`, and `getSupply`. Market context is best-effort and uses
public CoinGecko and DefiLlama endpoints; a failed optional source never hides
the core network report. The report records source status and timestamps so a
reviewer can audit freshness.

No X/Twitter scraping or social account is required. The dashboard explicitly
labels unavailable optional data instead of inventing values.

## Automation

Run the generator from cron, Task Scheduler, or CI at a configurable interval:

```powershell
python solana_report.py --interval 900
```

`--interval` runs forever and refreshes atomically every 15 minutes. A failed
refresh preserves the last successful snapshot and writes the error to the
source health section.

## Tests

```powershell
python -m unittest discover -s tests -v
```

All tests are offline and use the standard library.
