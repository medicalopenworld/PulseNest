"""agent_sweep_batch.py — Claude Agent SDK batch-processing example.

Iterates over the AFE SWEEP TEST CSV files in captures/ and launches one
specialized agent per file to analyze it (saturation, probe_state mismatches,
suspicious channels). Each agent writes nothing — the script collects the
analysis text and saves one Markdown report per CSV under reports/sweep_agents/.

This is the pattern for high-volume / unattended jobs:
  - a plain Python process drives N agent sessions (optionally in parallel)
  - each session is a full Claude Code agent with tool access (Read, Grep...)
  - the same loop can run 24/7 under cron/systemd/Task Scheduler

Requirements:
    pip install claude-agent-sdk
    (authenticates via Claude Code login or ANTHROPIC_API_KEY)

Usage:
    python agent_sweep_batch.py            # process all sweep CSVs
    python agent_sweep_batch.py --limit 2  # quick test with 2 files
"""

import argparse
import asyncio
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

PROJECT_DIR = Path(__file__).resolve().parent
CAPTURES_DIR = PROJECT_DIR / "captures"
REPORTS_DIR = PROJECT_DIR / "reports" / "sweep_agents"

MAX_PARALLEL_AGENTS = 3  # concurrent agent sessions

ANALYSIS_PROMPT = """\
You are an AFE4490 sweep-test analyst. Analyze the CSV file: {csv_path}

Context: each row is one sweep step of an AFE4490 pulse-oximeter front-end
(ESP32-S3 + AFE4490). Key columns:
- probe_state_expected vs probe_state_calculated + probe_state_check (OK/NOT OK)
- LED1mA/LED2mA, RF1/RF2, RG1/RG2, ambdac_uA: swept hardware parameters
- LEDx/ALEDx mean/min/max/pp/std: raw 22-bit signed ADC codes
  (empirical rails: +2096921 / -2096919 — codes near them mean ADC saturation)
- V_TIA_* [V]: reconstructed TIA differential output (linear spec 1.0 V,
  empirical linear limit 1.8 V, hard clip ~1.94 V)
- I_PD_* [uA]: reconstructed photodiode current

Report (concise, Markdown):
1. Sweep summary: which parameters were swept, ranges, number of steps.
2. Saturation: rows where any ADC code approaches the rails or |V_TIA| > 1.0 V.
3. Probe-state mismatches: rows with probe_state_check = "NOT OK" and any
   pattern you see (e.g. mismatch only at low LED current).
4. Anomalies: outlier std/pp values, empty columns, non-monotonic responses.
Keep it under 40 lines. Do not modify any file.
"""


async def analyze_csv(csv_path: Path, semaphore: asyncio.Semaphore) -> None:
    """Run one agent session to analyze a single sweep CSV."""
    async with semaphore:
        print(f"[agent] start  {csv_path.name}")

        options = ClaudeAgentOptions(
            cwd=str(PROJECT_DIR),
            allowed_tools=["Read", "Grep", "Glob", "Bash"],
            permission_mode="bypassPermissions",  # unattended batch job
            max_turns=15,
        )

        report_lines: list[str] = []
        cost_usd = None

        async for message in query(
            prompt=ANALYSIS_PROMPT.format(csv_path=csv_path), options=options
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        report_lines.append(block.text)
            elif isinstance(message, ResultMessage):
                cost_usd = message.total_cost_usd

        report_path = REPORTS_DIR / (csv_path.stem + ".md")
        report_path.write_text(
            f"# Sweep analysis — {csv_path.name}\n\n" + "\n\n".join(report_lines),
            encoding="utf-8",
        )
        cost = f"${cost_usd:.4f}" if cost_usd is not None else "n/a"
        print(f"[agent] done   {csv_path.name} -> {report_path.name} (cost {cost})")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="max CSVs to process")
    args = parser.parse_args()

    csv_files = sorted(CAPTURES_DIR.glob("afe_sweep_test_*.csv"))
    if args.limit:
        csv_files = csv_files[: args.limit]
    if not csv_files:
        print(f"No sweep CSVs found in {CAPTURES_DIR}")
        return

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Processing {len(csv_files)} CSVs, {MAX_PARALLEL_AGENTS} agents in parallel")

    semaphore = asyncio.Semaphore(MAX_PARALLEL_AGENTS)
    await asyncio.gather(*(analyze_csv(p, semaphore) for p in csv_files))

    print(f"All reports written to {REPORTS_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
