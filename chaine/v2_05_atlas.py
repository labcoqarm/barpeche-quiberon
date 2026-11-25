"""
v2_05_atlas.py : assemble l'atlas en une seule page HTML.

Entrées : v2/zones.geojson, v2/scores.npz, v2/hours.json, v2/tide.json, v2/currents.npz
Sorties : data/output/atlas/atlas_ANNEE.html (à ouvrir dans le navigateur), data/processed/v2/scores_ANNEE.csv (zone, heure, indice, chances), data/processed/v2/atlas_ANNEE.gpkg (avec --gpkg : une entité par zone et par heure, pour le contrôleur temporel de QGIS)
"""
import base64
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import v2_config as C


def _b64(a):
    return base64.b64encode(np.ascontiguousarray(a, dtype="uint8").tobytes()).decode("ascii")


def _round_coords(obj, nd=5):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(float(v), nd) for v in obj]
        return [_round_coords(o, nd) for o in obj]
    return obj


def run(demo=False, gpkg=False):
    print("=== v2_05 : atlas ===")
    need = ["zones.geojson", "scores.npz", "hours.json", "tide.json", "currents.npz"]
    miss = [n for n in need if not (C.V2 / n).exists()]
    if miss:
        print(f"  ERREUR : fichiers manquants {miss}")
        return False
    zones = gpd.read_file(C.V2 / "zones.geojson")
    sc = np.load(C.V2 / "scores.npz")
    hours = json.loads((C.V2 / "hours.json").read_text(encoding="utf-8"))
    tide = json.loads((C.V2 / "tide.json").read_text(encoding="utf-8"))
    cur = np.load(C.V2 / "currents.npz")
    S, P = sc["S"], sc["P"]
    H, Z = S.shape
    if Z != len(zones) or H != len(hours["hours"]):
        print("  ERREUR : zones et scores ne correspondent plus. Relancer v2_03 puis v2_04.")
        return False

    feats = []
    keep = ["id", "name", "facing", "facing_deg", "exposure", "area_m2", "lon", "lat"]
    for _, r in zones.iterrows():
        g = r.geometry.__geo_interface__
        feats.append(dict(type="Feature", properties={k: (r[k].item() if hasattr(r[k], "item") else r[k]) for k in keep}, geometry=dict(type=g["type"], coordinates=_round_coords(g["coordinates"]))))

    meta = dict(hours["meta"])
    meta.update(year=C.YEAR, demo=bool(demo), s_lo=int(np.percentile(S, 2)), s_hi=int(max(np.percentile(S, 98), np.percentile(S, 2) + 5)), p_hi=int(np.percentile(P, 98)), M2=tide["meta"]["M2"], S2=tide["meta"]["S2"], current_proxy=bool(tide["meta"]["current_proxy"]))
    payload = dict(
        meta=meta, hours=hours["hours"], sun=hours["sun"],
        tide=dict(eta=tide["hourly"]["eta"], rate=tide["hourly"]["rate"], coeff=tide["hourly"]["coeff"], h_from_pm=tide["hourly"]["h_from_pm"], events=tide["events"]),
        zones=dict(type="FeatureCollection", features=feats),
        S=_b64(S), P=_b64(P), COMP=_b64(sc["COMP"]), HSL=_b64(sc["HSL"]),
        CUR=_b64(np.clip(np.round(np.nan_to_num(cur["speed"]) * 100), 0, 255)),
    )
    tpl = (Path(__file__).parent / "v2_atlas_template.html").read_text(encoding="utf-8")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = tpl.replace("__YEAR__", str(C.YEAR)).replace("__DATA__", data)
    out = C.ATLAS_DIR / ("atlas_demo.html" if demo else f"atlas_{C.YEAR}.html")
    out.write_text(html, encoding="utf-8")
    print(f"  Page : {out}  ({out.stat().st_size/1e6:.1f} Mo, {Z} zones, {H} heures)")

    # Table longue pour SIG et tableur
    t = [h["t"] for h in hours["hours"]]
    long = pd.DataFrame({
        "zone_id": np.tile(np.arange(Z), H),
        "heure_locale": np.repeat(t, Z),
        "indice": S.reshape(-1), "chances": P.reshape(-1),
        "agitation": sc["COMP"][:, :, 0].reshape(-1), "courant": sc["COMP"][:, :, 1].reshape(-1),
        "lumiere": sc["COMP"][:, :, 2].reshape(-1), "eau": sc["COMP"][:, :, 3].reshape(-1),
    })
    if not demo:
        long.to_csv(C.V2 / f"scores_{C.YEAR}.csv", index=False)
        print(f"  Table : {C.V2 / f'scores_{C.YEAR}.csv'}  ({len(long)} lignes ; jointure sur zones.geojson par id = zone_id)")
    if gpkg and not demo:
        g = zones[["id", "name", "facing", "exposure", "geometry"]].merge(long, left_on="id", right_on="zone_id")
        g["debut"] = pd.to_datetime(g["heure_locale"])
        g["fin"] = g["debut"] + pd.Timedelta(hours=1)
        g = gpd.GeoDataFrame(g.drop(columns=["zone_id"]), geometry="geometry", crs=zones.crs)
        gp = C.V2 / f"atlas_{C.YEAR}.gpkg"
        g.to_file(gp, layer="zones_heures", driver="GPKG")
        print(f"  GeoPackage : {gp}  (QGIS : Propriétés > Temporel > champs debut et fin)")
    return True


if __name__ == "__main__":
    sys.exit(0 if run(demo="--demo" in sys.argv, gpkg="--gpkg" in sys.argv) else 1)
