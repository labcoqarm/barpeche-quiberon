"""
v2_config.py : tous les réglages de la chaîne.

L'année cible se règle seule : la prochaine saison pas encore terminée (après le 21 septembre, on passe à l'année suivante). Pour forcer une année : variable d'environnement BARPECHE_ANNEE.
"""
import os
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent # scripts dans chaine/, données dans data/ à côté

# ── Dossiers ────────────────────────────────────────────────────────────────
DATA_RAW = ROOT / "data" / "raw"
DATA_PROC = ROOT / "data" / "processed"
V2 = DATA_PROC / "v2" # tous les produits v2
ERA5_DIR = DATA_RAW / "era5" # era5_YYYY_wind.nc / era5_YYYY_wave.nc
SST_DIR = DATA_RAW / "cmems" # sst_YYYY.nc
IBI_WAVE_DIR = DATA_RAW / "ibi_wave" # ibi_wave_YYYY.nc (téléchargé par v2_01)
IBI_PHY_DIR = DATA_RAW / "ibi_phy" # ibi_phy_*.nc (téléchargé par v2_01)
ATLAS_DIR = ROOT / "data" / "output" / "atlas"

ZONES_SRC = DATA_PROC / "candidate_zones.geojson" # construits par v2_00_socle.py
COAST_SRC = DATA_PROC / "osm_cote.geojson"

for _p in (DATA_PROC, V2, ERA5_DIR, SST_DIR, IBI_WAVE_DIR, IBI_PHY_DIR, ATLAS_DIR):
    _p.mkdir(parents=True, exist_ok=True)

# ── Fenêtre cible ───────────────────────────────────────────────────────────
DEBUT, FIN = (6, 21), (9, 21) # mois, jour
POOL_DAYS = 3 # météo historique prise à ±3 jours autour de chaque date
HIST_FIRST = 2000


def _saison():
    if os.environ.get("BARPECHE_ANNEE"):
        return int(os.environ["BARPECHE_ANNEE"])
    today = date.today()
    return today.year if today <= date(today.year, *FIN) else today.year + 1


YEAR = _saison()
TZ = "Europe/Paris"
START_LOCAL = f"{YEAR}-{DEBUT[0]:02d}-{DEBUT[1]:02d} 00:00"
END_LOCAL = f"{YEAR}-{FIN[0]:02d}-{FIN[1]:02d} 23:00"
HIST_YEARS = list(range(HIST_FIRST, YEAR)) # chaque saison terminée rejoint l'historique


def periode_historique(year):
    """Dates à télécharger pour une année passée : la fenêtre, plus le tirage à ±3 jours et une marge."""
    marge = timedelta(days=POOL_DAYS + 1)
    return date(year, *DEBUT) - marge, date(year, *FIN) + marge

# ── Emprises ────────────────────────────────────────────────────────────────
BBOX = dict(xmin=-3.30, ymin=47.28, xmax=-2.90, ymax=47.58) # emprise du vent ERA5
WAVE_BBOX = dict(xmin=-3.35, ymin=47.30, xmax=-2.90, ymax=47.60) # houle IBI
PHY_BBOX = dict(xmin=-3.28, ymin=47.38, xmax=-2.95, ymax=47.60) # marée et courants IBI
REF_POINT = (-3.085, 47.487) # lon, lat : devant Port Haliguen, référence marée

COAST_BBOX = dict(xmin=-3.45, ymin=47.20, xmax=-2.80, ymax=47.65) # côte prise en compte pour l'abri (Belle-Île, Houat, Hoëdic)
CRS_WGS84 = "EPSG:4326"
CRS_METRIC = "EPSG:2154"

# ── Jeux de données Copernicus ──────────────────────────────────────────────
# Essayés dans l'ordre : réanalyse, puis réanalyse intérimaire, puis analyse temps réel pour les années récentes que la réanalyse ne couvre pas encore.
IBI_WAVE_DATASETS = ["cmems_mod_ibi_wav_my_0.027deg_PT1H-i", "cmems_mod_ibi_wav_myint_0.027deg_PT1H-i", "cmems_mod_ibi_wav_anfc_0.027deg_PT1H-i"]
IBI_WAVE_VARS = [["VHM0", "VMDR", "VTPK"], ["VHM0", "VMDR"]]
SST_DATASETS = ["METOFFICE-GLO-SST-L4-REP-OBS-SST", "METOFFICE-GLO-SST-L4-NRT-OBS-SST-V2"]
IBI_PHY_15M = "cmems_mod_ibi_phy_anfc_0.027deg-2D_PT15M-i"
IBI_PHY_1H = "cmems_mod_ibi_phy_anfc_0.027deg-2D_PT1H-m"
PHY_DAYS = 369 # longueur de la série servant à l'analyse harmonique
PHY_MAX_AGE = 300 # jours : au-delà, la série marée et courants est retéléchargée

# ── Zones ───────────────────────────────────────────────────────────────────
COMMUNE = ("Quiberon", "56") # nom, département
COMMUNE_BUFFER_M = 500 # les zones vont jusqu'à 500 m au-delà de la limite communale
BANDE_M = 120 # largeur de mer à portée de lancer depuis la côte rocheuse
N_DIRS = 72 # un rayon tous les 5°
RAY_KM = 25.0 # longueur maximale d'un rayon
FETCH_CAP_KM = 15.0 # au-delà, la direction compte comme ouverte
SPLIT_AREA_M2 = 150_000 # une zone plus grande est redécoupée
SPLIT_GRID_M = 400
MIN_AREA_M2 = 2_500

# ── Score ───────────────────────────────────────────────────────────────────
# Moyenne géométrique pondérée de quatre facteurs entre 0 et 1 : un facteur franchement mauvais tire le score vers le bas, aucun ne peut être compensé entièrement par les autres. Les poids sont un choix de lecture (article peche.com + littérature), pas un calage sur des prises.
WEIGHTS = dict(agitation=0.30, courant=0.25, lumiere=0.30, eau=0.15)
FLOOR = 0.08 # plancher de chaque facteur avant la moyenne géométrique
TOP_SHARE = 0.20 # "bonnes conditions" = meilleur cinquième des zones-heures-années

# Agitation = ressac (houle locale) OU clapot levé par un vent qui porte vers la zone.
AGIT_FLOOR = 0.25 # mer plate : facteur 0.25, pas zéro (le bar vient aussi au bord par calme, de nuit)
WAVE = dict(lo=0.10, full=0.50, unsafe_lo=1.80, unsafe_hi=3.00) # hauteur locale, m
WIND = dict(lo=1.5, full=4.5, strong=10.0, hi=16.0) # m/s
SUBGRID = 0.35 # part de la houle de la maille qui atteint une zone fermée à la direction de houle

# Lumière : pénombre idéale, nuit bonne, plein jour faible sauf si l'eau est agitée (surface brisée).
LIGHT = dict(night=0.75, night_el=-12.0, tw_lo=-6.0, tw_hi=6.0, day=0.35, day_el=35.0, agit_rescue=0.35)

# Eau (°C)
SST = dict(cold=12.0, cold_score=0.6, ok_lo=14.0, ok_hi=19.5, warm=22.0, warm_score=0.5)
