"""
v2_run.py : lance toute la chaîne dans l'ordre. Depuis le dossier du projet :

python chaine/v2_run.py : télécharge ce qui manque, puis recalcule si quelque chose a changé
python chaine/v2_run.py --force : recalcule même si rien n'a changé
python chaine/v2_run.py --gpkg : ajoute le GeoPackage pour le contrôleur temporel de QGIS
python chaine/v2_run.py --sans-telechargement : si les fichiers sont déjà là

Premier lancement : 30 à 90 min de téléchargements (file d'attente ERA5). Ensuite, quelques secondes s'il n'y a rien de neuf, 5 à 10 min quand une saison s'ajoute.
"""
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))
import v2_config as C

SORTIES = ["zones.geojson", "scores.npz", "hours.json", "tide.json", "currents.npz"]


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def empreinte():
    """Résumé des entrées : année, fichiers bruts, scripts. S'il ne bouge pas, le résultat non plus."""
    fichiers = [C.ZONES_SRC, C.COAST_SRC, *sorted(HERE.glob("v2_*.py"))]
    for d in (C.ERA5_DIR, C.SST_DIR, C.IBI_WAVE_DIR, C.IBI_PHY_DIR):
        fichiers += sorted(p for p in d.glob("*.nc") if not p.stem.endswith("_tmp"))
    h = hashlib.sha1(f"{C.YEAR} {C.START_LOCAL} {C.END_LOCAL}".encode())
    for p in fichiers:
        if p.exists():
            st = p.stat()
            h.update(f"{p.name} {st.st_size} {st.st_mtime_ns}".encode())
    return h.hexdigest()


def main():
    t0 = time.time()
    print(f"BarPeche : saison {C.YEAR} ({C.START_LOCAL[5:10]} au {C.END_LOCAL[5:10]}), {time.strftime('%d/%m/%Y %H:%M')}")
    if not load("v2_00_socle").run():
        print("\nArrêt : sans trait de côte, pas de zones.")
        return 1
    print()
    if "--sans-telechargement" not in sys.argv and not load("v2_01_download").run():
        print("\nArrêt aux téléchargements. Corriger le point signalé puis relancer.")
        return 1

    etat_path = C.V2 / "etat.json"
    etat = json.loads(etat_path.read_text(encoding="utf-8")) if etat_path.exists() else {}
    signature = empreinte()
    if (etat.get("empreinte") == signature and "--force" not in sys.argv and all((C.V2 / n).exists() for n in SORTIES)):
        print(f"\nRien de neuf depuis le {etat.get('date', '?')} : résultats inchangés.")
        return 0

    for name, kw in [("v2_02_zones", {}), ("v2_03_tides", {}), ("v2_04_score", {}), ("v2_05_atlas", dict(gpkg="--gpkg" in sys.argv))]:
        print()
        if not load(name).run(**kw):
            print(f"\nArrêt à l'étape {name}. Corriger le point signalé ci-dessus puis relancer.")
            return 1

    etat_path.write_text(json.dumps(dict(empreinte=signature, annee=C.YEAR, date=time.strftime("%d/%m/%Y %H:%M"))), encoding="utf-8")
    print(f"\nTerminé en {time.time() - t0:.0f} s.")
    print(f"  Appli : ouvrir app.R dans RStudio, Run App")
    print(f"  Page seule : {C.ATLAS_DIR / f'atlas_{C.YEAR}.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
