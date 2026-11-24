# Gambit

Chess for Luma, built with LumaUI.

Play the computer at five levels, from your first game to grandmaster, or a
friend on the same device. A calm board that fits a phone, a tablet and a
desktop; tap or drag the pieces, or play with the keyboard alone.

- **New game**: against the computer (Easy, Casual, Club, Hard, Master) or two players
- **Puzzles**: 2,338 positions from the Lichess puzzle database, picked near your level, with a
  rating that follows you, hints and the solution when you want it
- **Hint**: an arrow shows a good move when you are stuck
- **Undo**, **Resign**, **Flip board**, and every move of the game in the details pane
- **Openings** named as you play, and a **review** of each finished game: accuracy, inaccuracies,
  mistakes and blunders, with the better move
- The game in progress is kept between runs
- Works offline: no account, nothing leaves the device

One app on a phone, a tablet and a desktop. The board is Gambit's only drawn
content; everything around it is LumaUI (AppWindow, Island, ActionCenter, panels,
CornerPill, DetailsPane, toasts, confirmations in the bar).

## Run

On Luma, from the source tree, with a Stockfish binary at hand:

```sh
GAMBIT_ENGINE=/path/to/stockfish ./run-app
```

## Build

```sh
flatpak-builder --user --install --install-deps-from=luma build-dir flatpak/io.github.elomkdn.Gambit.json
```

The manifest builds Stockfish 11 from its pinned source archive. `luma lint` and
`luma test` pass.

## Credits

- Engine: [Stockfish](https://stockfishchess.org) 11 by the Stockfish developers (GPL-3.0)
- Rules and notation: [python-chess](https://github.com/niklasf/python-chess) 1.11.2
  by Niklas Fiekas (GPL-3.0-or-later), vendored as `src/chess/`
- Pieces: the cburnett set by Colin M.L. Burnett (GPL-2.0-or-later), as used by Lichess
- Puzzles: the [Lichess puzzle database](https://database.lichess.org) (CC0), picked by
  `tools/build_puzzles.py` (played at least 2,000 times, well liked, settled rating, short solution)
- Opening names: [lichess-org/chess-openings](https://github.com/lichess-org/chess-openings) (CC0),
  turned into a table of positions by `tools/build_openings.py`

## License

GPL-3.0-or-later. Third-party licences are in `LICENSES/`.
