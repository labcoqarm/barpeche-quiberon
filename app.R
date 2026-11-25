# Pêche au bar à Quiberon : atlas horaire, version Shiny. Paquets : shiny, leaflet, sf, jsonlite. Lancer : shiny::runApp() depuis ce dossier.

library(shiny)
library(leaflet)

A <- charger(".")
M <- A$meta
H <- nrow(A$heures)
Z <- nrow(A$zones)
NJ <- H %/% 24

JOURS <- c("dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi")
MOIS <- c("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")
ROSE <- "#C2185B"

instant <- function(x) as.POSIXct(x, format = "%Y-%m-%dT%H:%M", tz = "UTC")
t_h <- instant(A$heures$t)
t_ev <- instant(A$maree$events$local)

heure_de <- function(h) (h - 1) %% 24
debut_jour <- function(h) (h - 1) %/% 24 * 24
jour_nom <- function(h, court = FALSE) {
  wd <- as.integer(format(t_h[h], "%w")) + 1
  j <- as.integer(format(t_h[h], "%d"))
  m <- MOIS[as.integer(format(t_h[h], "%m"))]
  if (court) paste0(substr(JOURS[wd], 1, 3), ". ", j, " ", substr(m, 1, 4), ".")
  else paste(JOURS[wd], j, m)
}
fr1 <- function(x) ifelse(is.na(x), "n. d.", formatC(x, format = "f", digits = 1, decimal.mark = ","))
clic <- function(id, valeur) sprintf("Shiny.setInputValue('%s', %s, {priority: 'event'})", id, valeur)

valeurs <- list(S = A$S, P = A$P)
max_heure <- lapply(valeurs, function(m) apply(m, 1, max))
bornes <- list(S = c(M$s_lo, M$s_hi), P = c(0, max(40, M$p_hi)))
degrade <- colorRamp(c("#F3F0DC", "#B8DDB0", "#5DB7B1", "#2C6E9E", "#3B1F6E"))
couleur <- function(v, m) {
  x <- pmin(1, pmax(0, (v - bornes[[m]][1]) / diff(bornes[[m]])))
  rgb(degrade(x), maxColorValue = 255)
}
unite <- function(v, m) if (m == "S") as.character(v) else paste(v, "%")

# même règle que v2_config.py : après le 21 septembre, on attend la saison suivante
saison_attendue <- function(d = Sys.Date()) {
  a <- as.integer(format(d, "%Y"))
  if (d <= as.Date(sprintf("%d-09-21", a))) a else a + 1L
}
perime <- !isTRUE(M$demo) && M$year < saison_attendue()

ign <- function(couche, format) {
  paste0("https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=", couche, "&STYLE=normal&FORMAT=", format, "&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}")
}
# aucun de ces fonds ne demande de clé
FONDS <- list(
  "Plan IGN" = list(ign("GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2", "image/png"), "© IGN Géoplateforme"),
  "Photo IGN" = list(ign("ORTHOIMAGERY.ORTHOPHOTOS", "image/jpeg"), "© IGN Géoplateforme"),
  "Photo Esri" = list("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", "Esri, Maxar")
)

texte_maree <- function(h) {
  T <- A$maree
  dt <- as.numeric(difftime(t_ev, t_h[h], units = "hours"))
  i <- which.min(abs(dt))
  if (abs(dt[i]) <= 0.5) {
    l1 <- paste("Étale de", if (T$events$kind[i] == "PM") "pleine mer" else "basse mer")
  } else {
    dp <- T$h_from_pm[h]
    l1 <- sprintf("%s, %d h %s la pleine mer", if (T$rate[h] > 0) "Montante" else "Descendante", round(abs(dp)), if (dp < 0) "avant" else "après")
  }
  c(l1, sprintf("coefficient %d, %s%s m par rapport au niveau moyen", round(T$coeff[h]), if (T$eta[h] >= 0) "+" else "−", fr1(abs(T$eta[h]))))
}

texte_lumiere <- function(h) {
  e <- A$heures$sun[h]
  s <- A$soleil[[format(t_h[h], "%Y-%m-%d")]]
  nom <- if (e < -12) "Nuit noire" else if (e < -6) "Nuit, lueur à l'horizon" else if (e < 0) (if (heure_de(h) < 12) "Aube" else "Crépuscule") else if (e < 6) "Soleil rasant" else if (e < 25) "Soleil bas" else "Plein jour"
  c(nom, if (length(s)) paste0("lever ", s[1], ", coucher ", s[2]) else "")
}

