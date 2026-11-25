# Lecture des sorties de la chaîne Python v2 : soit le dossier data/processed/v2 (npz + json), soit une page atlas_*.html déjà produite.

lire_npy <- function(f) {
  con <- file(f, "rb")
  on.exit(close(con))
  readBin(con, "raw", 6)
  version <- readBin(con, "integer", 1, size = 1)
  readBin(con, "raw", 1)
  n <- readBin(con, "integer", 1, size = if (version == 1) 2 else 4, endian = "little")
  entete <- rawToChar(readBin(con, "raw", n))
  type <- sub(".*'descr': *'([^']+)'.*", "\\1", entete)
  dims <- sub(".*'shape': *\\(([^)]*)\\).*", "\\1", entete)
  dims <- as.integer(Filter(nzchar, trimws(strsplit(dims, ",")[[1]])))
  x <- switch(type,
    "|u1" = readBin(con, "integer", prod(dims), size = 1, signed = FALSE),
    "<f4" = readBin(con, "double", prod(dims), size = 4, endian = "little"),
    "<f8" = readBin(con, "double", prod(dims), size = 8, endian = "little"),
    stop("type numpy non lu : ", type)
  )
  if (length(dims) == 1) x else aperm(array(x, rev(dims))) # numpy range en ordre C
}

lire_npz <- function(f, noms) {
  d <- tempfile()
  utils::unzip(f, files = paste0(noms, ".npy"), exdir = d)
  setNames(lapply(file.path(d, paste0(noms, ".npy")), lire_npy), noms)
}

octets <- function(s, H, Z, k = 1) {
  x <- as.integer(jsonlite::base64_dec(s))
  if (k == 1) matrix(x, H, Z, byrow = TRUE) else aperm(array(x, c(k, Z, H)))
}

lire_zones <- function(f) {
  z <- sf::st_transform(sf::st_read(f, quiet = TRUE), 4326)
  z[order(z$id), ]
}

lire_html <- function(f) {
  txt <- paste(readLines(f, encoding = "UTF-8", warn = FALSE), collapse = "\n")
  json <- regmatches(txt, regexpr('(?s)<script id="payload" type="application/json">.*?</script>', txt, perl = TRUE))
  if (!length(json)) stop("Pas de données dans ", f)
  json <- sub("</script>$", "", sub("^<script[^>]*>", "", json))

  D <- jsonlite::fromJSON(json)
  geo <- tempfile(fileext = ".geojson")
  writeLines(jsonlite::toJSON(jsonlite::fromJSON(json, simplifyVector = FALSE)$zones, auto_unbox = TRUE, digits = NA), geo, useBytes = TRUE)
  zones <- lire_zones(geo)
  H <- nrow(D$hours)
  Z <- nrow(zones)

  list(meta = D$meta, heures = D$hours, soleil = D$sun, maree = D$tide, zones = zones, S = octets(D$S, H, Z), P = octets(D$P, H, Z), COMP = octets(D$COMP, H, Z, 4), HSL = octets(D$HSL, H, Z), CUR = octets(D$CUR, H, Z), source = f, maj = format(file.mtime(f), "%d/%m/%Y"))
}

lire_v2 <- function(dossier) {
  sc <- lire_npz(file.path(dossier, "scores.npz"), c("S", "P", "COMP", "HSL"))
  vitesse <- lire_npz(file.path(dossier, "currents.npz"), "speed")$speed
  heures <- jsonlite::fromJSON(file.path(dossier, "hours.json"))
  maree <- jsonlite::fromJSON(file.path(dossier, "tide.json"))

  # mêmes bornes de couleur que v2_05_atlas.py
  q <- function(x, p) as.integer(stats::quantile(x, p))
  meta <- heures$meta
  meta$year <- as.integer(substr(heures$hours$t[1], 1, 4))
  meta$demo <- FALSE
  meta$s_lo <- q(sc$S, .02)
  meta$s_hi <- max(q(sc$S, .98), q(sc$S, .02) + 5L)
  meta$p_hi <- q(sc$P, .98)
  meta$M2 <- maree$meta$M2
  meta$S2 <- maree$meta$S2
  meta$current_proxy <- isTRUE(maree$meta$current_proxy)

  etat <- file.path(dossier, "etat.json")
  maj <- if (file.exists(etat)) jsonlite::fromJSON(etat)$date else format(file.mtime(file.path(dossier, "scores.npz")), "%d/%m/%Y")

  vitesse[is.na(vitesse)] <- 0
  list(meta = meta, heures = heures$hours, soleil = heures$sun, maree = c(maree$hourly, list(events = maree$events)), zones = lire_zones(file.path(dossier, "zones.geojson")), S = sc$S, P = sc$P, COMP = sc$COMP, HSL = sc$HSL, CUR = pmin(pmax(round(vitesse * 100), 0), 255), source = dossier, maj = maj)
}

charger <- function(dossier = ".") {
  v2 <- file.path(dossier, "data", "processed", "v2")
  if (file.exists(file.path(v2, "scores.npz"))) return(lire_v2(v2))
  atlas <- Sys.glob(file.path(dossier, "data", "output", "atlas", "atlas_2*.html"))
  if (length(atlas)) return(lire_html(tail(sort(atlas), 1)))
  demo <- file.path(dossier, "demo", "atlas_demo_donnees_fictives.html")
  if (file.exists(demo)) return(lire_html(demo))
  stop("Rien à lire dans ", normalizePath(dossier), " : lancer python chaine\\v2_run.py.")
}
