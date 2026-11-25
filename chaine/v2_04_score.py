"""
v2_04_score.py : score de la saison cible (v2_config.YEAR) par zone et par heure.

Principe : pour la saison cible, la marée et la lumière sont connues à l'avance ; le vent, la houle et la température de l'eau ne le sont pas. Pour chaque heure de la fenêtre, on rejoue donc la météo observée à la même heure, à ±3 jours de la même date, pendant toutes les années disponibles (environ 180 tirages), avec la marée et la lumière réelles de la saison. On en tire :
- l'indice : score moyen de la zone à cette heure (0 à 100) ;
- les chances : part des tirages où la zone se classe dans le meilleur cinquième.

Entrées : era5_YYYY_wind.nc, sst_YYYY.nc, ibi_wave_YYYY.nc (ou era5_YYYY_wave.nc à défaut), v2/zones.geojson, v2/zones_open.npy, v2/tide.json, v2/currents.npz
Sorties : v2/scores.npz, v2/hours.json
"""
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import v2_config as C
from v2_lib import cube, nearest_wet, open_nc, ramp, sector16, series_mean, solar_elevation, window_local


# ── Lecture de l'historique ─────────────────────────────────────────────────

def load_wind(year):
    p = C.ERA5_DIR / f"era5_{year}_wind.nc"
    if not p.exists():
        return None
    ds = open_nc(p)
    df = pd.DataFrame({"u": series_mean(ds["u10"]), "v": series_mean(ds["v10"])})
    ds.close()
    return df[~df.index.duplicated()].sort_index()


def load_sst(year):
    p = C.SST_DIR / f"sst_{year}.nc"
    if not p.exists():
        return None
    ds = open_nc(p)
    name = "analysed_sst" if "analysed_sst" in ds else list(ds.data_vars)[0]
    s = series_mean(ds[name])
    ds.close()
    s.index = s.index.normalize()
    s = s[~s.index.duplicated()].sort_index()
    return s - 273.15 if s.mean() > 100 else s


def wave_grid(zones):
    """Maille de houle IBI la plus proche de chaque zone. None si aucun fichier IBI."""
    files = sorted(C.IBI_WAVE_DIR.glob("ibi_wave_*.nc"))
    if not files:
        return None
    ds = open_nc(files[0])
    wet = np.isfinite(cube(ds, "VHM0")).mean(axis=0) > 0.9
    lons, lats = ds["longitude"].values, ds["latitude"].values
    ds.close()
    cells = [nearest_wet(lons, lats, wet, lo, la) for lo, la in zip(zones["lon"], zones["lat"])]
    uniq = sorted({(j, i) for j, i, _ in cells})
    zone_cell = np.array([uniq.index((j, i)) for j, i, _ in cells])
    return dict(uniq=uniq, zone_cell=zone_cell, dist=np.array([d for _, _, d in cells]), lons=lons, lats=lats)


def load_wave(year, grid):
    """(index temps, Hs[t, maille], direction[t, maille], période[t, maille] ou None)."""
    if grid is None: # repli ERA5 : un seul point pour toute la zone
        p = C.ERA5_DIR / f"era5_{year}_wave.nc"
        if not p.exists():
            return None
        ds = open_nc(p)
        hs, dr = series_mean(ds["swh"]), series_mean(ds["mwd"])
        tp = series_mean(ds["mwp"]) if "mwp" in ds else None
        ds.close()
        return hs.index, hs.values[:, None], dr.values[:, None], None if tp is None else tp.values[:, None]
    p = C.IBI_WAVE_DIR / f"ibi_wave_{year}.nc"
    if not p.exists():
        return None
    ds = open_nc(p)
    jj = [j for j, _ in grid["uniq"]]
    ii = [i for _, i in grid["uniq"]]
    t = pd.DatetimeIndex(ds["time"].values).round("s")
    hs = cube(ds, "VHM0")[:, jj, ii]
    dr = cube(ds, "VMDR")[:, jj, ii]
    tp = cube(ds, "VTPK")[:, jj, ii] if "VTPK" in ds else None
    ds.close()
    return t, hs, dr, tp


