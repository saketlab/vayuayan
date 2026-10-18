# Regenerates man/figures/logo.png: annual mean satellite PM2.5 (WUSTL
# V6.GL.03) over India on a coarse grid, with a wind and particle glyph above
# Nepal. Same house style as varunayan and thali.
# Usage (from R/): Rscript data-raw/logo.R
library(ggplot2)
library(sf)
library(hexSticker)
devtools::load_all(quiet = TRUE)

sysfonts::font_add_google("Albert Sans", "albert", regular.wt = 700)
showtext::showtext_auto()

year <- 2024
navy <- "#0B1D33"
ink <- "#EEF2F8"

# official LGD boundary, islands included
lgd_url <- "https://geo.bharatviz.org/geojsons/admin/India-geodata-lgd-states.geojson"
sf_use_s2(FALSE)
india <- st_union(st_make_valid(st_read(lgd_url, quiet = TRUE)))
parts <- st_cast(india, "POLYGON")
# exterior rings drop district sliver holes; tiny islands stay unsimplified
parts <- st_sfc(lapply(parts, function(p) st_polygon(p[1])), crs = 4326)
big <- as.numeric(st_area(st_transform(parts, 7755))) > 5e8
parts[big] <- st_simplify(parts[big], dTolerance = 0.05)
india <- st_union(parts)

# mean PM2.5 per grid cell; rank scaling so the map spans the whole palette
nc <- pm25_download_netcdf(year, region = "AS")
pm25 <- terra::crop(terra::rast(nc), terra::ext(66, 99, 5, 38))
cells <- st_make_grid(india, cellsize = 0.6, square = TRUE)
cells <- cells[lengths(st_intersects(cells, india)) > 0]
pm <- terra::extract(pm25, terra::vect(cells), fun = mean, na.rm = TRUE)[[2]]
# ColorBrewer RdYlBu without its darkest blue
pal <- grDevices::colorRampPalette(c(
  "#4575B4", "#74ADD1", "#ABD9E9", "#E0F3F8", "#FFFFBF",
  "#FEE090", "#FDAE61", "#F46D43", "#D73027", "#A50026"
))(100)
grid <- st_sf(fill = pal[1 + round(99 * (rank(pm) - 1) / (length(pm) - 1))], geometry = cells)
grid <- grid[!is.na(pm), ]

# wind gust: a line from (x0, y) ending in a curl of radius r, curling up or down
gust <- function(x0, y, len, r, up = TRUE, id = 1) {
  s <- if (up) 1 else -1
  t <- seq(pi / 2, -pi, length.out = 60)
  cx <- x0 + len
  data.frame(
    x = c(x0, cx, cx + r * cos(t)),
    y = c(y, y, y + s * r - s * r * sin(t)),
    id = id
  )
}
wind <- rbind(
  gust(82.7, 35.7, 6.3, 1.25, up = TRUE, id = 1),
  gust(84.4, 33.2, 7.3, 1.0, up = FALSE, id = 2),
  gust(82.3, 31.1, 4.6, 0.8, up = FALSE, id = 3)
)
# particulate dots drifting off the gusts
dust <- data.frame(
  x = c(91.1, 93.8, 88.6, 94.9, 90.7),
  y = c(34.4, 34.1, 32.0, 31.9, 29.9),
  s = c(0.32, 0.24, 0.28, 0.2, 0.22)
)

p <- ggplot() +
  geom_sf(data = grid, aes(fill = I(fill)), colour = navy, linewidth = 0.08) +
  geom_sf(data = india, fill = NA, colour = ink, linewidth = 0.18) +
  geom_path(data = wind, aes(x, y, group = id), colour = ink, linewidth = 0.55, lineend = "round") +
  geom_point(data = dust, aes(x, y, size = I(s)), colour = ink) +
  coord_sf(xlim = c(67.5, 98), ylim = c(6.2, 38.6), expand = FALSE, datum = NA) +
  theme_void() +
  theme_transparent()

sticker(
  p,
  package = "vayuayan",
  p_family = "albert", p_fontface = "bold", p_size = 21,
  p_color = ink, p_y = 0.42,
  s_x = 1, s_y = 1.14, s_width = 1.24, s_height = 1.24,
  h_fill = navy, h_color = "#E8562A", h_size = 1.4,
  dpi = 600,
  filename = "man/figures/logo.png"
)

# hexSticker centres the hex unevenly; trim and pad equally
logo <- magick::image_trim(magick::image_read("man/figures/logo.png"))
logo <- magick::image_border(logo, "transparent", "12x12")
magick::image_write(logo, "man/figures/logo.png")
