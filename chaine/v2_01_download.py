"""
v2_01_download.py : téléchargements, année par année, de tout ce que le score utilise.

1. Vent ERA5 (Copernicus Climate, cdsapi) : data/raw/era5/era5_YYYY_wind.nc
2. Température de l'eau OSTIA (Copernicus Marine) : data/raw/cmems/sst_YYYY.nc
3. Houle IBI 1/36°, horaire (Copernicus Marine) : data/raw/ibi_wave/ibi_wave_YYYY.nc
4. Niveau de la mer et courants IBI des 12 derniers mois : data/raw/ibi_phy/ (l'analyse harmonique en tire la marée et les courants de la saison cible)

Pour chaque année de l'historique, un fichier est gardé s'il couvre déjà la période voulue (fenêtre de config ±3 jours). Sinon, les sources sont essayées dans l'ordre (réanalyse, puis temps réel). Si aucune ne répond, l'ancien fichier est gardé ; s'il n'y en a pas, le script s'arrête. Chaque saison terminée s'ajoute donc toute seule au prochain lancement.

Comptes : `copernicusmarine login` déjà fait, et ~/.cdsapirc rempli pour ERA5.
"""
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import v2_config as C
from v2_lib import open_nc


def couvre(path, start, end):
    """Le fichier existe-t-il et couvre-t-il start -> end, à un jour près ?"""
    path = Path(path)
    if not path.exists() or path.stat().st_size < 2000:
        return False
    ds = open_nc(path)
    t = pd.DatetimeIndex(ds["time"].values)
    ds.close()
    jour = pd.Timedelta(days=1)
    return len(t) > 0 and t.min() <= pd.Timestamp(start) + jour and t.max() >= pd.Timestamp(end) - jour


def _message(exc):
    txt = str(exc).strip()
    return txt.splitlines()[0][:110] if txt else type(exc).__name__


def obtenir(label, out, essais, start, end):
    """Essaie chaque source jusqu'à obtenir un fichier qui couvre la période. Renvoie 'ok', 'neuf' ou 'absent'."""
    if couvre(out, start, end):
        return "ok"
    tmp = out.with_name(out.stem + "_tmp.nc")
    raison = ""
    for nom, telecharger in essais:
        try:
            t0 = time.time()
            telecharger(tmp)
            if couvre(tmp, start, end):
                os.replace(tmp, out)
                print(f"  {label} : {out.stat().st_size / 1024:.0f} ko en {time.time() - t0:.0f} s ({nom})")
                return "neuf"
            raison = f"{nom} ne couvre pas toute la période"
        except Exception as exc: # année hors couverture, variable absente, réseau
            raison = _message(exc)
    if tmp.exists():
        tmp.unlink()
    if not out.exists():
        raise RuntimeError(f"{label} : aucune source disponible ({raison})")
    print(f"  {label} : indisponible ({raison}) ; ancien fichier gardé")
    return "absent"


def _subset(dataset_id, variables, bbox, start, end, out_path):
    import copernicusmarine
    out_path = Path(out_path)
    copernicusmarine.subset(
        dataset_id=dataset_id,
        variables=variables,
        minimum_longitude=bbox["xmin"], maximum_longitude=bbox["xmax"],
        minimum_latitude=bbox["ymin"], maximum_latitude=bbox["ymax"],
        start_datetime=start, end_datetime=end,
        output_directory=str(out_path.parent),
        output_filename=out_path.name,
        overwrite=True,
    )
    if not out_path.exists() or out_path.stat().st_size < 2000:
        raise RuntimeError(f"fichier absent ou vide : {out_path.name}")


def _era5(year, start, end, out):
    import cdsapi
    mois = sorted({f"{d.month:02d}" for d in pd.date_range(start, end, freq="D")})
    cdsapi.Client(quiet=True, progress=False).retrieve("reanalysis-era5-single-levels", {
        "product_type": ["reanalysis"],
        "variable": ["10m_u_component_of_wind", "10m_v_component_of_wind"],
        "year": [str(year)], "month": mois,
        "day": [f"{d:02d}" for d in range(1, 32)],
        "time": [f"{h:02d}:00" for h in range(24)],
        "area": [C.BBOX["ymax"], C.BBOX["xmin"], C.BBOX["ymin"], C.BBOX["xmax"]],
        "data_format": "netcdf",
        "download_format": "unarchived",
    }, str(out))


