#!/usr/bin/env python3
"""Pick Gambit's puzzles from the Lichess puzzle database (CC0).

Keeps well-tried puzzles only: played at least 2,000 times, liked, with a settled
rating and a short solution, spread evenly from 500 to 2,800 in 100-point steps.

Usage: python3 -I tools/build_puzzles.py lichess_db_puzzle.csv.zst data/puzzles.json
"""
import csv
import io
import json
import subprocess
import sys
from collections import defaultdict

PER_STEP = 120
LOW, HIGH = 500, 2800


def main(source, target):
    zstd = subprocess.Popen(["zstdcat", source], stdout=subprocess.PIPE)
    buckets = defaultdict(list)
    for row in csv.DictReader(io.TextIOWrapper(zstd.stdout, encoding="utf-8")):
        try:
            rating, deviation = int(row["Rating"]), int(row["RatingDeviation"])
            popularity, plays = int(row["Popularity"]), int(row["NbPlays"])
        except ValueError:
            continue
        moves = row["Moves"].split()
        if not (LOW <= rating < HIGH and deviation <= 80 and popularity >= 90 and plays >= 2000):
            continue
        if not 2 <= len(moves) <= 8:        # the opponent's move, then at most four of yours
            continue
        buckets[rating // 100].append((popularity, plays, row["PuzzleId"], row["FEN"], row["Moves"], rating,
                                       row["Themes"]))
    zstd.wait()
    chosen = []
    for step in sorted(buckets):
        best = sorted(buckets[step], key=lambda p: (-p[0], -p[1]))[:PER_STEP]
        chosen += [[pid, fen, moves, rating, themes] for _pop, _plays, pid, fen, moves, rating, themes in best]
    chosen.sort(key=lambda p: p[3])
    with open(target, "w", encoding="utf-8") as out:
        json.dump({"source": "Lichess puzzle database, https://database.lichess.org (CC0)",
                   "puzzles": chosen}, out, separators=(",", ":"))
    print(f"{len(chosen)} puzzles from {len(buckets)} rating steps")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
