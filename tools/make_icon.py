#!/usr/bin/env python3
"""Draw Gambit's icon in Luma's family style: a white knight on a green plate.

The knight is the cburnett knight (GPL-2.0-or-later), the same as on the board,
drawn large, lit from the upper left, with Luma's edge light and shadows.

Usage: python3 -I tools/make_icon.py data/io.github.elomkdn.Gambit.svg
"""
import sys

P = "gmb"
PLATE = ("#4cc488", "#178a55")
DARK = "#0b4a2c"
# The knight's outline and its head, from the cburnett set (45 × 45 units).
BODY = "M22 10c10.5 1 16.5 8 16 29H15c0-9 10-6.5 8-21"
HEAD = ("M24 18c.38 2.91-5.55 7.37-8 9-3 2-2.82 4.34-5 4-1.042-.94 1.41-3.04 0-3-1 0 .19 1.23-1 2-1 0-4.003 1-4-4"
        " 0-2 6-12 6-12s1.89-1.9 2-3.5c-.73-.994-.5-2-.5-3 1-1 3 2.5 3 2.5h2s.78-1.992 2.5-3c1 0 1 3 1 3")
EYE = "M9.5 25.5a.5.5 0 1 1-1 0 .5.5 0 1 1 1 0m5.433-9.75a.5 1.5 30 1 1-.866-.5.5 1.5 30 1 1 .866.5"
SCALE = 11.2
CENTER = (21.5, 24.0)       # the knight's middle, in its own units
AT = (512, 492)


def place():
    tx, ty = AT[0] - CENTER[0] * SCALE, AT[1] - CENTER[1] * SCALE
    return f"translate({tx:.1f} {ty:.1f}) scale({SCALE})"


def main(path):
    turn = place()
    knight = f'<path d="{BODY}"/><path d="{HEAD}"/>'
    mask = lambda name, dx, dy: (
        f'<mask id="{P}-{name}" maskUnits="userSpaceOnUse" x="0" y="0" width="1024" height="1024">'
        f'<g transform="{turn}" fill="#fff" stroke="#fff" stroke-width="1.5" stroke-linejoin="round">{knight}</g>'
        f'<g transform="translate({dx} {dy})"><g transform="{turn}" fill="#000" stroke="#000" stroke-width="1.5" '
        f'stroke-linejoin="round">{knight}</g></g></mask>')
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">
<defs>
<linearGradient id="{P}-pl" x1="0.2" y1="0" x2="0.8" y2="1"><stop offset="0" stop-color="{PLATE[0]}"/><stop offset="1" stop-color="{PLATE[1]}"/></linearGradient>
<radialGradient id="{P}-plh" cx="0.26" cy="0.12" r="0.8"><stop offset="0" stop-color="#fff" stop-opacity="0.2"/><stop offset="0.55" stop-color="#fff" stop-opacity="0.05"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>
<linearGradient id="{P}-rim" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0.42"/><stop offset="0.1" stop-color="#fff" stop-opacity="0"/><stop offset="0.86" stop-color="{DARK}" stop-opacity="0"/><stop offset="1" stop-color="{DARK}" stop-opacity="0.35"/></linearGradient>
<clipPath id="{P}-clip"><rect x="82" y="82" width="860" height="860" rx="202"/></clipPath>
<filter id="{P}-amb" x="-50%" y="-50%" width="200%" height="200%" color-interpolation-filters="sRGB"><feGaussianBlur stdDeviation="56"/></filter>
<filter id="{P}-sh" x="-50%" y="-50%" width="200%" height="200%" color-interpolation-filters="sRGB"><feGaussianBlur stdDeviation="22"/></filter>
<filter id="{P}-hsoft" x="-50%" y="-50%" width="200%" height="200%" color-interpolation-filters="sRGB"><feGaussianBlur stdDeviation="2"/></filter>
<linearGradient id="{P}-obj" x1="0.1" y1="0.05" x2="0.9" y2="0.95"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#dfe7f2"/></linearGradient>
{mask("hl", 7, 8.4)}
{mask("lo", -7, -8.4)}
</defs>
<g id="plate"><rect x="82" y="82" width="860" height="860" rx="202" fill="url(#{P}-pl)"/><rect x="82" y="82" width="860" height="860" rx="202" fill="url(#{P}-plh)"/></g>
<g id="ambient-shadow" clip-path="url(#{P}-clip)"><ellipse cx="520" cy="700" rx="320" ry="170" fill="{DARK}" opacity="0.38" filter="url(#{P}-amb)"/></g>
<g id="object-shadow" clip-path="url(#{P}-clip)"><g opacity="0.32" filter="url(#{P}-sh)" transform="translate(12 26)"><g transform="{turn}" fill="{DARK}" stroke="{DARK}" stroke-width="1.5" stroke-linejoin="round">{knight}</g></g></g>
<g id="object-main">
<g transform="{turn}" fill="url(#{P}-obj)" stroke="{DARK}" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">{knight}</g>
<g transform="{turn}" fill="{DARK}"><path d="{EYE}"/></g>
<g filter="url(#{P}-hsoft)"><rect width="1024" height="1024" fill="#5a7a6c" opacity="0.25" mask="url(#{P}-lo)"/><rect width="1024" height="1024" fill="#fff" mask="url(#{P}-hl)"/></g>
</g>
<g id="plate-rim" clip-path="url(#{P}-clip)"><rect x="82" y="82" width="860" height="860" rx="202" fill="none" stroke="url(#{P}-rim)" stroke-width="8"/></g>
</svg>
'''
    with open(path, "w", encoding="utf-8") as out:
        out.write(svg)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "io.github.elomkdn.Gambit.svg")
