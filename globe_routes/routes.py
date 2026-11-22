"""Cities, route waypoints and timing (frames @ 24 fps).

A waypoint is a city name (gets a node dot) or a (lon, lat) tuple (a shaping point,
kept on water for sea lanes). Each route: (name, kind, start, end, waypoints);
kind "land" = corridor, "sea" = shipping lane (slightly finer line).
"""

CITIES = {
    "Riyadh": (46.72, 24.71), "Jeddah": (39.17, 21.54), "Dammam": (50.10, 26.43),
    "NEOM": (35.20, 27.95), "Tabuk": (36.57, 28.38), "Hail": (41.69, 27.52),
    "Buraydah": (43.97, 26.33), "Abha": (42.50, 18.22), "Jizan": (42.55, 16.89),
    "Kuwait": (47.98, 29.37), "Port Said": (32.30, 31.26), "Suez": (32.55, 29.97),
    "Muscat": (58.60, 23.66), "Mumbai": (72.85, 18.95), "Djibouti": (43.15, 11.60),
    "Mombasa": (39.70, -4.06), "Dar es Salaam": (39.30, -6.80), "Durban": (31.10, -29.90),
    "Cape Town": (18.40, -33.92), "Walvis Bay": (14.45, -22.95), "Lobito": (13.50, -12.35),
    "Luanda": (13.20, -8.82), "Lagos": (3.38, 6.42), "Abidjan": (-4.02, 5.28),
    "Dakar": (-17.48, 14.69), "Casablanca": (-7.62, 33.60), "Alexandria": (29.90, 31.22),
    "Cairo": (31.24, 30.04), "Khartoum": (32.53, 15.50), "Addis Ababa": (38.75, 9.00),
    "Nairobi": (36.82, -1.29), "Kampala": (32.58, 0.35), "Kinshasa": (15.30, -4.32),
    "Lusaka": (28.28, -15.40), "Johannesburg": (28.05, -26.20), "Bamako": (-8.00, 12.65),
    "Niamey": (2.11, 13.51), "Kano": (8.52, 12.00), "N'Djamena": (15.05, 12.11),
    "Colombo": (79.84, 6.93), "Singapore": (103.82, 1.26), "Jakarta": (106.85, -6.10),
    "Perth": (115.75, -32.05), "Darwin": (130.84, -12.46), "Alice Springs": (133.88, -23.70),
    "Adelaide": (138.60, -34.93), "Melbourne": (144.96, -37.81), "Sydney": (151.21, -33.87),
    "Shanghai": (121.80, 31.20), "Delhi": (77.21, 28.61), "Kolkata": (88.36, 22.57),
    "Kalgoorlie": (121.47, -30.75), "Jaipur": (75.79, 26.91),
}

# Ringed hubs (a clean static ring around the dot).
HUBS = {"Riyadh", "Jeddah", "Dammam", "Mumbai", "Singapore", "Cape Town"}

