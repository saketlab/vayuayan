#!/usr/bin/env python3
"""Dump CPCB raw 15-minute pollutant observations to sorted parquet.

The script does these steps:

1. Download the raw 15-minute CSV files of each CPCB station.
2. Convert each wide CSV to a long pollutant table.
3. Keep one parquet shard for each station-year in the cache.
4. Write one sorted parquet for each station.
5. Use DuckDB to write a final parquet, sorted by:

    year, date, time, station_name, station_id, city, pollutant_name

You can stop the script and run it again. On the next run, the script skips
the station-year shards, the station parquet files, and the `.empty` markers
that exist.

Examples:

    # Full run, from the year 2000 to the current year.
    python scripts/dump_raw_15min_pollutants.py \
        --out data/cpcb_raw_15min_pollutants.parquet \
        --cache data/cpcb_raw_15min_cache \
        --station-out-dir data/cpcb_raw_15min_station_parquet

    # Smoke test for one station and a range of dates.
    python scripts/dump_raw_15min_pollutants.py \
        --station-id site_301 --start-year 2025 --end-year 2025 \
        --start-date 2025-01-01 --end-date 2025-05-31 \
        --out /tmp/site_301_15min.parquet --cache /tmp/site_301_15min_cache \
        --station-out-dir /tmp/site_301_15min_stations

The script uses pyarrow and duckdb to write parquet and to do the final sort.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import duckdb
import pandas as pd
import pyarrow.parquet as pq

from vayuayan import CPCBHistorical
from vayuayan.exceptions import DataNotFoundError
from vayuayan.tidy import cpcb_raw_to_long

SORT_COLUMNS = [
    "year",
    "date",
    "time",
    "station_name",
    "station_id",
    "city",
    "pollutant_name",
]

OUTPUT_COLUMNS = [
    "year",
    "date",
    "time",
    "timestamp",
    "station_name",
    "station_id",
    "city",
    "state",
    "pollutant_name",
    "pollutant_unit",
    "value",
]


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_") or "unknown"


def normalize_raw_csv(
    df: pd.DataFrame,
    station: dict,
    requested_year: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    # Keep only the requested calendar year. Some files have rows of the next year.
    first, last = date(requested_year, 1, 1), date(requested_year, 12, 31)
    long = cpcb_raw_to_long(
        df,
        station,
        max(start_date, first) if start_date else first,
        min(end_date, last) if end_date else last,
    )
    ts = long["timestamp"]
    # Each timestamp repeats once per pollutant, so format only the unique ones
    uniq = ts.drop_duplicates()
    long = long.rename(
        columns={"pollutant": "pollutant_name", "unit": "pollutant_unit"}
    ).assign(
        year=ts.dt.year.astype("int16"),
        date=ts.dt.date,
        time=ts.map(dict(zip(uniq, uniq.dt.strftime("%H:%M:%S")))),
    )[OUTPUT_COLUMNS]
    return long.sort_values(SORT_COLUMNS, kind="stable").reset_index(drop=True)


def iter_master_stations(
    client: CPCBHistorical,
    state_filter: str | None = None,
    city_filter: str | None = None,
    station_ids: set[str] | None = None,
) -> Iterable[dict]:
    for state, city, station in client.iter_stations(
        state=state_filter or "", city=city_filter or ""
    ):
        city_name = str(city.get("city_name", ""))
        city_code = str(city.get("city_code", ""))
        station_id = str(station.get("station_id", ""))
        if station_ids and station_id not in station_ids:
            continue
        yield {
            "station_id": station_id,
            "station_name": str(station.get("station_name", "")),
            "city": str(station.get("city", city_name)),
            "state": str(station.get("state", state.get("state_name", ""))),
            "city_code": city_code,
            "state_code": str(state.get("state_code", "")),
            "latitude": station.get("latitude"),
            "longitude": station.get("longitude"),
        }


def shard_paths(
    cache: Path,
    station_id: str,
    year: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[Path, Path]:
    station_dir = cache / safe_name(station_id)
    suffix = str(year)
    if start_date is not None or end_date is not None:
        start_label = start_date.isoformat() if start_date is not None else "start"
        end_label = end_date.isoformat() if end_date is not None else "end"
        suffix = f"{year}_{start_label}_to_{end_label}"
    return station_dir / f"{suffix}.parquet", station_dir / f"{suffix}.empty"


def dump_station_year(
    client: CPCBHistorical,
    station: dict,
    year: int,
    cache: Path,
    overwrite: bool = False,
    start_date: date | None = None,
    end_date: date | None = None,
) -> str:
    shard, empty_marker = shard_paths(
        cache, station["station_id"], year, start_date, end_date
    )
    if not overwrite and shard.exists():
        return "cached"
    if not overwrite and empty_marker.exists():
        return "empty-cached"

    shard.parent.mkdir(parents=True, exist_ok=True)
    # A NetworkError propagates, so an outage never writes an .empty marker
    try:
        raw = client.download_raw_aqi_data_station_level(
            station["station_id"],
            str(year),
            "",
            frequency="15_minute",
            station_name=station["station_name"],
            city=station["city"],
            state=station["state"],
        )
    except DataNotFoundError:
        empty_marker.touch()
        return "empty"
    long = normalize_raw_csv(raw, station, year, start_date, end_date)
    if long.empty:
        empty_marker.touch()
        return "empty"

    long.to_parquet(shard, index=False)
    empty_marker.unlink(missing_ok=True)
    return f"written:{len(long)}"


def collect_parquet_files(root: Path) -> list[str]:
    return sorted(
        str(p) for p in list(root.glob("*.parquet")) + list(root.glob("*/*.parquet"))
    )


def _prepare_tmp_out(inputs: list[str], out: Path) -> Path:
    if not inputs:
        raise RuntimeError("No input parquet files provided")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = out.with_name(f"{out.name}.tmp")
    tmp_out.unlink(missing_ok=True)
    return tmp_out


def _register_raw_view(
    con: duckdb.DuckDBPyConnection,
    inputs: list[str],
    temp_dir: Path | None,
    memory_limit: str | None,
) -> None:
    con.execute("SET preserve_insertion_order=false")
    # The merge queries the same files once per month; keep their footers cached
    con.execute("SET parquet_metadata_cache=true")
    if temp_dir is not None:
        temp_dir.mkdir(parents=True, exist_ok=True)
        con.execute("SET temp_directory=$1", [str(temp_dir)])
    if memory_limit:
        con.execute("SET memory_limit=$1", [memory_limit])
    con.read_parquet(inputs, union_by_name=True).create_view("raw_15min")


def write_sorted_parquet(
    inputs: list[str],
    out: Path,
    temp_dir: Path | None = None,
    memory_limit: str | None = None,
) -> None:
    tmp_out = _prepare_tmp_out(inputs, out)

    con = duckdb.connect()
    try:
        _register_raw_view(con, inputs, temp_dir, memory_limit)
        con.execute(
            f"""
            COPY (
                SELECT {", ".join(OUTPUT_COLUMNS)}
                FROM raw_15min
                ORDER BY {", ".join(SORT_COLUMNS)}
            ) TO $1 (FORMAT PARQUET, COMPRESSION ZSTD)
            """,
            [str(tmp_out)],
        )
    finally:
        con.close()

    tmp_out.replace(out)


def write_sorted_parquet_by_month(
    inputs: list[str],
    out: Path,
    temp_dir: Path | None = None,
    memory_limit: str | None = None,
) -> None:
    tmp_out = _prepare_tmp_out(inputs, out)

    con = duckdb.connect()
    writer: pq.ParquetWriter | None = None
    try:
        _register_raw_view(con, inputs, temp_dir, memory_limit)
        # One sort per month keeps each sort small without one query per day
        months = con.execute(
            "SELECT DISTINCT year, month(date) AS m FROM raw_15min ORDER BY year, m"
        ).fetchall()
        for year, month in months:
            start = date(int(year), int(month), 1)
            end = date(start.year + start.month // 12, start.month % 12 + 1, 1)
            # A date range, not month(date), so DuckDB skips row groups by date
            reader = con.execute(
                f"""
                SELECT {", ".join(OUTPUT_COLUMNS)}
                FROM raw_15min
                WHERE date >= $1 AND date < $2
                ORDER BY {", ".join(SORT_COLUMNS)}
                """,
                [start, end],
            ).fetch_record_batch(rows_per_batch=131072)
            for batch in reader:
                if writer is None:
                    writer = pq.ParquetWriter(tmp_out, batch.schema, compression="zstd")
                writer.write_batch(batch)
    finally:
        if writer is not None:
            writer.close()
        con.close()

    if writer is None:
        raise RuntimeError("No rows found in input parquet files")
    tmp_out.replace(out)


def station_parquet_path(station_out_dir: Path, station_id: str) -> Path:
    return station_out_dir / f"{safe_name(station_id)}.parquet"


def build_station_parquet(
    cache: Path,
    station_out_dir: Path,
    station_id: str,
    overwrite: bool = False,
    temp_dir: Path | None = None,
    memory_limit: str | None = None,
) -> str:
    out = station_parquet_path(station_out_dir, station_id)
    if out.exists() and not overwrite:
        return "cached"

    station_cache = cache / safe_name(station_id)
    shards = sorted(str(p) for p in station_cache.glob("*.parquet"))
    if not shards:
        return "empty"

    write_sorted_parquet(shards, out, temp_dir, memory_limit)
    return f"written:{len(shards)} shards"


def finalize_sorted_parquet(
    input_dir: Path,
    out: Path,
    temp_dir: Path | None = None,
    memory_limit: str | None = None,
    by_month: bool = True,
) -> None:
    shards = collect_parquet_files(input_dir)
    if not shards:
        raise RuntimeError(f"No parquet files found under {input_dir}")
    if by_month:
        write_sorted_parquet_by_month(shards, out, temp_dir, memory_limit)
    else:
        write_sorted_parquet(shards, out, temp_dir, memory_limit)


def parse_date_arg(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/cpcb_raw_15min_pollutants.parquet")
    parser.add_argument("--cache", default="data/cpcb_raw_15min_cache")
    parser.add_argument(
        "--station-out-dir",
        default="data/cpcb_raw_15min_station_parquet",
        help="Directory for one sorted parquet per station",
    )
    parser.add_argument(
        "--duckdb-temp-dir",
        default="data/.duckdb_tmp",
        help="DuckDB spill directory for station/global sorts",
    )
    parser.add_argument(
        "--duckdb-memory-limit",
        default="4GB",
        help="DuckDB memory limit for external sorting",
    )
    parser.add_argument(
        "--global-final-sort",
        action="store_true",
        help="Use one global sort for final merge instead of lower-spill month-by-month merge",
    )
    parser.add_argument("--start-year", type=int, default=2000)
    parser.add_argument("--end-year", type=int, default=date.today().year)
    parser.add_argument(
        "--start-date", type=parse_date_arg, help="Optional inclusive YYYY-MM-DD filter"
    )
    parser.add_argument(
        "--end-date", type=parse_date_arg, help="Optional inclusive YYYY-MM-DD filter"
    )
    parser.add_argument("--state", help="Optional state name/code filter")
    parser.add_argument("--city", help="Optional city name/code filter")
    parser.add_argument(
        "--station-id",
        action="append",
        help="Optional station id filter. Repeat for multiple stations.",
    )
    parser.add_argument("--limit-stations", type=int, help="Optional station limit")
    parser.add_argument(
        "--sleep", type=float, default=0.2, help="Delay between downloads"
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="Re-download existing shards"
    )
    parser.add_argument(
        "--skip-download", action="store_true", help="Only finalize cached shards"
    )
    parser.add_argument(
        "--skip-station-parquet",
        action="store_true",
        help="Do not build per-station parquet files",
    )
    parser.add_argument(
        "--overwrite-station-parquet",
        action="store_true",
        help="Rebuild existing per-station parquet files",
    )
    parser.add_argument(
        "--skip-final", action="store_true", help="Only download/cache shards/stations"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cache = Path(args.cache)
    station_out_dir = Path(args.station_out_dir)
    duckdb_temp_dir = Path(args.duckdb_temp_dir) if args.duckdb_temp_dir else None
    out = Path(args.out)
    # The parquet shards are the cache of this script; do not fill ~/.cache too
    client = CPCBHistorical(use_cache=False)

    if args.start_year > args.end_year:
        raise SystemExit("--start-year must be <= --end-year")
    if args.start_date and args.end_date and args.start_date > args.end_date:
        raise SystemExit("--start-date must be <= --end-date")

    stations = []
    if not args.skip_download or not args.skip_station_parquet:
        station_ids = set(args.station_id or []) or None
        stations = list(
            iter_master_stations(client, args.state, args.city, station_ids)
        )
        if args.limit_stations is not None:
            stations = stations[: args.limit_stations]

    if not args.skip_download:
        print(
            f"{len(stations)} stations | years {args.start_year}-{args.end_year} | cache {cache}",
            flush=True,
        )

    total = len(stations) * (args.end_year - args.start_year + 1)
    n = 0
    for station in stations:
        if not args.skip_download:
            for year in range(args.start_year, args.end_year + 1):
                n += 1
                prefix = f"[{n}/{total}] {station['station_id']} {station['station_name']} {year}"
                status = "failed"
                try:
                    status = dump_station_year(
                        client,
                        station,
                        year,
                        cache,
                        args.overwrite,
                        args.start_date,
                        args.end_date,
                    )
                    print(f"{prefix}: {status}", flush=True)
                except Exception as exc:
                    print(f"{prefix}: failed: {exc}", file=sys.stderr, flush=True)
                if status not in {"cached", "empty-cached"}:
                    time.sleep(args.sleep)

        if not args.skip_station_parquet:
            try:
                status = build_station_parquet(
                    cache,
                    station_out_dir,
                    station["station_id"],
                    args.overwrite_station_parquet,
                    duckdb_temp_dir,
                    args.duckdb_memory_limit,
                )
                print(f"station {station['station_id']}: {status}", flush=True)
            except Exception as exc:
                print(
                    f"station {station['station_id']}: failed: {exc}",
                    file=sys.stderr,
                    flush=True,
                )

    final_input_dir = station_out_dir
    if args.skip_station_parquet and not collect_parquet_files(station_out_dir):
        final_input_dir = cache
    if not args.skip_final:
        if not collect_parquet_files(final_input_dir):
            print(
                f"no parquet written: no parquet files under {final_input_dir}",
                file=sys.stderr,
                flush=True,
            )
            return
        print(f"writing sorted parquet -> {out}", flush=True)
        finalize_sorted_parquet(
            final_input_dir,
            out,
            duckdb_temp_dir,
            args.duckdb_memory_limit,
            by_month=not args.global_final_sort,
        )
        print(f"wrote {out}", flush=True)


if __name__ == "__main__":
    main()
