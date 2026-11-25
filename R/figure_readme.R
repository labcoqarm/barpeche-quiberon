# Carte de l'indice moyen de la saison par zone pour le README (figures/indice_moyen.png). Lancer depuis la racine du projet.

library(ggplot2)
source("R/donnees.R")

# Échelle et flèche du nord, dessinées avec ggplot2 seul (carte en longitude/latitude)
echelle_nord <- function(emprise, km) {
  larg <- emprise[["xmax"]] - emprise[["xmin"]]
  haut <- emprise[["ymax"]] - emprise[["ymin"]]
  dx <- km / (111.32 * cos(mean(c(emprise[["ymin"]], emprise[["ymax"]])) * pi / 180)) # km convertis en degrés de longitude
  h <- haut * 0.012
  x0 <- emprise[["xmin"]] + larg * 0.05
  y0 <- emprise[["ymin"]] + haut * 0.04
  xn <- emprise[["xmax"]] - larg * 0.08
  yn <- emprise[["ymax"]] - haut * 0.15
  list(
    annotate("rect", xmin = x0, xmax = x0 + dx / 2, ymin = y0, ymax = y0 + h, fill = "black", colour = "black"),
    annotate("rect", xmin = x0 + dx / 2, xmax = x0 + dx, ymin = y0, ymax = y0 + h, fill = "white", colour = "black"),
    annotate("text", x = c(x0, x0 + dx / 2, x0 + dx), y = y0 + 3 * h, label = c("0", km / 2, paste(km, "km")), size = 3),
    annotate("segment", x = xn, xend = xn, y = yn, yend = yn + 8 * h, arrow = arrow(length = unit(2.5, "mm"), type = "closed")),
    annotate("text", x = xn, y = yn + 11 * h, label = "N", fontface = "bold", size = 4)
  )
}

A <- charger(".")
zones <- A$zones
zones$indice <- colMeans(A$S)
emprise <- sf::st_bbox(zones)
emprise[c("xmin", "ymin")] <- emprise[c("xmin", "ymin")] - 0.02
emprise[c("xmax", "ymax")] <- emprise[c("xmax", "ymax")] + 0.02
cote <- sf::st_crop(sf::st_geometry(sf::st_read("data/processed/osm_cote.geojson", quiet = TRUE)), emprise)

ggplot() +
  geom_sf(data = cote, colour = "grey40", linewidth = 0.3) +
  geom_sf(data = zones, aes(fill = indice), colour = "white", linewidth = 0.1) +
  scale_fill_distiller(palette = "YlGnBu", direction = 1, name = "Indice\nmoyen") +
  echelle_nord(emprise, 2) +
  labs(title = "Pêche au bar du bord à Quiberon", subtitle = paste0("Indice moyen de chaque zone, toutes heures du 21 juin au 21 septembre ", A$meta$year), caption = "Météo rejouée de 2000 à la dernière saison terminée (ERA5, Copernicus Marine). Côte : OpenStreetMap.") +
  theme_void(base_family = "sans")
ggsave("figures/indice_moyen.png", width = 7, height = 8, dpi = 200, bg = "white")
