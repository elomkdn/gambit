# SPDX-License-Identifier: GPL-3.0-or-later
"""The board: the game's own content, drawn by Gambit; everything around it is LumaUI.

Tap a piece then a square, or drag it there; with the keyboard, the arrows move a
cursor and Enter picks up and puts down. The last move, the legal squares, check
and a hint are shown on the board itself. Pieces are the cburnett set
(GPL-2.0-or-later), drawn by librsvg at the board's size so they stay sharp.
"""
from __future__ import annotations

import math
import os
import time
from pathlib import Path

import cairo
import chess
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Rsvg", "2.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, GObject, Graphene, Gsk, Gtk, Pango, PangoCairo, Rsvg  # noqa: E402

try:
    from luma_appkit import motion_duration, type_font
except ImportError:  # pragma: no cover - outside the Luma runtime
    motion_duration = lambda ms: ms
    type_font = None

MARGIN = 12
RADIUS = 10
# The board's own colours: a cool, quiet pair that sits with Luma in light and dark.
LIGHT = (0.882, 0.898, 0.914)
DARK = (0.545, 0.627, 0.690)
SHOT_SCALE = float(os.environ.get("APP_SHOT_SCALE", "1"))   # store screenshots render at 3x
PIECE_FILE = {chess.PAWN: "P", chess.KNIGHT: "N", chess.BISHOP: "B", chess.ROOK: "R", chess.QUEEN: "Q",
              chess.KING: "K"}
PIECE_NAME = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop", chess.ROOK: "rook",
              chess.QUEEN: "queen", chess.KING: "king"}


def _rect(x, y, w, h):
    return Graphene.Rect().init(x, y, w, h)


