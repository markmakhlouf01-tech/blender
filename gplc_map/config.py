"""Shared configuration for the GPLC 'On the map' Blender recreation."""
import math

# Geographic extent of the relief map (degrees).
LON0, LON1 = -25.0, 115.0
LAT0, LAT1 = -42.0, 66.0
DEG_PER_PX = 0.025          # heightmap resolution

# Map projection into Blender units: 1 BU per degree latitude,
# longitudes compressed by cos(22deg) so Arabia keeps natural proportions.
LON_C, LAT_C = 45.0, 22.0
X_SCALE = math.cos(math.radians(22.0))


def project(lon, lat):
    """Lon/lat (deg) -> Blender XY on the map plane."""
    return ((lon - LON_C) * X_SCALE, (lat - LAT_C))


# Video
FPS = 30
RES_X, RES_Y = 1080, 1920