def historique():
    bilan = {"ok": 0, "neuf": 0, "absent": 0}

    for year in C.HIST_YEARS:
        d0, d1 = C.periode_historique(year)
        s, e = f"{d0}T00:00:00", f"{d1}T23:00:00"

        r = obtenir(f"{year} vent", C.ERA5_DIR / f"era5_{year}_wind.nc", [("ERA5", lambda p, y=year: _era5(y, d0, d1, p))], d0, d1)
        bilan[r] += 1

        r = obtenir(f"{year} eau", C.SST_DIR / f"sst_{year}.nc", [(ds, lambda p, ds=ds: _subset(ds, ["analysed_sst"], C.WAVE_BBOX, s, e, p)) for ds in C.SST_DATASETS], d0, d1)
        bilan[r] += 1

        r = obtenir(f"{year} houle", C.IBI_WAVE_DIR / f"ibi_wave_{year}.nc", [(ds.split("_")[4], lambda p, ds=ds, v=v: _subset(ds, v, C.WAVE_BBOX, s, e, p)) for ds in C.IBI_WAVE_DATASETS for v in C.IBI_WAVE_VARS], d0, d1)
        bilan[r] += 1

    print(f"  Historique {C.HIST_YEARS[0]}-{C.HIST_YEARS[-1]} : {bilan['ok']} fichiers déjà complets, {bilan['neuf']} téléchargés, {bilan['absent']} indisponibles")


def physique():
    print(f"\n  Niveau de la mer et courants IBI (marée {C.YEAR})")
    end = datetime.now(timezone.utc) - timedelta(days=3)
    start = end - timedelta(days=C.PHY_DAYS)
    s, e = start.strftime("%Y-%m-%dT00:00:00"), end.strftime("%Y-%m-%dT00:00:00")

    def frais(p):
        return p.exists() and p.stat().st_size > 50_000 and time.time() - p.stat().st_mtime < C.PHY_MAX_AGE * 86400

    for nom, variables, out, vital in (("niveau", ["zos"], C.IBI_PHY_DIR / "ibi_phy_ssh.nc", True), ("courants", ["uo", "vo"], C.IBI_PHY_DIR / "ibi_phy_cur.nc", False)):
        if frais(out):
            print(f"  [à jour] {out.name}")
            continue
        tmp = out.with_name(out.stem + "_tmp.nc")
        for ds_id in (C.IBI_PHY_15M, C.IBI_PHY_1H):
            try:
                t0 = time.time()
                _subset(ds_id, variables, C.PHY_BBOX, s, e, tmp)
                os.replace(tmp, out)
                print(f"  {nom} : {out.stat().st_size / 1e6:.1f} Mo en {time.time() - t0:.0f} s ({ds_id})")
                break
            except Exception as exc: # ce jeu ne répond pas : on essaie le suivant
                print(f"  {nom} : échec avec {ds_id} ({_message(exc)})")
        else:
            if tmp.exists():
                tmp.unlink()
            if out.exists():
                print(f"  {nom} : ancien fichier gardé")
            elif vital:
                raise RuntimeError(f"niveau de la mer introuvable, pas de marée {C.YEAR}. Vérifier `copernicusmarine login`.")
            else:
                print("  Courants indisponibles : le score utilisera la vitesse de variation du niveau.")
    return True


def run():
    print(f"=== v2_01 : téléchargements (saison {C.YEAR}, historique {C.HIST_YEARS[0]}-{C.HIST_YEARS[-1]}) ===")
    import cdsapi # noqa: F401 (vérifie dès le départ que les deux paquets sont installés)
    import copernicusmarine # noqa: F401
    historique()
    return physique()


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
