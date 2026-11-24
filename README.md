# Gambit

Chess for Luma, built with LumaUI.

Play the computer at five levels, from your first game to grandmaster, or a
friend on the same device. A calm board that fits a phone, a tablet and a
desktop; tap or drag the pieces, or play with the keyboard alone.

- **New game**: against the computer (Easy, Casual, Club, Hard, Master) or two players
- **Hint**: an arrow shows a good move when you are stuck
- **Undo**, **Resign**, **Flip board**, and every move of the game in the details pane
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

## License

GPL-3.0-or-later. Third-party licences are in `LICENSES/`.
