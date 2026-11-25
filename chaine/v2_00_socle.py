"""
v2_00_socle.py : trait de côte et zones de départ, à partir de données ouvertes.

1. Contour de la commune de Quiberon (geo.api.gouv.fr), élargi de 500 m.
2. Trait de côte, plages et ports dans OpenStreetMap (API Overpass).
3. Côte rocheuse = trait de côte moins les plages et les ports.
4. Zone candidate = la bande de mer de 120 m (portée d'un lancer) au pied de cette côte rocheuse, dans le contour communal élargi. v2_02 la nettoie et la découpe ensuite.

Sorties : data/processed/osm_cote.geojson, data/processed/candidate_zones.geojson. Rien n'est refait si les deux fichiers existent : les supprimer pour reconstruire.
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon, shape
from shapely.ops import linemerge, polygonize, unary_union

sys.path.insert(0, str(Path(__file__).parent))
import v2_config as C

OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
ENTETES = {"User-Agent": "BarPeche/2 (atlas personnel de peche)"}


def lire_json(url, data=None, essais=3):
    raison = ""
    for i in range(essais):
        try:
            req = urllib.request.Request(url, data=data, headers=ENTETES)
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc: # coupure réseau : on réessaie, au bout de 3 échecs on s'arrête
            raison = str(exc)[:120]
            time.sleep(5 * (i + 1))
    raise RuntimeError(raison)


def commune():
    nom, dep = C.COMMUNE
    url = ("https://geo.api.gouv.fr/communes?" + urllib.parse.urlencode(
        dict(nom=nom, codeDepartement=dep, fields="nom,code", format="geojson", geometry="contour")))
    feats = [f for f in lire_json(url)["features"] if f["properties"]["nom"] == nom]
    if not feats:
        raise RuntimeError(f"commune {nom} introuvable")
    print(f"  Commune : {nom} ({feats[0]['properties']['code']})")
    g = gpd.GeoSeries([shape(feats[0]["geometry"])], crs=C.CRS_WGS84).to_crs(C.CRS_METRIC)
    return g.iloc[0].buffer(C.COMMUNE_BUFFER_M)


def osm():
    b = C.COAST_BBOX
    bb = f"{b['ymin']},{b['xmin']},{b['ymax']},{b['xmax']}"
    q = f"""[out:json][timeout:180];
(
  way["natural"="coastline"]({bb});
  way["natural"~"^(beach|sand)$"]({bb});
  relation["natural"~"^(beach|sand)$"]({bb});
  way["landuse"="harbour"]({bb});
  way["leisure"="marina"]({bb});
  relation["leisure"="marina"]({bb});
);
out geom;"""
    data = urllib.parse.urlencode({"data": q}).encode()
    raison = ""
    for url in OVERPASS:
        try:
            return lire_json(url, data=data)["elements"]
        except RuntimeError as exc: # serveur Overpass indisponible : on passe au suivant
            raison = str(exc)
            print(f"  Overpass : échec avec {url.split('/')[2]} ({raison[:80]})")
    raise RuntimeError(raison)


def _ligne(geom):
    return LineString([(p["lon"], p["lat"]) for p in geom])


def decouper(elements):
    """Trait de côte (lignes orientées, terre à gauche) et surfaces à exclure (plages, ports)."""
    cote, exclues = [], []
    for e in elements:
        tags = e.get("tags", {})
        if e["type"] == "way" and len(e.get("geometry", [])) >= 2:
            ln = _ligne(e["geometry"])
            if tags.get("natural") == "coastline":
                cote.append(ln)
            elif ln.is_ring and len(ln.coords) >= 4:
                exclues.append(Polygon(ln.coords))
        elif e["type"] == "relation":
            outer = [_ligne(m["geometry"]) for m in e.get("members", []) if m.get("role") == "outer" and len(m.get("geometry", [])) >= 2]
            exclues += list(polygonize(linemerge(outer))) if outer else []
    proj = lambda geoms: list(gpd.GeoSeries(geoms, crs=C.CRS_WGS84).to_crs(C.CRS_METRIC))
    return proj(cote), proj(exclues) if exclues else []


def meme_sens(morceau, ln):
    """Une découpe peut retourner la ligne : on la remet dans le sens d'origine (terre à gauche)."""
    a = ln.project(morceau.interpolate(0.25, normalized=True))
    b = ln.project(morceau.interpolate(0.75, normalized=True))
    return LineString(morceau.coords[::-1]) if b < a else morceau


def bande_de_mer(cote, exclues, limite):
    """Mer à portée de lancer depuis la côte rocheuse, dans la limite communale élargie."""
    a_exclure = unary_union([p.buffer(25) for p in exclues]) if exclues else None
    mer, terre = [], []
    for ln in cote:
        terre.append(ln.buffer(C.BANDE_M, single_sided=True)) # gauche du trait : la terre
        if not ln.intersects(limite):
            continue
        roche = ln.difference(a_exclure) if a_exclure is not None else ln
        for morceau in getattr(roche, "geoms", [roche]):
            if morceau.geom_type == "LineString" and morceau.length > 30:
                mer.append(meme_sens(morceau, ln).buffer(-C.BANDE_M, single_sided=True)) # droite : la mer
    if not mer:
        return None
    zone = unary_union(mer).difference(unary_union(terre)).intersection(limite)
    if a_exclure is not None:
        zone = zone.difference(a_exclure)
    return zone


def run():
    print("=== v2_00 : trait de côte et zones de départ ===")
    if C.ZONES_SRC.exists() and C.COAST_SRC.exists():
        print(f"  [déjà là] {C.ZONES_SRC.name}, {C.COAST_SRC.name}")
        return True
    limite = commune()
    elements = osm()

    cote, exclues = decouper(elements)
    print(f"  OpenStreetMap : {len(cote)} tronçons de côte, {len(exclues)} plages et ports exclus")
    if not cote:
        print("  ERREUR : aucun trait de côte reçu")
        return False
    zone = bande_de_mer(cote, exclues, limite)
    if zone is None or zone.is_empty:
        print("  ERREUR : aucune côte rocheuse dans la limite communale")
        return False

    parts = [p for p in getattr(zone, "geoms", [zone]) if p.geom_type == "Polygon" and p.area >= C.MIN_AREA_M2]
    gpd.GeoDataFrame({"category": ["coastline"] * len(cote)}, geometry=cote, crs=C.CRS_METRIC) \
        .to_crs(C.CRS_WGS84).to_file(C.COAST_SRC, driver="GeoJSON")
    gpd.GeoDataFrame(geometry=parts, crs=C.CRS_METRIC).to_crs(C.CRS_WGS84).to_file(C.ZONES_SRC, driver="GeoJSON")
    print(f"  Bande de {C.BANDE_M} m au pied de la côte rocheuse : {len(parts)} morceaux, {sum(p.area for p in parts) / 1e6:.2f} km²")
    print(f"  -> {C.ZONES_SRC}")
    return True


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
