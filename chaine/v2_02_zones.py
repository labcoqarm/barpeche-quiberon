"""
v2_02_zones.py : zones de pêche et exposition.

Entrées : data/processed/candidate_zones.geojson (bande de mer au pied de la côte rocheuse, v2_00), data/processed/osm_cote.geojson (trait de côte OSM, v2_00)
Sorties : data/processed/v2/zones.geojson, data/processed/v2/zones_open.npy (ouverture par direction, Z x 72)

Les polygones en marches d'escalier sont fusionnés et arrondis. Pour l'exposition, un rayon part de chaque zone tous les 5° et mesure la distance d'eau libre jusqu'à la première côte (fetch). Une zone est exposée à un vent ou à une houle venant d'une direction si le rayon tiré dans cette direction va loin sans toucher terre.
"""
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, box
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).parent))
import v2_config as C
from v2_lib import sector8


def clean_zones(gdf):
    """Fusionne, arrondit, redécoupe les grandes zones. Travaille en Lambert-93."""
    g = gdf.to_crs(C.CRS_METRIC)
    geoms = [geom.buffer(0) for geom in g.geometry if geom is not None and not geom.is_empty]
    merged = unary_union(geoms).buffer(35, join_style="round").buffer(-35, join_style="round")
    parts = [p for p in getattr(merged, "geoms", [merged]) if p.area >= C.MIN_AREA_M2]

    out = []
    for p in parts:
        if p.area <= C.SPLIT_AREA_M2:
            out.append(p)
            continue
        x0, y0, x1, y1 = p.bounds
        s = C.SPLIT_GRID_M
        for gx in np.arange(np.floor(x0 / s) * s, x1, s):
            for gy in np.arange(np.floor(y0 / s) * s, y1, s):
                piece = p.intersection(box(gx, gy, gx + s, gy + s))
                for q in getattr(piece, "geoms", [piece]):
                    if q.geom_type == "Polygon" and q.area >= C.MIN_AREA_M2:
                        out.append(q)
    out = [q.simplify(6) for q in out]
    return gpd.GeoDataFrame(geometry=out, crs=C.CRS_METRIC)


def load_coast():
    if not C.COAST_SRC.exists():
        raise FileNotFoundError(f"{C.COAST_SRC} absent : lancer v2_00_socle.py d'abord")
    g = gpd.read_file(C.COAST_SRC).to_crs(C.CRS_METRIC)
    if "category" in g.columns:
        g = g[g["category"] == "coastline"]
    lines = [geom for geom in g.geometry if geom is not None and geom.geom_type in ("LineString", "MultiLineString")]
    # Les rochers isolés (contour fermé de moins de 300 m) ne coupent pas les rayons.
    lines = [ln for ln in lines if not (ln.length < 300 and ln.is_ring)]
    if not lines:
        raise RuntimeError(f"aucun trait de côte dans {C.COAST_SRC.name}")
    return lines


def grid_north_offset(x, y):
    """Angle (degrés) entre le nord vrai et le nord de la grille Lambert-93 au point (x, y)."""
    to_wgs = Transformer.from_crs(C.CRS_METRIC, C.CRS_WGS84, always_xy=True)
    to_l93 = Transformer.from_crs(C.CRS_WGS84, C.CRS_METRIC, always_xy=True)
    lon, lat = to_wgs.transform(x, y)
    x2, y2 = to_l93.transform(lon, lat + 0.01)
    return float(np.degrees(np.arctan2(x2 - x, y2 - y))) # cap grille du nord vrai


