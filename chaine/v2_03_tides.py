"""
v2_03_tides.py : marée et courants de marée de la saison cible par analyse harmonique.

Entrées : data/raw/ibi_phy/ibi_phy_ssh.nc (niveau de la mer IBI, 12 mois), data/raw/ibi_phy/ibi_phy_cur.nc (courants de surface IBI, 12 mois, facultatif), data/processed/v2/zones.geojson
Sorties : data/processed/v2/tide.json (heures et hauteurs des PM/BM, série horaire), data/processed/v2/currents.npz (vitesse du courant par zone et par heure)

Méthode : la série du modèle est décomposée en ondes de marée (M2, S2, N2, K1...) avec utide, corrections nodales comprises, puis recomposée aux dates de la saison cible. La marée est astronomique, donc prévisible ; la surcote météo ne l'est pas et n'est pas incluse. Hauteurs données par rapport au niveau moyen, pas au zéro des cartes.
"""
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import utide
from scipy.signal import find_peaks

sys.path.insert(0, str(Path(__file__).parent))
import v2_config as C
from v2_lib import cube, nearest_wet, open_nc, window_local

CONSTIT = ["M2", "S2", "N2", "K2", "K1", "O1", "P1", "Q1", "2N2", "MU2", "NU2", "L2", "M4", "MS4", "MN4", "M6", "2MS6", "M3"]


def _times(ds):
    """Horodatage UTC de la série ; signale la convention des moyennes horaires."""
    t = pd.DatetimeIndex(ds["time"].values).round("s")
    step_min = float(np.median(np.diff(t.values).astype("timedelta64[s]").astype(float)) / 60.0)
    if step_min > 45:
        minutes = set(t.minute[:48])
        if minutes == {30}:
            print("  Série horaire moyenne, horodatée au milieu de l'heure (correct).")
        else:
            print("  ATTENTION : série horaire moyenne horodatée à l'heure ronde. Si les heures de")
            print("  pleine mer affichées plus bas sont décalées d'environ 30 min par rapport au SHOM,")
            print("  le produit est horodaté en début d'heure : me le signaler.")
    return t, step_min


def _solve(t, u, v=None, lat=47.5):
    span_days = (t[-1] - t[0]) / pd.Timedelta(days=1)
    constit = CONSTIT if span_days >= 200 else "auto"
    kw = dict(lat=lat, nodal=True, trend=False, method="ols", conf_int="none", constit=constit, verbose=False)
    good = np.isfinite(u) if v is None else (np.isfinite(u) & np.isfinite(v))
    tt = t.values[good]
    if v is None:
        return utide.solve(tt, u[good], **kw)
    return utide.solve(tt, u[good], v[good], **kw)


def tide_elevation(loc, utc):
    path = C.IBI_PHY_DIR / "ibi_phy_ssh.nc"
    if not path.exists():
        raise FileNotFoundError(f"{path} absent : lancer v2_01_download.py")
    ds = open_nc(path)
    t, step = _times(ds)
    zos = cube(ds, "zos")
    wet = np.isfinite(zos).mean(axis=0) > 0.9
    lons, lats = ds["longitude"].values, ds["latitude"].values
    j, i, dkm = nearest_wet(lons, lats, wet, *C.REF_POINT)
    h = zos[:, j, i].astype("float64")
    print(f"  Série : {t[0]:%d/%m/%Y} -> {t[-1]:%d/%m/%Y}, pas de {step:.0f} min, {len(t)} valeurs")
    print(f"  Maille de référence : {lons[i]:.3f}°, {lats[j]:.3f}° (à {dkm:.1f} km du point visé)")

    coef = _solve(t, h - np.nanmean(h), lat=float(lats[j]))
    amp = {str(n): float(a) for n, a in zip(coef.name, coef.A)}
    pha = {str(n): float(g) for n, g in zip(coef.name, coef.g)}
    m2, s2 = amp.get("M2", np.nan), amp.get("S2", np.nan)
    fit = utide.reconstruct(t.values, coef, verbose=False).h
    resid = (h - np.nanmean(h)) - fit
    print(f"  M2 = {m2:.2f} m, S2 = {s2:.2f} m ; écart-type du résidu = {np.nanstd(resid)*100:.0f} cm")

    # Recomposition toutes les 5 minutes, un jour de marge de chaque côté
    fine = pd.date_range(utc[0] - pd.Timedelta(days=1), utc[-1] + pd.Timedelta(days=1), freq="5min")
    eta = utide.reconstruct(fine.values, coef, verbose=False).h
    rate = np.gradient(eta, 5 / 60.0) # m par heure

    hi, _ = find_peaks(eta, distance=48) # au moins 4 h entre deux PM
    lo, _ = find_peaks(-eta, distance=48)
    ev = sorted([(k, "PM") for k in hi] + [(k, "BM") for k in lo])

    # Coefficient estimé : 95 en vive-eau moyenne (demi-marnage M2+S2), 45 en morte-eau (M2-S2)
    events = []
    for n, (k, kind) in enumerate(ev):
        neigh = [eta[ev[m][0]] for m in (n - 1, n + 1) if 0 <= m < len(ev) and ev[m][1] != kind]
        semi = abs(eta[k] - np.mean(neigh)) / 2.0 if neigh else np.nan
        coeff = 45 + 50 * (semi - (m2 - s2)) / (2 * s2) if np.isfinite(semi) else np.nan
        events.append(dict(utc=fine[k], kind=kind, h=float(eta[k]), coeff=float(np.clip(coeff, 20, 120)) if np.isfinite(coeff) else None))
    ev_df = pd.DataFrame(events)

    # Table horaire sur la fenêtre
    pos = fine.get_indexer(utc)
    pm = ev_df[ev_df["kind"] == "PM"].reset_index(drop=True)
    pm_t = pm["utc"].values.astype("datetime64[s]").astype("int64")
    hour_t = utc.values.astype("datetime64[s]").astype("int64")
    near = np.abs(hour_t[:, None] - pm_t[None, :]).argmin(axis=1)
    hourly = pd.DataFrame({
        "local": loc.strftime("%Y-%m-%dT%H:%M"),
        "eta": eta[pos].round(3),
        "rate": rate[pos].round(3),
        "coeff": pm["coeff"].values[near].round(0),
        "h_from_pm": ((hour_t - pm_t[near]) / 3600.0).round(2),
    })

    ev_df["local"] = (pd.DatetimeIndex(ev_df["utc"]).tz_localize("UTC").tz_convert(C.TZ) .strftime("%Y-%m-%dT%H:%M"))
    in_win = (ev_df["utc"] >= utc[0] - pd.Timedelta(hours=8)) & (ev_df["utc"] <= utc[-1] + pd.Timedelta(hours=8))
    ev_out = ev_df[in_win]

    print("\n  Contrôle à faire une fois : comparer ces heures avec maree.info (Port Haliguen)")
    for _, r in ev_out.head(8).iterrows():
        c = f"coeff ~{r['coeff']:.0f}" if r["kind"] == "PM" and r["coeff"] is not None else ""
        print(f"    {r['local'].replace('T', ' ')}  {r['kind']}  {r['h']:+.2f} m  {c}")

    meta = dict(ref_lon=float(lons[i]), ref_lat=float(lats[j]), M2=m2, S2=s2, constituents={k: dict(A=round(amp[k], 4), g=round(pha[k], 2)) for k in amp}, resid_std_cm=float(np.nanstd(resid) * 100), series_start=str(t[0]), series_end=str(t[-1]), step_min=step)
    return hourly, ev_out, meta, float(np.nanpercentile(np.abs(rate), 95))