ROUTES = [
    # --- Saudi Arabia (close-up) ---
    ("riyadh_dammam", "land", 78, 104, ["Riyadh", (48.3, 25.45), "Dammam"]),
    ("riyadh_jeddah", "land", 80, 116, ["Riyadh", (44.0, 23.55), (41.6, 22.35), "Jeddah"]),
    ("riyadh_neom", "land", 90, 138, ["Riyadh", "Buraydah", "Hail", "Tabuk", "NEOM"]),
    ("riyadh_jizan", "land", 96, 130, ["Riyadh", (44.4, 21.0), "Abha", "Jizan"]),
    ("dammam_kuwait", "land", 108, 132, ["Dammam", (48.8, 27.7), "Kuwait"]),
    # --- Region: Red Sea, Gulf, Arabian Sea ---
    ("red_sea_north", "sea", 148, 200, ["Jeddah", (38.3, 23.5), (36.7, 25.8), (35.0, 27.3),
                                         (33.9, 27.9), (33.0, 29.0), "Suez", (32.36, 30.6), "Port Said"]),
    ("red_sea_south", "sea", 150, 186, ["Jeddah", (40.3, 19.2), (41.6, 16.3), (42.8, 13.8),
                                         (43.4, 12.6), "Djibouti"]),
    ("gulf_hormuz", "sea", 156, 196, ["Dammam", (50.7, 27.0), (52.5, 26.6), (54.5, 26.3),
                                       (56.4, 26.6), (57.2, 25.3), (58.1, 24.3), "Muscat"]),
    ("muscat_mumbai", "sea", 190, 228, ["Muscat", (60.5, 22.6), (66.0, 21.0), (70.5, 19.4), "Mumbai"]),
    ("aden_mumbai", "sea", 182, 238, ["Djibouti", (45.5, 12.3), (51.5, 12.6), (60.0, 14.6),
                                       (68.0, 17.4), "Mumbai"]),
    # --- Africa ---
    ("horn_mombasa", "sea", 222, 262, ["Djibouti", (46.0, 12.0), (51.8, 12.0), (51.0, 7.5),
                                        (48.6, 4.0), (46.2, 1.4), (42.8, -1.9), "Mombasa"]),
    ("med_lane", "sea", 228, 290, ["Port Said", "Alexandria", (25.0, 33.0), (18.0, 34.0),
                                    (11.8, 37.0), (5.0, 37.8), (-1.0, 36.3), (-5.6, 35.95),
                                    (-7.0, 35.0), "Casablanca"]),
    ("nile", "land", 236, 284, ["Alexandria", "Cairo", (32.9, 24.1), "Khartoum", (36.4, 12.6),
                                 "Addis Ababa", (41.8, 9.6), "Djibouti"]),
    ("east_coast", "sea", 252, 312, ["Mombasa", "Dar es Salaam", (40.6, -11.0), (41.6, -15.5),
                                      (38.2, -20.5), (36.3, -24.5), (33.5, -28.5), "Durban",
                                      (29.0, -33.6), (25.6, -34.5), (20.0, -35.3), "Cape Town"]),
    ("kenya_congo", "land", 254, 300, ["Mombasa", "Nairobi", "Kampala", (25.2, 0.5), "Kinshasa",
                                        (14.0, -6.5), "Luanda"]),
    ("tazara_lobito", "land", 262, 306, ["Dar es Salaam", (35.7, -9.0), (31.4, -11.4), "Lusaka",
                                          (25.5, -11.2), (18.5, -12.0), "Lobito"]),
    ("west_coast", "sea", 268, 334, ["Cape Town", (16.3, -30.0), "Walvis Bay", (11.2, -17.0),
                                      "Lobito", "Luanda", (11.0, -4.5), (8.6, 0.0), (6.5, 3.5),
                                      "Lagos", (0.0, 5.0), "Abidjan", (-8.0, 4.0), (-14.0, 7.8),
                                      (-17.3, 11.8), "Dakar"]),
    ("sahel", "land", 270, 322, ["Dakar", "Bamako", "Niamey", "Kano", "N'Djamena", "Khartoum"]),
    ("kano_lagos", "land", 286, 306, ["Kano", (6.0, 9.0), "Lagos"]),
    ("south_rail", "land", 284, 320, ["Durban", "Johannesburg", (28.6, -20.15), "Lusaka"]),
    # --- India, South-East Asia, Australia ---
    ("india_north", "land", 322, 362, ["Mumbai", "Jaipur", "Delhi", (82.0, 25.4), "Kolkata"]),
    ("mumbai_colombo", "sea", 318, 346, ["Mumbai", (72.5, 15.0), (74.6, 10.0), (77.6, 7.2), "Colombo"]),
    ("colombo_singapore", "sea", 344, 380, ["Colombo", (82.0, 6.0), (90.0, 5.8), (95.5, 6.4),
                                             (99.4, 4.4), (100.8, 2.8), (102.6, 1.6), "Singapore"]),
    ("singapore_jakarta", "sea", 378, 398, ["Singapore", (104.9, 0.2), (106.0, -1.0), (107.0, -2.6),
                                             (106.9, -4.6), "Jakarta"]),
    ("jakarta_perth", "sea", 394, 432, ["Jakarta", (105.8, -6.0), (104.8, -7.3), (108.0, -15.0),
                                         (113.0, -27.0), "Perth"]),
    ("singapore_darwin", "sea", 384, 430, ["Singapore", (106.5, -0.5), (110.0, -4.5), (115.0, -6.4),
                                            (120.0, -7.5), (124.0, -6.8), (128.0, -9.3),
                                            (130.2, -11.5), "Darwin"]),
    ("singapore_shanghai", "sea", 386, 432, ["Singapore", (105.5, 4.5), (109.5, 10.5), (111.0, 15.0),
                                              (115.0, 21.5), (119.5, 24.5), (122.0, 28.5), "Shanghai"]),
    ("darwin_sydney", "land", 428, 462, ["Darwin", "Alice Springs", "Adelaide", "Melbourne", "Sydney"]),
    ("perth_adelaide", "land", 438, 466, ["Perth", "Kalgoorlie", (131.0, -31.4), (137.8, -32.5),
                                           "Adelaide"]),
]

# Camera keys: (frame, lon, lat, height above surface [globe radii], tilt deg, heading deg).
CAMERA = [
    (1,   30.0, 16.0, 3.30, 0.0, -14.0),   # space: Africa + Arabia, globe turning
    (36,  38.0, 20.0, 2.20, 6.0, -8.0),
    (72,  45.4, 22.4, 0.44, 30.0, 0.0),    # fast dive onto Riyadh
    (140, 44.2, 23.4, 0.50, 36.0, 9.0),    # drift while the Saudi network draws
    (200, 45.0, 18.0, 1.05, 30.0, 14.0),   # pull back: Red Sea, Gulf, Arabian Sea
    (238, 38.0, 10.0, 1.40, 20.0, 4.0),
    (298, 22.0, 3.0, 1.95, 8.0, -6.0),     # Africa, whole continent in frame
    (334, 20.0, -2.0, 2.05, 6.0, -10.0),
    (392, 100.0, 2.0, 1.85, 10.0, 6.0),    # swing east: Indian Ocean -> Asia / Australia
    (430, 114.0, -8.0, 1.80, 12.0, 10.0),
    (480, 70.0, 6.0, 2.55, 4.0, 0.0),      # pull out: the whole network
]

FRAMES = 480
FPS = 24
