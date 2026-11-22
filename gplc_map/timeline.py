"""All timing (frames @30fps) and camera keys in one place, for easy retiming."""

T = {
    "end": 780,              # 26 s total
    "map_end": 640,          # map layer is fully covered by the white wipe after this

    # (frame, camera location, look-at target) - smooth bezier between keys
    "camera": [
        (1,   (-1.0, -1.0, 92.0),  (-0.5, 5.0, 0.0)),    # night, high above Arabia
        (80,  (-1.0, -6.0, 64.0),  (-0.6, 4.0, 0.0)),
        (165, (-2.2, -17.0, 32.0), (-0.8, 2.0, 0.0)),    # Saudi framed
        (275, (0.8, -16.5, 28.5),  (0.0, 2.4, 0.0)),     # slow lateral drift
        (410, (4.0, -22.0, 78.0),  (4.0, 9.0, 0.0)),     # wide: Europe - Africa - Asia
        (445, (3.5, -26.0, 56.0),  (2.5, 3.0, 0.0)),
        (505, (6.5, -14.8, 4.2),   (1.6, -8.6, 0.0)),    # low, beside the ship in the Gulf of Aden
        (640, (1.6, -14.2, 3.6),   (-2.8, -6.2, 0.0)),
    ],

    "night": [(1, 1.0), (70, 1.0), (150, 0.0)],
    "sun_energy": [(1, 0.4), (70, 0.4), (150, 3.2)],

    # line draw-on: (frame, reveal distance in BU)
    "reveal_border": [(115, 0.0), (205, 34.5)],
    "reveal_saudi_net": [(170, 0.0), (270, 16.5)],
    "opacity_saudi_net": [(1, 1.0), (300, 1.0), (400, 0.7)],
    "reveal_global": [(290, 0.0), (420, 50.0), (520, 77.0)],
    "opacity_global": [(1, 1.0)],
    "reveal_sea": [(280, 0.0), (430, 80.0), (560, 147.0)],

    "ship_scale": 1.0,
    "ship_show": 420,
    "ship_offset": [(420, 0.0), (640, 0.5)],

    # UI
    "grid_opacity": [(1, 0.0), (25, 0.9), (150, 0.55), (560, 0.55), (590, 0.0)],
    "toplogo_opacity": [(20, 0.0), (45, 1.0), (548, 1.0), (566, 0.0)],
    # (line 1, line 2, in, out)
    "titles": [
        ("COORDINATING", "TRADE", 175, 268),
        ("CONNECTING", "MARKETS", 300, 418),
        ("CREATING", "GROWTH", 455, 540),
    ],
    "bar": (170, 548),
    "bar_fill": [(170, 0.0), (270, 0.33), (420, 0.66), (545, 1.0)],
    "wipe": (550, 600),
    "tagline": (604, 626, 676),
    "endcard": 690,
    "audio": None,
}
