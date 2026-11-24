#!/usr/bin/env python3
"""Turn Lichess's chess-openings list (CC0) into a table of positions and their names.

Each line's moves are replayed and the position they reach is the key, so an
opening is recognised however its moves came about. Where several lines reach
the same position, the shortest names it.

Usage: python3 -I tools/build_openings.py OPENINGS_DIR data/openings.json
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import chess  # noqa: E402


def main(folder, target):
    table = {}
    for name in "abcde":
        with open(Path(folder) / f"{name}.tsv", encoding="utf-8") as source:
            for row in csv.DictReader(source, delimiter="\t"):
                board = chess.Board()
                plies = 0
                for token in row["pgn"].split():
                    if token.endswith("."):
                        continue
                    board.push_san(token)
                    plies += 1
                key = board.epd()
                if key not in table or plies < table[key][2]:
                    table[key] = [row["eco"], row["name"], plies]
    with open(target, "w", encoding="utf-8") as out:
        json.dump({"source": "lichess-org/chess-openings (CC0)",
                   "openings": {key: value[:2] for key, value in table.items()}}, out, separators=(",", ":"),
                  ensure_ascii=False)
    print(f"{len(table)} positions")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
