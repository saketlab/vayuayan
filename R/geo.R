.bharatviz_districts_url <-
  "https://geo.bharatviz.org/geojsons/districts/India_LGD_districts.geojson"

#' Boundary of Indian districts or states
#'
#' @description
#' Union of BharatViz LGD district polygons, selected by district or state
#' name. The district layer is downloaded once per session.
#'
#' @param district Character vector of district names (column
#'   \code{district_name}).
#' @param state Character vector of state names (column \code{state_name}).
#'   Used when \code{district} is \code{NULL}.
#' @return An \code{sfc} polygon in EPSG:4326.
#' @source \url{https://geo.bharatviz.org/geojsons/districts/India_LGD_districts.geojson}
#' @examplesIf interactive()
#' mumbai <- india_boundary(district = c("Mumbai", "Mumbai Suburban"))
#' delhi <- india_boundary(state = "Delhi")
#' @export
india_boundary <- function(district = NULL, state = NULL) {
  if (is.null(district) && is.null(state)) {
    stop("Supply district or state.", call. = FALSE)
  }
  if (is.null(.cpcb_cache$districts)) {
    .cpcb_cache$districts <- sf::st_read(.bharatviz_districts_url, quiet = TRUE) %>%
      sf::st_make_valid() %>%
      sf::st_transform(4326)
  }
  districts <- .cpcb_cache$districts
  sel <- if (!is.null(district)) {
    districts$district_name %in% district
  } else {
    districts$state_name %in% state
  }
  if (!any(sel)) {
    stop("No BharatViz district matches the selection.", call. = FALSE)
  }
  sf::st_union(sf::st_make_valid(districts[sel, ]))
}

#' Map a PM2.5 raster
#'
#' @description
#' Plot a PM2.5 raster with an optional boundary outline. The color scale
#' spans the 2nd to 98th percentile of the raster so that outliers do not
#' wash out the map.
#'
#' @param r A \code{terra} \code{SpatRaster}, for example from
#'   \code{pm25_load_netcdf_bbox()}.
#' @param boundary Optional \code{sf} or \code{sfc} outline to draw on top.
#' @param title Optional plot title.
#' @return A \code{ggplot} object. The subtitle gives the raster mean.
#' @examplesIf interactive()
#' shape <- india_boundary(state = "Delhi")
#' r <- pm25_load_netcdf_bbox(pm25_v5gl04_path(2022, 11, "."), shape, mask = TRUE)
#' pm25_map(r, shape, title = "Delhi")
#' @export
pm25_map <- function(r, boundary = NULL, title = NULL) {
  for (pkg in c("ggplot2", "tidyterra")) {
    if (!requireNamespace(pkg, quietly = TRUE)) {
      stop(sprintf("Package '%s' is required for pm25_map().", pkg), call. = FALSE)
    }
  }
  vals <- terra::values(r, na.rm = TRUE)
  limits <- c(
    floor(stats::quantile(vals, 0.02)),
    ceiling(stats::quantile(vals, 0.98))
  )

  p <- ggplot2::ggplot() +
    tidyterra::geom_spatraster(data = r) +
    ggplot2::scale_fill_distiller(
      palette = "YlOrRd", direction = 1, limits = limits,
      oob = .squish, na.value = NA,
      name = expression(paste(mu, "g/m"^3))
    ) +
    ggplot2::labs(
      title = title,
      subtitle = sprintf("Mean: %.1f \u00b5g/m\u00b3", mean(vals)),
      x = NULL, y = NULL
    ) +
    ggplot2::theme_minimal(base_size = 10) +
    ggplot2::theme(
      panel.grid = ggplot2::element_blank(),
      plot.title = ggplot2::element_text(face = "bold", hjust = 0.5),
      plot.subtitle = ggplot2::element_text(hjust = 0.5, color = "grey40")
    )
  if (!is.null(boundary)) {
    p <- p + ggplot2::geom_sf(
      data = sf::st_as_sf(boundary), fill = NA,
      color = "grey20", linewidth = 0.5
    )
  }
  p
}

# scales::squish without a scales dependency; keeps NA
.squish <- function(x, range = c(0, 1), only.finite = TRUE) {
  pmin(pmax(x, range[1]), range[2])
}