class BoardView(Gtk.Widget):
    __gtype_name__ = "GambitBoard"
    __gsignals__ = {"move": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self, pieces_dir: Path):
        super().__init__(hexpand=True, vexpand=True, focusable=True, accessible_role=Gtk.AccessibleRole.IMG)
        self.add_css_class("gambit-board")
        self.pieces_dir = Path(pieces_dir)
        self.board = chess.Board()
        self.flipped = False
        self.interactive = True
        self.last: chess.Move | None = None
        self.hint: chess.Move | None = None
        self.selected: int | None = None
        self.cursor: int | None = None
        self.choose_promotion = None        # callable(from, to, done(piece_type)) set by the window
        self._textures: dict = {}
        self._handles: dict = {}
        self._press = None
        self._drag = None
        self._anim = None
        self._tick = 0
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", self._drag_end)
        self.add_controller(drag)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)

    # ── what it shows ─────────────────────────────────────────────────

    def show(self, board: chess.Board, *, last: chess.Move | None = None, animate: chess.Move | None = None,
             before: chess.Board | None = None) -> None:
        """Show `board`; `animate` slides that move's piece across from where it stood in `before`."""
        self.board = board.copy(stack=False)
        self.last = last
        self.hint = None
        self.selected = None
        self._drag = None
        if animate is not None and before is not None:
            piece = before.piece_at(animate.from_square)
            duration = motion_duration(170) / 1000
            if piece is not None and duration > 0:
                self._anim = (piece, animate.from_square, animate.to_square, time.monotonic(), duration)
                if not self._tick:
                    self._tick = self.add_tick_callback(self._animate)
        self._describe()
        self.queue_draw()

    def set_flipped(self, flipped: bool) -> None:
        self.flipped = flipped
        self.queue_draw()

    def set_interactive(self, interactive: bool) -> None:
        self.interactive = interactive
        if not interactive:
            self.selected = None
            self._drag = None
        self.queue_draw()

    def show_selection(self, square: int | None) -> None:
        """Pick up the piece on `square` as if tapped: its legal squares show."""
        self.selected = square
        self.queue_draw()

    def show_hint(self, move: chess.Move | None) -> None:
        self.hint = move
        self.queue_draw()

    def _describe(self) -> None:
        side = "White" if self.board.turn else "Black"
        words = f"Chess board, {side} to move"
        if self.cursor is not None:
            piece = self.board.piece_at(self.cursor)
            what = f"{'white' if piece.color else 'black'} {PIECE_NAME[piece.piece_type]}" if piece else "empty"
            words += f". {chess.square_name(self.cursor)}, {what}"
        self.update_property([Gtk.AccessibleProperty.LABEL], [words])

    # ── geometry ──────────────────────────────────────────────────────

    def _geometry(self):
        width, height = self.get_width(), self.get_height()
        size = max(8, int((min(width, height) - 2 * MARGIN) // 8))
        side = size * 8
        return (width - side) / 2, (height - side) / 2, size

    def _origin(self, square: int, geometry):
        x0, y0, size = geometry
        file, rank = chess.square_file(square), chess.square_rank(square)
        col = 7 - file if self.flipped else file
        row = rank if self.flipped else 7 - rank
        return x0 + col * size, y0 + row * size

    def _square_at(self, x: float, y: float, geometry=None) -> int | None:
        x0, y0, size = geometry or self._geometry()
        col, row = math.floor((x - x0) / size), math.floor((y - y0) / size)
        if not (0 <= col < 8 and 0 <= row < 8):
            return None
        file = 7 - col if self.flipped else col
        rank = row if self.flipped else 7 - row
        return chess.square(file, rank)

    def do_measure(self, orientation, for_size):
        return 240, 480, -1, -1

    # ── input ─────────────────────────────────────────────────────────

    def _movable(self, square: int | None) -> bool:
        piece = self.board.piece_at(square) if square is not None else None
        return bool(self.interactive and piece and piece.color == self.board.turn)

    def _targets(self, square: int) -> set[int]:
        return {move.to_square for move in self.board.legal_moves if move.from_square == square}

    def _drag_begin(self, gesture, x, y):
        self.grab_focus()
        self._press = (self._square_at(x, y), x, y)

    def _drag_update(self, gesture, dx, dy):
        if self._press is None:
            return
        square, x, y = self._press
        if self._drag is None and math.hypot(dx, dy) > 6 and self._movable(square):
            self._drag = [square, x + dx, y + dy]
            self.selected = square
        if self._drag is not None:
            self._drag[1], self._drag[2] = x + dx, y + dy
            self.queue_draw()

    def _drag_end(self, gesture, dx, dy):
        press, self._press = self._press, None
        if press is None:
            return
        square, x, y = press
        if self._drag is not None:
            origin = self._drag[0]
            self._drag = None
            target = self._square_at(x + dx, y + dy)
            if target is not None and target != origin and target in self._targets(origin):
                self._attempt(origin, target)
            self.queue_draw()
            return
        if math.hypot(dx, dy) <= 6:
            self._tap(square)

    def _tap(self, square: int | None) -> None:
        if square is None or not self.interactive:
            self.selected = None
        elif self.selected is not None and square in self._targets(self.selected):
            self._attempt(self.selected, square)
            return
        elif self._movable(square) and square != self.selected:
            self.selected = square
        else:
            self.selected = None
        self.queue_draw()

    def _attempt(self, origin: int, target: int) -> None:
        piece = self.board.piece_at(origin)
        promotes = (piece is not None and piece.piece_type == chess.PAWN
                    and chess.square_rank(target) in (0, 7)
                    and chess.Move(origin, target, chess.QUEEN) in self.board.legal_moves)
        self.selected = None
        if promotes and self.choose_promotion is not None:
            self.choose_promotion(origin, target,
                                  lambda kind: self.emit("move", chess.Move(origin, target, kind).uci()))
            self.queue_draw()
            return
        move = chess.Move(origin, target, chess.QUEEN if promotes else None)
        if move in self.board.legal_moves:
            self.emit("move", move.uci())
        self.queue_draw()

    def _key(self, _controller, keyval, _code, _state):
        steps = {Gdk.KEY_Left: (-1, 0), Gdk.KEY_Right: (1, 0), Gdk.KEY_Up: (0, 1), Gdk.KEY_Down: (0, -1)}
        if keyval in steps:
            if self.cursor is None:
                self.cursor = chess.E2 if self.board.turn == chess.WHITE else chess.E7
            else:
                df, dr = steps[keyval]
                if self.flipped:
                    df, dr = -df, -dr
                file = min(7, max(0, chess.square_file(self.cursor) + df))
                rank = min(7, max(0, chess.square_rank(self.cursor) + dr))
                self.cursor = chess.square(file, rank)
            self._describe()
            self.queue_draw()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space) and self.cursor is not None:
            self._tap(self.cursor)
            return True
        if keyval == Gdk.KEY_Escape and self.selected is not None:
            self.selected = None
            self.queue_draw()
            return True
        return False

    # ── motion ────────────────────────────────────────────────────────

    def _animate(self, _widget, _clock):
        if self._anim is None:
            self._tick = 0
            return GLib.SOURCE_REMOVE
        _piece, _a, _b, start, duration = self._anim
        if time.monotonic() - start >= duration:
            self._anim = None
            self._tick = 0
            self.queue_draw()
            return GLib.SOURCE_REMOVE
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    # ── drawing ───────────────────────────────────────────────────────

    def _color(self, role, fallback):
        found, value = self.get_style_context().lookup_color(role)
        return (value.red, value.green, value.blue, value.alpha) if found else fallback

    def _density(self) -> float:
        """Device pixels per point: the screen's, or a screenshot's when one renders at 3x."""
        return self.get_scale_factor() * SHOT_SCALE

    def _texture(self, piece: chess.Piece, pixels: int):
        key = (piece.symbol(), pixels)
        texture = self._textures.get(key)
        if texture is None:
            name = ("w" if piece.color else "b") + PIECE_FILE[piece.piece_type]
            handle = self._handles.get(name)
            if handle is None:
                handle = self._handles[name] = Rsvg.Handle.new_from_file(str(self.pieces_dir / f"{name}.svg"))
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, pixels, pixels)
            viewport = Rsvg.Rectangle()
            viewport.x, viewport.y, viewport.width, viewport.height = 0, 0, pixels, pixels
            handle.render_document(cairo.Context(surface), viewport)
            surface.flush()
            texture = Gdk.MemoryTexture.new(pixels, pixels, Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED,
                                            GLib.Bytes.new(bytes(surface.get_data())), surface.get_stride())
            if len(self._textures) > 64:        # a resize leaves old sizes behind
                self._textures.clear()
            self._textures[key] = texture
        return texture

    def do_snapshot(self, snapshot):
        geometry = self._geometry()
        x0, y0, size = geometry
        side = size * 8
        accent = self._color("luma_accent", (0.32, 0.5, 0.68, 1.0))
        danger = self._color("luma_destructive", (0.85, 0.25, 0.25, 1.0))
        focus = self._color("luma_focus_ring", accent)
        outline = Gsk.RoundedRect()
        outline.init_from_rect(_rect(x0, y0, side, side), RADIUS)
        snapshot.push_rounded_clip(outline)
        for square in chess.SQUARES:
            x, y = self._origin(square, geometry)
            light = (chess.square_file(square) + chess.square_rank(square)) % 2 == 1
            snapshot.append_color(_rgba(*(LIGHT if light else DARK), 1.0), _rect(x, y, size, size))
        if self.last is not None:
            for square in (self.last.from_square, self.last.to_square):
                x, y = self._origin(square, geometry)
                snapshot.append_color(_rgba(*accent[:3], 0.34), _rect(x, y, size, size))
        if self.selected is not None:
            x, y = self._origin(self.selected, geometry)
            snapshot.append_color(_rgba(*accent[:3], 0.5), _rect(x, y, size, size))
        cr = snapshot.append_cairo(_rect(x0, y0, side, side))
        if self.board.is_check():
            king = self.board.king(self.board.turn)
            if king is not None:
                x, y = self._origin(king, geometry)
                glow = cairo.RadialGradient(x + size / 2, y + size / 2, 0, x + size / 2, y + size / 2, size * 0.7)
                glow.add_color_stop_rgba(0, *danger[:3], 0.85)
                glow.add_color_stop_rgba(0.55, *danger[:3], 0.35)
                glow.add_color_stop_rgba(1, *danger[:3], 0.0)
                cr.set_source(glow)
                cr.rectangle(x, y, size, size)
                cr.fill()
        self._draw_coordinates(cr, geometry)
        moving = self._anim[2] if self._anim else None
        dragging = self._drag[0] if self._drag else None
        pixels = max(8, int(size * self._density()))
        for square, piece in self.board.piece_map().items():
            if square in (moving, dragging):
                continue
            x, y = self._origin(square, geometry)
            snapshot.append_texture(self._texture(piece, pixels), _rect(x, y, size, size))
        cr = snapshot.append_cairo(_rect(x0, y0, side, side))
        if self.selected is not None:
            for target in self._targets(self.selected):
                x, y = self._origin(target, geometry)
                cx, cy = x + size / 2, y + size / 2
                if self.board.piece_at(target) is not None or target == self.board.ep_square:
                    cr.set_source_rgba(0.05, 0.08, 0.12, 0.28)
                    cr.set_line_width(size * 0.08)
                    cr.arc(cx, cy, size * 0.44, 0, 2 * math.pi)
                    cr.stroke()
                else:
                    cr.set_source_rgba(0.05, 0.08, 0.12, 0.24)
                    cr.arc(cx, cy, size * 0.15, 0, 2 * math.pi)
                    cr.fill()
        if self.hint is not None:
            self._draw_arrow(cr, self.hint, geometry, accent)
        if self.cursor is not None and self.has_visible_focus():
            x, y = self._origin(self.cursor, geometry)
            cr.set_source_rgba(*focus[:3], 1.0)
            cr.set_line_width(3)
            cr.rectangle(x + 1.5, y + 1.5, size - 3, size - 3)
            cr.stroke()
        snapshot.pop()
        if self._anim is not None:
            piece, origin, target, start, duration = self._anim
            t = min(1.0, (time.monotonic() - start) / duration)
            t = 1 - (1 - t) ** 3
            ax, ay = self._origin(origin, geometry)
            bx, by = self._origin(target, geometry)
            snapshot.append_texture(self._texture(piece, pixels),
                                    _rect(ax + (bx - ax) * t, ay + (by - ay) * t, size, size))
        if self._drag is not None:
            piece = self.board.piece_at(self._drag[0])
            if piece is not None:
                lift = size * 1.15
                snapshot.append_texture(self._texture(piece, max(8, int(lift * self._density()))),
                                        _rect(self._drag[1] - lift / 2, self._drag[2] - lift * 0.6, lift, lift))

    def _draw_coordinates(self, cr, geometry):
        size = geometry[2]
        if size < 34:
            return
        layout_font = type_font("caption") if type_font else Pango.FontDescription.from_string("Sans 8")
        for index in range(8):
            file_square = chess.square(7 - index if self.flipped else index, 7 if self.flipped else 0)
            rank_square = chess.square(7 if self.flipped else 0, 7 - index if self.flipped else index)
            for square, text, corner in ((file_square, chess.FILE_NAMES[chess.square_file(file_square)], "br"),
                                         (rank_square, str(chess.square_rank(rank_square) + 1), "tl")):
                x, y = self._origin(square, geometry)
                light = (chess.square_file(square) + chess.square_rank(square)) % 2 == 1
                layout = PangoCairo.create_layout(cr)
                font = layout_font.copy()
                font.set_weight(Pango.Weight.BOLD)
                layout.set_font_description(font)
                layout.set_text(text, -1)
                _ink, logical = layout.get_pixel_extents()
                pad = max(2, size * 0.06)
                tx = x + size - logical.width - pad if corner == "br" else x + pad
                ty = y + size - logical.height - pad * 0.5 if corner == "br" else y + pad * 0.5
                cr.move_to(tx, ty)
                cr.set_source_rgba(*(DARK if light else LIGHT), 0.95)
                PangoCairo.show_layout(cr, layout)
                cr.new_path()

    def _draw_arrow(self, cr, move: chess.Move, geometry, color):
        size = geometry[2]
        ax, ay = self._origin(move.from_square, geometry)
        bx, by = self._origin(move.to_square, geometry)
        ax, ay, bx, by = ax + size / 2, ay + size / 2, bx + size / 2, by + size / 2
        angle = math.atan2(by - ay, bx - ax)
        head = size * 0.42
        tip_x, tip_y = bx - math.cos(angle) * size * 0.12, by - math.sin(angle) * size * 0.12
        base_x, base_y = tip_x - math.cos(angle) * head, tip_y - math.sin(angle) * head
        cr.set_source_rgba(*color[:3], 0.82)
        cr.set_line_width(size * 0.16)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.move_to(ax, ay)
        cr.line_to(base_x, base_y)
        cr.stroke()
        spread = head * 0.62
        cr.move_to(tip_x, tip_y)
        cr.line_to(base_x + math.sin(angle) * spread, base_y - math.cos(angle) * spread)
        cr.line_to(base_x - math.sin(angle) * spread, base_y + math.cos(angle) * spread)
        cr.close_path()
        cr.fill()


def _rgba(r, g, b, a):
    color = Gdk.RGBA()
    color.red, color.green, color.blue, color.alpha = r, g, b, a
    return color