# ── Facteurs ────────────────────────────────────────────────────────────────

def light_factor(elev):
    L = C.LIGHT
    e = np.asarray(elev, dtype="float64")
    night_to_tw = L["night"] + (1 - L["night"]) * ramp(e, L["night_el"], L["tw_lo"])
    tw_to_day = 1 - (1 - L["day"]) * ramp(e, L["tw_hi"], L["day_el"])
    return np.where(e <= L["tw_lo"], night_to_tw, tw_to_day)


def sst_factor(t):
    S = C.SST
    t = np.asarray(t, dtype="float64")
    cold = S["cold_score"] + (1 - S["cold_score"]) * ramp(t, S["cold"], S["ok_lo"])
    warm = 1 - (1 - S["warm_score"]) * ramp(t, S["ok_hi"], S["warm"])
    return np.where(t < S["ok_lo"], cold, warm)


def open_toward(open_row, bearing):
    """Ouverture d'une zone dans la direction d'où vient le vent ou la houle (interpolation circulaire)."""
    n = open_row.shape[0]
    x = (np.asarray(bearing, dtype="float64") % 360) / (360.0 / n)
    i0 = np.floor(x).astype(int) % n
    f = x - np.floor(x)
    return open_row[i0] * (1 - f) + open_row[(i0 + 1) % n] * f


def sun_events(loc):
    """Lever et coucher du soleil par jour local, à la minute."""
    out = {}
    for day in pd.DatetimeIndex(loc.normalize().unique()):
        mins = pd.date_range(day, day + pd.Timedelta(hours=24), freq="1min", inclusive="left")
        el = solar_elevation(mins.tz_convert("UTC").tz_localize(None), *C.REF_POINT)
        up = np.where(el > -0.833)[0]
        if len(up):
            out[day.strftime("%Y-%m-%d")] = [mins[up[0]].strftime("%H:%M"), mins[up[-1]].strftime("%H:%M")]
    return out


# ── Calcul ──────────────────────────────────────────────────────────────────

JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]