meilleurs_creneaux <- function(z, n = 3) {
  pris <- integer(0)
  for (c in order(-A$S[, z])) {
    if (all(abs(pris - c) >= 12)) pris <- c(pris, c)
    if (length(pris) == n) break
  }
  pris
}

css <- "
* { font-family: Arial, Helvetica, sans-serif; box-sizing: border-box; }
html, body { height: 100%; margin: 0; font-size: 14px; color: #111; }
.app { display: flex; flex-direction: column; height: 100vh; }
.barre { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; padding: 6px 10px; background: #ececec; border-bottom: 1px solid #999; }
.barre .titre { font-weight: bold; margin-right: 8px; }
.barre .demo { color: #b00000; margin-right: 8px; }
.barre .btn, .barre select { border: 1px solid #888; border-radius: 0; background: #fff; height: 28px; padding: 2px 8px; font-size: 13px; box-shadow: none; }
.barre .btn.actif { background: #222; color: #fff; border-color: #222; }
.barre .form-group { margin: 0; width: auto !important; }
.barre select.form-control { width: auto; display: inline-block; }
.barre .sep { width: 1px; height: 22px; background: #999; margin: 0 5px; }
.corps { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) 330px; grid-template-rows: minmax(0, 1fr) auto; }
#carte { grid-column: 1; grid-row: 1; height: 100% !important; }
.cal { grid-column: 1; grid-row: 2; border-top: 1px solid #999; padding: 4px 8px 6px; }
.cal .tete { display: flex; justify-content: space-between; font-size: 12px; color: #444; }
.cal .tete b { color: #111; }
.legende { display: inline-block; width: 120px; height: 9px; vertical-align: middle; margin: 0 4px; background: linear-gradient(90deg, #F3F0DC, #B8DDB0, #5DB7B1, #2C6E9E, #3B1F6E); }
.panneau { grid-column: 2; grid-row: 1 / span 2; overflow-y: auto; border-left: 1px solid #999; padding: 8px 12px 20px; }
.panneau h2 { font-size: 18px; margin: 4px 0 10px; }
.panneau h3 { font-size: 14px; margin: 16px 0 6px; padding-bottom: 2px; border-bottom: 1px solid #bbb; }
.gris { color: #555; font-size: 12px; }
table.t { width: 100%; border-collapse: collapse; }
table.t td { padding: 4px; border-bottom: 1px solid #e2e2e2; vertical-align: top; }
table.t td.n { text-align: right; font-weight: bold; white-space: nowrap; }
table.t tr.lien { cursor: pointer; }
table.t tr.lien:hover { background: #f2f2f2; }
.carre { display: inline-block; width: 10px; height: 10px; margin-right: 5px; border: 1px solid #777; }
.jauge { height: 7px; background: #e2e2e2; margin-top: 3px; }
.jauge i { display: block; height: 100%; background: #333; }
.fiche { border: 2px solid #C2185B; padding: 8px 10px; margin-bottom: 6px; }
.fiche .entete { display: flex; justify-content: space-between; }
.profil { display: flex; align-items: flex-end; gap: 2px; height: 56px; margin-top: 6px; }
.profil div { flex: 1; cursor: pointer; }
.profil .now { outline: 2px solid #C2185B; }
.axe { display: flex; justify-content: space-between; font-size: 11px; color: #555; }
.modal-content { border-radius: 0; }
"

js <- "
Shiny.addCustomMessageHandler('regler', function(m) {
  for (var k in m) document.getElementById(k).value = m[k];
});
Shiny.addCustomMessageHandler('mode', function(m) {
  document.getElementById('mS').classList.toggle('actif', m === 'S');
  document.getElementById('mP').classList.toggle('actif', m === 'P');
});
document.addEventListener('keydown', function(e) {
  var t = e.target.tagName;
  if (t === 'SELECT' || t === 'INPUT' || document.querySelector('.modal.in')) return;
  var pas = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: -24, ArrowDown: 24}[e.key];
  if (pas) { Shiny.setInputValue('pas', pas, {priority: 'event'}); e.preventDefault(); }
  else if (e.key === ' ' && t !== 'BUTTON') { Shiny.setInputValue('espace', 1, {priority: 'event'}); e.preventDefault(); }
});
"

# select dont seul l'utilisateur déclenche l'événement : le serveur le règle sans écho
liste <- function(id, evenement, choix, largeur) {
  tags$select(id = id, style = paste0("width:", largeur), onchange = clic(evenement, "this.value"), lapply(seq_along(choix), function(i) tags$option(value = choix[[i]], names(choix)[i])))
}

ui <- fillPage(
  tags$head(tags$style(HTML(css)), tags$script(HTML(js)), tags$title(sprintf("Pêche au bar à Quiberon (%d)", M$year))),
  div(class = "app",
    div(class = "barre",
      span(class = "titre", sprintf("Pêche au bar à Quiberon (%d)", M$year)),
      if (isTRUE(M$demo)) span(class = "demo", "données fictives"),
      if (perime) span(class = "demo", "données périmées : lancer mise_a_jour.bat"),
      actionButton("jm", "« jour"),
      actionButton("hm", "‹ heure"),
      liste("sel_jour", "jour_choisi", setNames(as.list(0:(NJ - 1)), sapply(seq(1, H, 24), jour_nom, court = TRUE)), "120px"),
      liste("sel_heure", "heure_choisie", setNames(as.list(0:23), paste(0:23, "h")), "64px"),
      actionButton("hp", "heure ›"),
      actionButton("jp", "jour »"),
      actionButton("lecture", "Lecture"),
      span(class = "sep"),
      actionButton("mS", "Indice", class = "actif"),
      actionButton("mP", "Chances"),
      span(class = "sep"),
      liste("sel_zone", "zone_choisie", c(list("Toutes les zones" = ""), setNames(as.list(seq_len(Z)), A$zones$name)), "140px"),
      selectInput("fond", NULL, names(FONDS), selectize = FALSE),
      selectInput("opacite", NULL, c("Zones 90 %" = 0.9, "Zones 70 %" = 0.7, "Zones 50 %" = 0.5, "Zones 30 %" = 0.3), selected = 0.7, selectize = FALSE),
      actionButton("aide", "Aide")
    ),
    div(class = "corps",
      leafletOutput("carte"),
      div(class = "cal",
        div(class = "tete", uiOutput("cal_titre"), textOutput("survol", inline = TRUE)),
        plotOutput("calendrier", height = "190px", click = "cal_clic", hover = hoverOpts("cal_survol", delay = 60, delayType = "throttle"))
      ),
      div(class = "panneau",
        uiOutput("quand"),
        uiOutput("fiche"),
        h3("Meilleures zones à cette heure"),
        uiOutput("top"),
        h3("Conditions"),
        uiOutput("conditions"),
        plotOutput("courbe_maree", height = "50px"),
        p(class = "gris", sprintf("Marée et lumière calculées pour %d. Vent, houle et eau : valeurs habituelles à cette date, %d à %d.", M$year, M$years[1], M$years[2]))
      )
    )
  )
)

server <- function(input, output, session) {
  h <- reactiveVal(which.max(max_heure$S))
  zone <- reactiveVal(NA_integer_)
  mode <- reactiveVal("S")
  lecture <- reactiveVal(FALSE)

  aller <- function(x) h((x - 1) %% H + 1)

  observeEvent(input$hm, aller(h() - 1))
  observeEvent(input$hp, aller(h() + 1))
  observeEvent(input$jm, aller(h() - 24))
  observeEvent(input$jp, aller(h() + 24))
  observeEvent(input$pas, aller(h() + input$pas))
  observeEvent(input$aller, aller(input$aller))
  observeEvent(input$jour_choisi, aller(as.integer(input$jour_choisi) * 24 + heure_de(h()) + 1))
  observeEvent(input$heure_choisie, aller(debut_jour(h()) + as.integer(input$heure_choisie) + 1))
  observeEvent(input$cal_clic, {
    d <- floor(input$cal_clic$x)
    k <- floor(input$cal_clic$y)
    if (d >= 0 && d < NJ && k >= 0 && k < 24) aller(d * 24 + k + 1)
  })
  observeEvent(h(), session$sendCustomMessage("regler", list(sel_jour = (h() - 1) %/% 24, sel_heure = heure_de(h()))))

  basculer <- function() lecture(!lecture())
  observeEvent(input$lecture, basculer())
  observeEvent(input$espace, basculer())
  observeEvent(lecture(), updateActionButton(session, "lecture", label = if (lecture()) "Pause" else "Lecture"))
  observe({
    if (!lecture()) return()
    invalidateLater(800)
    isolate(aller(h() + 1))
  })

  observeEvent(input$mS, mode("S"))
  observeEvent(input$mP, mode("P"))
  observeEvent(mode(), session$sendCustomMessage("mode", mode()))

  centrer <- function(z) {
    if (is.na(z)) return()
    zoom <- if (is.null(input$carte_zoom)) 13 else input$carte_zoom
    leafletProxy("carte") |> setView(A$zones$lon[z], A$zones$lat[z], zoom)
  }
  observeEvent(input$carte_shape_click, {
    z <- as.integer(input$carte_shape_click$id)
    zone(if (identical(z, zone())) NA_integer_ else z)
  })
  observeEvent(input$zone_choisie, {
    zone(if (input$zone_choisie == "") NA_integer_ else as.integer(input$zone_choisie))
    centrer(zone())
  })
  observeEvent(input$clic_zone, {
    zone(as.integer(input$clic_zone))
    centrer(zone())
  })
  observeEvent(input$fermer, zone(NA_integer_))
  observeEvent(zone(), session$sendCustomMessage("regler", list(sel_zone = if (is.na(zone())) "" else zone())), ignoreNULL = FALSE)

  # leaflet ignore ce qu'on lui envoie avant d'être affiché : on attend son premier zoom
  carte_prete <- reactiveVal(FALSE)
  observeEvent(input$carte_zoom, carte_prete(TRUE), once = TRUE)

  output$carte <- renderLeaflet({
    bb <- unname(sf::st_bbox(A$zones))
    leaflet(options = leafletOptions(zoomSnap = 0.25)) |>
      addScaleBar("bottomleft", scaleBarOptions(imperial = FALSE)) |>
      fitBounds(bb[1], bb[2], bb[3], bb[4])
  })

  observe({
    req(carte_prete(), input$fond)
    f <- FONDS[[input$fond]]
    leafletProxy("carte") |>
      clearGroup("fond") |>
      addTiles(f[[1]], attribution = f[[2]], group = "fond", options = tileOptions(maxZoom = 19))
  })

  observe({
    req(carte_prete(), input$opacite)
    m <- mode()
    v <- valeurs[[m]][h(), ]
    z <- zone()
    choisie <- !is.na(z) & seq_len(Z) == z
    ordre <- order(choisie) # la zone choisie en dernier, donc au-dessus
    leafletProxy("carte") |>
      clearGroup("zones") |>
      addPolygons(data = A$zones[ordre, ], layerId = ordre, group = "zones", fillColor = couleur(v[ordre], m), fillOpacity = as.numeric(input$opacite), color = ifelse(choisie[ordre], ROSE, "#222"), weight = ifelse(choisie[ordre], 3, 0.6), opacity = ifelse(choisie[ordre], 1, 0.6), label = sprintf("%s : %s", A$zones$name[ordre], unite(v[ordre], m)))
  })

  output$quand <- renderUI(h2(paste0(jour_nom(h()), ", ", heure_de(h()), " h")))

  output$top <- renderUI({
    m <- mode()
    v <- valeurs[[m]][h(), ]
    lignes <- lapply(order(-v)[1:min(5, Z)], function(z) {
      tags$tr(class = "lien", onclick = clic("clic_zone", z),
        tags$td(span(class = "carre", style = paste0("background:", couleur(v[z], m))), A$zones$name[z], div(class = "gris", paste0("face ", A$zones$facing[z], ", ", A$zones$exposure[z]))),
        tags$td(class = "n", unite(v[z], m)))
    })
    tags$table(class = "t", lignes)
  })

  output$fiche <- renderUI({
    z <- zone()
    if (is.na(z)) return(NULL)
    k <- h()
    m <- mode()
    f <- A$zones[z, ]
    brut <- c(paste0("houle locale ", fr1(A$HSL[k, z] / 50), " m"), if (isTRUE(M$current_proxy)) "vitesse de la marée" else paste0("courant ", fr1(A$CUR[k, z] / 100), " m/s"), "", "")
    facteurs <- lapply(1:4, function(i) {
      tags$tr(tags$td(c("Agitation", "Courant", "Lumière", "Eau")[i]), tags$td(div(class = "jauge", tags$i(style = paste0("width:", A$COMP[k, z, i], "%"))), if (nzchar(brut[i])) div(class = "gris", brut[i])))
    })
    d0 <- debut_jour(k)
    barres <- lapply(1:24, function(i) {
      c <- d0 + i
      v <- valeurs[[m]][c, z]
      haut <- max(6, min(100, round(100 * (v - bornes[[m]][1]) / diff(bornes[[m]]))))
      div(class = if (c == k) "now", title = paste0(i - 1, " h : ", unite(v, m)), onclick = clic("aller", c), style = sprintf("height:%d%%;background:%s", haut, couleur(v, m)))
    })
    creneaux <- lapply(meilleurs_creneaux(z), function(c) {
      tags$li(tags$a(href = "#", onclick = paste0(clic("aller", c), "; return false;"), sprintf("%s, %d h (indice %d)", jour_nom(c), heure_de(c), A$S[c, z])))
    })
    div(class = "fiche",
      div(class = "entete", strong(f$name), actionLink("fermer", "fermer")),
      div(class = "gris", sprintf("Face %s, %s, %s ha", f$facing, f$exposure, fr1(f$area_m2 / 1e4))),
      p(sprintf("Indice %d, chances %d %%", A$S[k, z], A$P[k, z])),
      tags$table(class = "t", facteurs),
      div(class = "gris", style = "margin-top:8px", paste("Le", jour_nom(k))),
      div(class = "profil", barres),
      div(class = "axe", span("0 h"), span("6 h"), span("12 h"), span("18 h"), span("23 h")),
      div(class = "gris", style = "margin-top:8px", "Meilleurs créneaux de la période"),
      tags$ul(style = "margin:4px 0; padding-left:18px", creneaux)
    )
  })

  output$conditions <- renderUI({
    k <- h()
    w <- A$heures[k, ]
    ligne <- function(nom, texte, detail = "") {
      tags$tr(tags$td(class = "gris", nom), tags$td(texte, if (nzchar(detail)) div(class = "gris", detail)))
    }
    ma <- texte_maree(k)
    lu <- texte_lumiere(k)
    tags$table(class = "t",
      ligne("Marée", ma[1], ma[2]),
      ligne("Lumière", lu[1], lu[2]),
      ligne("Vent habituel", if (is.na(w$wind)) "n. d." else paste0(w$wind_dir, ", ", fr1(w$wind), " m/s"), if (is.na(w$wind)) "" else sprintf("direction dominante dans %d %% des tirages", round(w$wind_share * 100))),
      ligne("Houle au large", paste(fr1(w$hs), "m"), if (is.na(w$tp)) "" else paste("période", fr1(w$tp), "s")),
      ligne("Eau", paste(fr1(w$sst), "°C"))
    )
  })

  output$courbe_maree <- renderPlot({
    k <- h()
    y <- A$maree$eta[debut_jour(k) + 1:24]
    par(mar = c(0, 0, 0, 0), family = "sans")
    plot(0:23, y, type = "l", lwd = 1.5, axes = FALSE, ann = FALSE, ylim = c(-1, 1) * max(abs(A$maree$eta)))
    abline(h = 0, col = "grey80")
    abline(v = heure_de(k), col = ROSE)
    points(heure_de(k), A$maree$eta[k], pch = 19, col = ROSE)
  }, res = 96)

  output$cal_titre <- renderUI({
    z <- zone()
    m <- mode()
    titre <- if (is.na(z)) "Meilleure zone de chaque heure" else paste(A$zones$name[z], "heure par heure")
    span(tags$b(titre), " ", if (m == "S") "indice" else "chances", " ", unite(bornes[[m]][1], m), span(class = "legende"), unite(bornes[[m]][2], m), " ; rond blanc : pleine mer, pointillés : lever et coucher du soleil")
  })

  valeur_cal <- reactive({
    z <- zone()
    if (is.na(z)) max_heure[[mode()]] else valeurs[[mode()]][, z]
  })

  output$survol <- renderText({
    p <- input$cal_survol
    if (is.null(p)) return("")
    d <- floor(p$x)
    k <- floor(p$y)
    if (d < 0 || d >= NJ || k < 0 || k > 23) return("")
    c <- d * 24 + k + 1
    paste0(jour_nom(c, TRUE), ", ", k, " h : ", unite(valeur_cal()[c], mode()))
  })

  output$calendrier <- renderPlot({
    m <- mode()
    v <- valeur_cal()
    i <- seq_len(H) - 1
    par(mar = c(0.3, 2.4, 2.2, 0.3), family = "sans", xaxs = "i", yaxs = "i")
    plot.new()
    plot.window(xlim = c(0, NJ), ylim = c(24, 0))
    rect(i %/% 24, i %% 24, i %/% 24 + 1, i %% 24 + 1, col = couleur(v, m), border = "white", lwd = 0.4)

    premiers <- seq(1, H, 24)
    wd <- as.integer(format(t_h[premiers], "%w"))
    x <- seq_len(NJ) - 0.5
    num <- as.integer(format(t_h[premiers], "%d"))
    if (NJ <= 40) {
      mtext(toupper(substr(JOURS[wd + 1], 1, 1)), 3, at = x, line = 1, cex = 0.7, font = ifelse(wd %in% c(0, 6), 2, 1))
      mtext(num, 3, at = x, line = 0.15, cex = 0.7)
    } else {
      # trop de jours pour tout écrire : les lundis et le début de chaque mois
      lundis <- wd == 1
      mtext(num[lundis], 3, at = x[lundis], line = 0.15, cex = 0.7)
      mois <- which(num == 1 | seq_len(NJ) == 1)
      mtext(MOIS[as.integer(format(t_h[premiers[mois]], "%m"))], 3, at = mois - 1, adj = 0, line = 1, cex = 0.7, font = 2)
      abline(v = mois[-1] - 1, col = "grey15", lwd = 1.2)
    }
    mtext(paste(c(0, 6, 12, 18), "h"), 2, at = c(0, 6, 12, 18) + 0.5, las = 1, line = 0.3, cex = 0.7)

    for (d in seq_len(NJ)) {
      s <- A$soleil[[format(t_h[premiers[d]], "%Y-%m-%d")]]
      if (is.null(s)) next
      y <- sapply(strsplit(s, ":"), function(u) as.numeric(u[1]) + as.numeric(u[2]) / 60)
      segments(d - 1, y, d, y, lty = 3, col = "grey15")
    }
    pm <- as.numeric(difftime(t_ev[A$maree$events$kind == "PM"], t_h[1], units = "hours"))
    pm <- pm[pm >= 0 & pm < H]
    points(pm %/% 24 + 0.5, pm %% 24, pch = 21, bg = "white", cex = 0.65)

    k <- h() - 1
    rect(k %/% 24, k %% 24, k %/% 24 + 1, k %% 24 + 1, border = ROSE, lwd = 2.5)
  }, res = 96)

  observeEvent(input$aide, showModal(modalDialog(
    title = "Lire la carte", easyClose = TRUE, footer = modalButton("Fermer"),
    p("Chaque zone est un morceau de la bande de mer de 120 m au pied de la côte rocheuse (plages et ports exclus), à portée de lancer. Sa couleur dit si l'heure affichée est favorable au bar : clair = peu, foncé = beaucoup."),
    p(sprintf("Marée, courants et lumière sont calculés pour %d. Vent, houle et température de l'eau sont rejoués à partir de la météo observée à la même date, à %d jours près, de %d à %d (environ %d tirages par heure).", M$year, M$pool_days, M$years[1], M$years[2], M$samples_median)),
    p(strong("Indice"), " : note moyenne de la zone sur ces tirages, de 0 à 100. ", strong("Chances"), " : part des tirages où la zone finit dans le meilleur cinquième."),
    p("Quatre facteurs : agitation (ressac ou clapot porté vers la zone), courant de marée, lumière (aube et crépuscule au plus haut), température de l'eau (pénalisée au-dessus de 19,5 °C)."),
    p("Les poids viennent de la lecture d'articles, pas de prises réelles. Houle et courants sortent d'un modèle à mailles de 2 à 3 km. Le jour même, une prévision à trois jours vaut mieux que cette carte."),
    p(sprintf("Règles 2026 au sud du 48e parallèle : deux bars par pêcheur et par jour, 42 cm minimum. À vérifier pour %d.", M$year)),
    p(class = "gris", sprintf("Houle : %s (Copernicus Marine). Marée et courants : analyse harmonique IBI 1/36° (M2 %s m, S2 %s m). Vent : ERA5. Eau : OSTIA. Côte, plages et ports : OpenStreetMap. Limite communale : geo.api.gouv.fr. Fond de carte : IGN ou Esri. Données : %s, calculées le %s.", M$wave_source, fr1(M$M2), fr1(M$S2), basename(A$source), A$maj))
  )))
}

shinyApp(ui, server)
