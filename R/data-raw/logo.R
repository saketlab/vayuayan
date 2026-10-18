# Adds the wind and particle symbol above Nepal to the hex logo.
# Input is the logo without the symbol, kept in git:
#   git show 58bfe84:man/figures/logo.png > logo_base.png
#   Rscript data-raw/logo.R logo_base.png man/figures/logo.png
# Running it on the current logo draws the symbol twice.
library(magick)
args <- commandArgs(TRUE)
img <- image_read(args[1])
out <- image_draw(img)
col <- "#EEF2F8"
# wind gust: a line ending in a curl, (x0, y) start, length len, curl radius r, curl up or down
gust <- function(x0, y, len, r, up = TRUE, lwd = 9) {
  s <- if (up) -1 else 1
  t <- seq(pi / 2, -pi, length.out = 60)
  cx <- x0 + len
  cy <- y + s * r
  xs <- c(x0, cx, cx + r * cos(t))
  ys <- c(y, y, cy - s * r * sin(t))
  lines(xs, ys, col = col, lwd = lwd, lend = "round", ljoin = "round")
}
gust(600, 250, 150, 32, up = TRUE)
gust(640, 315, 175, 26, up = FALSE)
gust(590, 370, 110, 20, up = FALSE)
# particulate dots drifting off the gusts
pm <- data.frame(
  x = c(800, 865, 740, 890, 790),
  y = c(282, 290, 345, 348, 400),
  r = c(3.2, 2.4, 2.8, 2, 2.2)
)
symbols(pm$x, pm$y, circles = pm$r, inches = FALSE, add = TRUE, bg = col, fg = NA)
dev.off()
image_write(out, args[2])