def tidal_currents(utc, zones):
    path = C.IBI_PHY_DIR / "ibi_phy_cur.nc"
    if not path.exists():
        return None
    ds = open_nc(path)
    t, _ = _times(ds)
    uo, vo = cube(ds, "uo"), cube(ds, "vo")
    wet = (np.isfinite(uo).mean(axis=0) > 0.9) & (np.isfinite(vo).mean(axis=0) > 0.9)
    lons, lats = ds["longitude"].values, ds["latitude"].values
    cells, dist = [], []
    for lon, lat in zip(zones["lon"], zones["lat"]):
        j, i, d = nearest_wet(lons, lats, wet, lon, lat)
        cells.append((j, i))
        dist.append(d)
    uniq = sorted(set(cells))
    print(f"\n  Courants : {len(uniq)} mailles du modèle pour {len(zones)} zones (distance médiane zone-maille {np.median(dist):.1f} km)")
    speed, direc = {}, {}
    for n, (j, i) in enumerate(uniq):
        coef = _solve(t, uo[:, j, i].astype("float64"), vo[:, j, i].astype("float64"), lat=float(lats[j]))
        rec = utide.reconstruct(utc.values, coef, verbose=False)
        speed[(j, i)] = np.hypot(rec.u, rec.v)
        direc[(j, i)] = (np.degrees(np.arctan2(rec.u, rec.v)) + 360) % 360 # cap vers lequel porte le courant
        print(f"    maille {n + 1}/{len(uniq)} : courant de marée max {speed[(j, i)].max():.2f} m/s")
    sp = np.stack([speed[c] for c in cells], axis=1) # (heures, zones)
    di = np.stack([direc[c] for c in cells], axis=1)
    return sp, di, np.array(dist)


def run():
    print(f"=== v2_03 : marée et courants {C.YEAR} ===")
    zpath = C.V2 / "zones.geojson"
    if not zpath.exists():
        print("  ERREUR : lancer v2_02_zones.py d'abord")
        return False
    zones = gpd.read_file(zpath)
    loc, utc = window_local(C)
    hourly, events, meta, rate95 = tide_elevation(loc, utc)

    cur = tidal_currents(utc, zones)
    if cur is None:
        print("\n  Pas de fichier de courants : vitesse de variation du niveau utilisée à la place.")
        sp = np.repeat(np.abs(hourly["rate"].values)[:, None], len(zones), axis=1)
        di = np.full_like(sp, np.nan)
        proxy, dist = True, np.full(len(zones), np.nan)
    else:
        sp, di, dist = cur
        proxy = False
    np.savez_compressed(C.V2 / "currents.npz", speed=sp.astype("float32"), direction=di.astype("float32"), proxy=proxy, cell_km=dist)

    meta["current_proxy"] = proxy
    out = dict(meta=meta, hourly={k: [None if (isinstance(x, float) and np.isnan(x)) else x for x in hourly[k].tolist()] for k in hourly.columns}, events=[dict(local=r["local"], kind=r["kind"], h=round(r["h"], 2), coeff=None if r["coeff"] is None or pd.isna(r["coeff"]) else round(r["coeff"])) for _, r in events.iterrows()])
    (C.V2 / "tide.json").write_text(json.dumps(out), encoding="utf-8")
    print(f"\n  Marnage de la fenêtre : {hourly['eta'].min():+.2f} m à {hourly['eta'].max():+.2f} m ; coefficients estimés {hourly['coeff'].min():.0f} à {hourly['coeff'].max():.0f}")
    print(f"  -> {C.V2 / 'tide.json'}")
    return True


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