def openness(zones, coast_lines):
    """Ouverture (0 à 1) de chaque zone dans chaque direction vraie, tous les 5°."""
    tree = shapely.STRtree(coast_lines)
    to_l93 = Transformer.from_crs(C.CRS_WGS84, C.CRS_METRIC, always_xy=True)
    bx0, by0 = to_l93.transform(C.BBOX["xmin"], C.BBOX["ymin"])
    bx1, by1 = to_l93.transform(C.BBOX["xmax"], C.BBOX["ymax"])
    cap = C.FETCH_CAP_KM * 1000.0
    ray_len = C.RAY_KM * 1000.0
    bearings = np.arange(C.N_DIRS) * (360.0 / C.N_DIRS)

    coast_all = unary_union(coast_lines)
    raw = np.ones((len(zones), C.N_DIRS))
    for zi, geom in enumerate(zones.geometry):
        # Origine : le point de la zone le plus au large, pour qu'un pixel à cheval sur le trait de côte ne fasse pas passer la zone pour abritée.
        cands = [geom.representative_point()] + [shapely.Point(c) for c in geom.simplify(25).exterior.coords]
        o = max(cands, key=lambda p: p.distance(coast_all))
        off = grid_north_offset(o.x, o.y)
        for di, b in enumerate(bearings):
            a = np.radians(b + off)
            end = (o.x + ray_len * np.sin(a), o.y + ray_len * np.cos(a))
            ray = LineString([(o.x, o.y), end])
            dist = ray_len
            for idx in tree.query(ray):
                inter = ray.intersection(coast_lines[idx])
                if not inter.is_empty:
                    dist = min(dist, o.distance(inter))
            raw[zi, di] = min(dist, cap) / cap
    # Lissage angulaire (fenêtre triangulaire de ±35°) : vent et houle ne viennent jamais d'un seul cap.
    half = int(round(35 / (360.0 / C.N_DIRS)))
    w = np.array([half + 1 - abs(k) for k in range(-half, half + 1)], dtype=float)
    w /= w.sum()
    smooth = np.zeros_like(raw)
    for k, wk in zip(range(-half, half + 1), w):
        smooth += wk * np.roll(raw, -k, axis=1)
    return raw, smooth, bearings


def run():
    print("=== v2_02 : zones et exposition ===")
    if not C.ZONES_SRC.exists():
        print(f"  ERREUR : {C.ZONES_SRC} absent (lancer v2_00_socle.py)")
        return False
    depart = gpd.read_file(C.ZONES_SRC)
    zones = clean_zones(depart)
    print(f"  Zones de départ : {len(depart)} polygones -> zones : {len(zones)}")
    if len(zones) == 0:
        print("  ERREUR : aucune zone après nettoyage")
        return False

    coast = load_coast()
    print(f"  Trait de côte : {len(coast)} tronçons")
    raw, smooth, bearings = openness(zones, coast)

    # Orientation : moyenne circulaire des directions ouvertes
    rad = np.radians(bearings)
    facing = (np.degrees(np.arctan2((raw * np.sin(rad)).sum(1), (raw * np.cos(rad)).sum(1))) + 360) % 360
    open_mean = raw.mean(1)
    expo = np.where(open_mean >= 0.45, "exposée", np.where(open_mean >= 0.25, "intermédiaire", "abritée"))

    # Numérotation dans le sens des aiguilles d'une montre autour de la presqu'île, depuis le nord-ouest
    cx, cy = unary_union(list(zones.geometry)).centroid.coords[0]
    pts = zones.geometry.representative_point()
    ang = (np.degrees(np.arctan2(pts.x.values - cx, pts.y.values - cy)) - 315) % 360
    order = np.argsort(ang)
    zones = zones.iloc[order].reset_index(drop=True)
    raw, smooth, facing, open_mean, expo = raw[order], smooth[order], facing[order], open_mean[order], expo[order]

    zones["area_m2"] = zones.geometry.area.round(0)
    zw = zones.to_crs(C.CRS_WGS84)
    rp = zw.geometry.representative_point()
    zw["id"] = np.arange(len(zw))
    zw["name"] = [f"Zone {i + 1}" for i in range(len(zw))]
    zw["facing_deg"] = facing.round(0)
    zw["facing"] = [sector8(f) for f in facing]
    zw["exposure"] = expo
    zw["open_mean"] = open_mean.round(3)
    zw["lon"] = rp.x.values.round(5)
    zw["lat"] = rp.y.values.round(5)

    zw.to_file(C.V2 / "zones.geojson", driver="GeoJSON")
    np.save(C.V2 / "zones_open.npy", smooth.astype("float32"))
    np.save(C.V2 / "zones_open_raw.npy", raw.astype("float32"))

    for e in ("exposée", "intermédiaire", "abritée"):
        sel = zw[zw["exposure"] == e]
        faces = ", ".join(f"{k} ({v})" for k, v in sel["facing"].value_counts().items())
        print(f"  {e:14s} : {len(sel):3d} zones   {faces}")
    print(f"  -> {C.V2 / 'zones.geojson'}")
    return True


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
