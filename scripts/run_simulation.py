#!/usr/bin/env python
"""Run N all-AI games and dump a CSV of outcomes.

Example:
    poetry run python scripts/run_simulation.py --games 100 --players 4
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from random import Random

from conquest.ai.archetypes import ARCHETYPES
from conquest.simulation.harness import run_simulation


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--games", type=int, default=100)
    p.add_argument("--players", type=int, default=4)
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--max-rounds", type=int, default=200)
    p.add_argument("--out", type=str, default="-", help="output CSV path or - for stdout")
    args = p.parse_args()

    archetype_pool = list(ARCHETYPES)
    rng = Random(args.seed)
    out_file = sys.stdout if args.out == "-" else open(args.out, "w", newline="")
    writer = csv.writer(out_file)
    writer.writerow(
        ["game_seed", "archetypes", "winner", "rounds", "outbreaks", "ended_reason", "elapsed_ms"]
    )

    t0 = time.perf_counter()
    for i in range(args.games):
        archetypes = [rng.choice(archetype_pool) for _ in range(args.players)]
        result = run_simulation(
            seed=args.seed + i,
            archetypes=archetypes,
            max_rounds=args.max_rounds,
        )
        writer.writerow(
            [
                result.seed,
                "|".join(result.archetypes),
                result.winner_archetype or "",
                result.rounds_played,
                result.outbreaks,
                result.ended_reason or "",
                f"{result.elapsed_ms:.1f}",
            ]
        )
    elapsed = time.perf_counter() - t0
    print(f"# {args.games} games in {elapsed:.1f}s", file=sys.stderr)
    if out_file is not sys.stdout:
        out_file.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
