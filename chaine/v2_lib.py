"""v2_lib.py : fonctions partagées par les scripts v2."""
import numpy as np
import pandas as pd
import xarray as xr

SECTORS8 = ["nord", "nord-est", "est", "sud-est", "sud", "sud-ouest", "ouest", "nord-ouest"]
SECTORS16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"]


def sector8(deg):
    return SECTORS8[int(((float(deg) % 360) + 22.5) // 45) % 8]


def sector16(deg):
    return SECTORS16[int(((float(deg) % 360) + 11.25) // 22.5) % 16]


def open_nc(path):
    """Ouvre un NetCDF et ramène les noms de coordonnées à time / latitude / longitude."""
    ds = xr.open_dataset(path)
    ren = {}
    for old, new in (("valid_time", "time"), ("lat", "latitude"), ("lon", "longitude")):
        if old in ds.variables and new not in ds.variables:
            ren[old] = new
    if ren:
        ds = ds.rename(ren)
    for extra in ("depth", "number", "expver"):
        if extra in ds.dims and ds.sizes[extra] == 1:
            ds = ds.isel({extra: 0}, drop=True)
    return ds


def cube(ds, name):
    """Champ (time, latitude, longitude) sous forme de tableau numpy, dans cet ordre."""
    return ds[name].transpose("time", "latitude", "longitude").values


def series_mean(da):
    """Moyenne spatiale d'un champ (time, lat, lon) -> pd.Series indexée par le temps UTC."""
    dims = [d for d in da.dims if d != "time"]
    vals = da.mean(dim=dims, skipna=True).values if dims else da.values
    return pd.Series(np.asarray(vals, dtype="float64"), index=pd.DatetimeIndex(da["time"].values).round("s"))


def ramp(x, x0, x1):
    """0 en x0, 1 en x1, linéaire entre les deux."""
    return np.clip((np.asarray(x, dtype="float64") - x0) / (x1 - x0), 0.0, 1.0)


def solar_elevation(times_utc, lon, lat):
    """Hauteur du soleil en degrés (formule NOAA simplifiée, précision d'environ 0.5°)."""
    t = pd.DatetimeIndex(times_utc)
    doy = t.dayofyear.values
    hour = t.hour.values + t.minute.values / 60.0
    g = 2 * np.pi / 365.0 * (doy - 1 + (hour - 12) / 24.0)
    eqtime = 229.18 * (0.000075 + 0.001868 * np.cos(g) - 0.032077 * np.sin(g) - 0.014615 * np.cos(2 * g) - 0.040849 * np.sin(2 * g))
    decl = (0.006918 - 0.399912 * np.cos(g) + 0.070257 * np.sin(g) - 0.006758 * np.cos(2 * g) + 0.000907 * np.sin(2 * g) - 0.002697 * np.cos(3 * g) + 0.00148 * np.sin(3 * g))
    tst = hour * 60 + eqtime + 4 * lon # temps solaire vrai, minutes
    ha = np.radians(tst / 4.0 - 180.0)
    la = np.radians(lat)
    cosz = np.sin(la) * np.sin(decl) + np.cos(la) * np.cos(decl) * np.cos(ha)
    return 90.0 - np.degrees(np.arccos(np.clip(cosz, -1, 1)))


def window_local(C):
    """Heures locales de la fenêtre cible et leurs équivalents UTC (sans fuseau)."""
    loc = pd.date_range(C.START_LOCAL, C.END_LOCAL, freq="1h", tz=C.TZ)
    utc = loc.tz_convert("UTC").tz_localize(None)
    return loc, utc


def nearest_wet(lons, lats, wet, lon, lat):
    """Indice (j, i) de la maille en eau la plus proche d'un point ; distance en km."""
    lon2, lat2 = np.meshgrid(lons, lats)
    d = np.hypot((lon2 - lon) * np.cos(np.radians(lat)) * 111.2, (lat2 - lat) * 111.2)
    d = np.where(wet, d, np.inf)
    j, i = np.unravel_index(np.argmin(d), d.shape)
    return int(j), int(i), float(d[j, i])