def run():
    print(f"=== v2_04 : score {C.YEAR} ===")
    need = [C.V2 / "zones.geojson", C.V2 / "zones_open.npy", C.V2 / "tide.json", C.V2 / "currents.npz"]
    miss = [p.name for p in need if not p.exists()]
    if miss:
        print(f"  ERREUR : fichiers manquants {miss} (lancer v2_02 puis v2_03)")
        return False
    zones = gpd.read_file(C.V2 / "zones.geojson")
    zopen = np.load(C.V2 / "zones_open.npy")
    cur = np.load(C.V2 / "currents.npz")
    loc, utc = window_local(C)
    H, Z = len(utc), len(zones)

    grid = wave_grid(zones)
    src_wave = "IBI 1/36°" if grid is not None else "ERA5 (un seul point, pas de détail spatial)"
    print(f"  Houle : {src_wave}")
    n_cell = len(grid["uniq"]) if grid is not None else 1
    zone_cell = grid["zone_cell"] if grid is not None else np.zeros(Z, dtype=int)

    # Tirages : pour chaque année et chaque décalage de -P à +P jours
    cols_u, cols_v, cols_t, cols_hs, cols_dr, cols_tp, years_ok = [], [], [], [], [], [], []
    for y in C.HIST_YEARS:
        wind, sst, wave = load_wind(y), load_sst(y), load_wave(y, grid)
        if wind is None or wave is None:
            continue
        wt, hs, dr, tp = wave
        base = utc + pd.DateOffset(years=y - C.YEAR)
        used = False
        for d in range(-C.POOL_DAYS, C.POOL_DAYS + 1):
            cand = base + pd.Timedelta(days=d)
            iw = wind.index.get_indexer(cand)
            ih = wt.get_indexer(cand)
            ok = (iw >= 0) & (ih >= 0)
            if not ok.any():
                continue
            used = True
            u = np.where(ok, wind["u"].values[iw], np.nan)
            v = np.where(ok, wind["v"].values[iw], np.nan)
            if sst is not None and len(sst):
                it = sst.index.get_indexer(cand.normalize(), method="nearest")
                tt = np.where(ok, sst.values[it], np.nan)
            else:
                tt = np.where(ok, 18.0, np.nan)
            cols_u.append(u); cols_v.append(v); cols_t.append(tt)
            cols_hs.append(np.where(ok[:, None], hs[ih], np.nan))
            cols_dr.append(np.where(ok[:, None], dr[ih], np.nan))
            cols_tp.append(np.where(ok[:, None], tp[ih], np.nan) if tp is not None else np.full((H, n_cell), np.nan))
        if used:
            years_ok.append(y)
    if not years_ok:
        print("  ERREUR : aucune année avec vent et houle. Vérifier data/raw/era5 et data/raw/ibi_wave.")
        return False

    U, V, T = np.stack(cols_u, 1), np.stack(cols_v, 1), np.stack(cols_t, 1) # (H, K)
    HS, DR, TP = np.stack(cols_hs, 1), np.stack(cols_dr, 1), np.stack(cols_tp, 1) # (H, K, mailles)
    valid = np.isfinite(U) & np.isfinite(HS).all(axis=2)
    K = U.shape[1]
    n_valid = valid.sum(1)
    print(f"  Années utilisées : {years_ok[0]}-{years_ok[-1]} ({len(years_ok)} ans), {K} tirages possibles par heure")
    print(f"  Tirages valides par heure : min {n_valid.min()}, médiane {int(np.median(n_valid))}, max {n_valid.max()}")
    if n_valid.min() < 20:
        print("  ATTENTION : certaines heures ont moins de 20 tirages, leur score est moins fiable.")

    ws = np.hypot(U, V)
    wd = (np.degrees(np.arctan2(-U, -V)) + 360) % 360 # direction d'où vient le vent
    wind_force = ramp(ws, C.WIND["lo"], C.WIND["full"]) * (1 - ramp(ws, C.WIND["strong"], C.WIND["hi"]))
    f_eau = sst_factor(T)

    elev = solar_elevation(utc, *C.REF_POINT)
    f_light = light_factor(elev) # (H,)

    sp = cur["speed"] # (H, Z)
    p95_all = np.nanpercentile(sp, 95)
    p95_zone = np.nanpercentile(sp, 95, axis=0)
    f_cur = 0.5 * np.clip(sp / p95_all, 0, 1) + 0.5 * np.clip(sp / np.maximum(p95_zone, 1e-6), 0, 1)

    W = C.WEIGHTS
    score = np.full((H, K, Z), np.nan, dtype="float32")
    comp = np.zeros((H, Z, 4), dtype="float32")
    hs_loc_med = np.zeros((H, Z), dtype="float32")
    with np.errstate(invalid="ignore"):
        for z in range(Z):
            c = zone_cell[z]
            sub = C.SUBGRID + (1 - C.SUBGRID) * open_toward(zopen[z], DR[:, :, c])
            hs_loc = HS[:, :, c] * sub
            ressac = ramp(hs_loc, C.WAVE["lo"], C.WAVE["full"])
            clapot = open_toward(zopen[z], wd) * wind_force
            safe = 1 - 0.85 * ramp(hs_loc, C.WAVE["unsafe_lo"], C.WAVE["unsafe_hi"])
            agit_raw = (1 - (1 - ressac) * (1 - clapot)) * safe
            f_agit = C.AGIT_FLOOR + (1 - C.AGIT_FLOOR) * agit_raw
            f_lum = np.maximum(f_light[:, None], C.LIGHT["day"] + C.LIGHT["agit_rescue"] * agit_raw)
            f_c = np.repeat(f_cur[:, z][:, None], K, axis=1)
            s = np.exp(W["agitation"] * np.log(np.maximum(f_agit, C.FLOOR)) + W["courant"] * np.log(np.maximum(f_c, C.FLOOR)) + W["lumiere"] * np.log(np.maximum(f_lum, C.FLOOR)) + W["eau"] * np.log(np.maximum(f_eau, C.FLOOR)))
            s[~valid] = np.nan
            score[:, :, z] = s
            for n, f in enumerate((f_agit, f_c, f_lum, f_eau)):
                comp[:, z, n] = np.nanmean(np.where(valid, f, np.nan), axis=1)
            hs_loc_med[:, z] = np.nanmedian(np.where(valid, hs_loc, np.nan), axis=1)

    flat = score[np.isfinite(score)]
    rng = np.random.default_rng(0)
    thr = float(np.quantile(rng.choice(flat, size=min(len(flat), 2_000_000), replace=False), 1 - C.TOP_SHARE))
    with np.errstate(invalid="ignore"):
        S = np.nanmean(score, axis=1) # (H, Z)
        P = np.nansum(score >= thr, axis=1) / np.maximum(n_valid[:, None], 1)

    # Météo typique de chaque heure
    big = int(np.nanargmax(np.nanmean(HS, axis=(0, 1)))) # maille la plus exposée
    sectors = (np.floor(((wd + 22.5) % 360) / 45)).astype(float)
    sectors[~valid] = np.nan
    hours = []
    sun = sun_events(loc)
    for h in range(H):
        ok = valid[h]
        sec = sectors[h][ok].astype(int)
        counts = np.bincount(sec, minlength=8) if len(sec) else np.zeros(8)
        dom = int(counts.argmax())
        hours.append(dict(
            t=loc[h].strftime("%Y-%m-%dT%H:%M"),
            sun=round(float(elev[h]), 1),
            wind=round(float(np.nanmedian(ws[h][ok])), 1) if ok.any() else None,
            wind_dir=sector16(dom * 45),
            wind_share=round(float(counts[dom] / max(counts.sum(), 1)), 2),
            hs=round(float(np.nanmedian(HS[h][ok][:, big])), 2) if ok.any() else None,
            tp=None if not np.isfinite(TP[h][ok][:, big]).any() else round(float(np.nanmedian(TP[h][ok][:, big])), 1),
            sst=round(float(np.nanmedian(T[h][ok])), 1) if ok.any() else None,
            n=int(n_valid[h]),
        ))

    np.savez_compressed(C.V2 / "scores.npz", S=np.round(np.nan_to_num(S) * 100).astype("uint8"), P=np.round(np.nan_to_num(P) * 100).astype("uint8"), COMP=np.round(np.nan_to_num(comp) * 100).astype("uint8"), HSL=np.clip(np.round(np.nan_to_num(hs_loc_med) * 50), 0, 255).astype("uint8"))
    meta = dict(years=[int(years_ok[0]), int(years_ok[-1])], n_years=len(years_ok), pool_days=C.POOL_DAYS, wave_source=src_wave, threshold=round(thr, 3), top_share=C.TOP_SHARE, weights=C.WEIGHTS, samples_median=int(np.median(n_valid)))
    (C.V2 / "hours.json").write_text(json.dumps(dict(meta=meta, hours=hours, sun=sun)), encoding="utf-8")

    q = np.percentile(S * 100, [5, 25, 50, 75, 95])
    print(f"  Indice (0-100) : p5 {q[0]:.0f}, p25 {q[1]:.0f}, médiane {q[2]:.0f}, p75 {q[3]:.0f}, p95 {q[4]:.0f}")
    best = np.unravel_index(np.argsort(S, axis=None)[::-1][:5], S.shape)
    print("  Cinq meilleures zones-heures :")
    for h, z in zip(*best):
        print(f"    {JOURS[loc[h].dayofweek]} {loc[h]:%d/%m %Hh}  {zones['name'][z]:9s} face {zones['facing'][z]:10s} indice {S[h, z]*100:.0f}, chances {P[h, z]*100:.0f} %")
    by_hour = pd.Series(S.max(1) * 100).groupby(loc.hour).mean()
    print("  Indice moyen de la meilleure zone selon l'heure : "
          + ", ".join(f"{h:02d}h {v:.0f}" for h, v in by_hour.items() if h % 3 == 0))
    print(f"  -> {C.V2 / 'scores.npz'}")
    return True


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
