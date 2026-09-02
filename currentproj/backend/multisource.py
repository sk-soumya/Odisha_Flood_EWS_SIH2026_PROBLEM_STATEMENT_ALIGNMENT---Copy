"""
Multi-source precipitation adapters for Odisha Flood EWS.

Supports:
- NASA GPM IMERG local NetCDF4 daily files (.nc4) and GeoTIFF rasters.
- Optional NASA PMM/JSON upstream point rainfall adapters.
- RainViewer metadata for radar visualization/health.
- Optional configured numeric radar JSON feed.

The adapter never converts radar image colours into rainfall millimetres.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

MODULE_DIR = Path(__file__).resolve().parent
TIMEOUT = float(os.getenv("EWS_SOURCE_TIMEOUT", "12"))

RAINVIEWER_METADATA_URL = os.getenv(
    "EWS_RADAR_METADATA_URL",
    "https://api.rainviewer.com/public/weather-maps.json",
).strip()

SATELLITE_FILE = os.getenv("EWS_SATELLITE_GPM_FILE", "").strip()
SATELLITE_DIR = os.getenv("EWS_SATELLITE_GPM_DIR", "./data/imerg_daily").strip()
SATELLITE_JSON_URL = os.getenv("EWS_SATELLITE_JSON_URL", "").strip()
RADAR_FEED_URL = os.getenv("EWS_RADAR_FEED_URL", "").strip()
RADAR_METADATA_ONLY = os.getenv("EWS_RADAR_METADATA_ONLY", "true").strip().lower() == "true"
SATELLITE_PMM_ENABLED = os.getenv("EWS_SATELLITE_PMM_ENABLED", "true").strip().lower() == "true"
NASA_PMM_URL = os.getenv("EWS_SATELLITE_PMM_URL", "https://pmmpublisher.pps.eosdis.nasa.gov/opensearch").strip()
PMM_LAST_ERROR = None


def _resolve(path_text: str) -> Path:
    p = Path(path_text)
    return p if p.is_absolute() else MODULE_DIR / p


def _num(payload: Dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = payload.get(key)
        try:
            x = float(value)
            if math.isfinite(x):
                return x
        except (TypeError, ValueError):
            pass
    return None


async def fetch_json(url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not url:
        return {}
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=True,
            headers={
                "User-Agent": "Odisha-Flood-EWS/1.0",
                "Accept": "application/activity+json, application/json, */*",
            },
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            try:
                payload = response.json()
            except Exception:
                # PMM may return structured JSON with an alternate content-type.
                payload = json.loads(response.text)
            return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        return {"_error": str(exc)}


async def radar_status() -> Dict[str, Any]:
    payload = await fetch_json(RAINVIEWER_METADATA_URL)
    frames = []
    if isinstance(payload, dict):
        radar = payload.get("radar") or {}
        frames = list(radar.get("past") or []) + list(radar.get("nowcast") or [])
    return {
        "available": bool(frames),
        "provider": "RainViewer",
        "metadata_url": RAINVIEWER_METADATA_URL,
        "frame_count": len(frames),
        "latest_frame_time": frames[-1].get("time") if frames else None,
        "numeric_rainfall_available": False,
        "note": (
            "RainViewer public API supplies radar map/timeline metadata; "
            "this adapter does not infer mm rainfall from image colours."
        ),
        "error": payload.get("_error") if isinstance(payload, dict) else None,
    }


async def _pmm_latest_asset(latitude: float = 20.3, longitude: float = 85.8) -> Dict[str, Any]:
    global PMM_LAST_ERROR
    PMM_LAST_ERROR = None
    """Discover a recent NASA GPM IMERG GeoTIFF through PMM Publisher.

    The PMM Publisher API documents both Early 1-day (precip_30mn_1d) and
    Late 1-day (precip_1d). Availability can lag UTC date boundaries, so the
    adapter tries each of the latest three dates individually and accepts
    either direct TIFF URLs or the documented download action structure.
    """
    if not SATELLITE_PMM_ENABLED:
        return {}

    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone.utc).date()

    def collect_urls(obj: Any) -> list[str]:
        found: list[str] = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                kl = str(k).lower()
                if isinstance(v, str) and v.startswith("http"):
                    vl = v.lower()
                    if (
                        vl.endswith((".tif", ".tiff", ".tif?", ".tiff?"))
                        or "geotiff" in kl
                        or "downloadurl" in kl
                    ):
                        found.append(v)
                else:
                    found.extend(collect_urls(v))
        elif isinstance(obj, list):
            for item in obj:
                found.extend(collect_urls(item))
        return list(dict.fromkeys(found))

    def prop_value(props: Dict[str, Any], name: str):
        value = props.get(name)
        return value.get("@value") if isinstance(value, dict) else value

    for day_offset in range(0, 4):
        day = today - timedelta(days=day_offset)
        day_text = day.isoformat()
        for q in ("precip_30mn_1d", "precip_1d"):
            payload = await fetch_json(
                NASA_PMM_URL,
                params={
                    "q": q,
                    "lat": latitude,
                    "lon": longitude,
                    "limit": 10,
                    "startTime": day_text,
                    "endTime": day_text,
                },
            )
            if payload.get("_error"):
                PMM_LAST_ERROR = str(payload.get("_error"))
                continue

            items = payload.get("items") or []
            for item in items:
                downloads = collect_urls(item)
                for url in downloads:
                    if ".tif" in url.lower() or ".tiff" in url.lower():
                        props = item.get("properties") or {}
                        return {
                            "dataset": item.get("displayName") or item.get("@id"),
                            "date": prop_value(props, "date") or day.strftime("%Y%m%d"),
                            "download_url": url,
                            "source": "NASA GSFC GPM IMERG",
                            "resolution": prop_value(props, "resolution") or "0.1deg",
                            "query": q,
                        }
    return {}



def _finite_mm(value: Any) -> Optional[float]:
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _nc4_rainfall_at(path: Path, latitude: float, longitude: float) -> float:
    """Read IMERG daily precipitation robustly for any lat/lon axis order."""
    import netCDF4  # type: ignore
    import numpy as np  # type: ignore

    with netCDF4.Dataset(path) as ds:
        lon_var = ds.variables.get("lon") or ds.variables.get("longitude")
        lat_var = ds.variables.get("lat") or ds.variables.get("latitude")
        prec_var = ds.variables.get("precipitation")
        if lon_var is None or lat_var is None or prec_var is None:
            raise ValueError("IMERG file missing lon/lat/precipitation variables")

        lon = np.asarray(lon_var[:], dtype=float).reshape(-1)
        lat = np.asarray(lat_var[:], dtype=float).reshape(-1)
        var = prec_var
        data = var[:]

        # Remove a leading time dimension (daily product normally has size 1).
        if data.ndim == 3:
            data = data[0]
        if data.ndim != 2:
            raise ValueError(f"Unexpected precipitation dimensions: {data.shape}")

        # Normalize requested longitude to the dataset convention.
        req_lon = float(longitude)
        if np.nanmin(lon) >= 0 and req_lon < 0:
            req_lon = req_lon % 360.0
        elif np.nanmax(lon) <= 180 and req_lon > 180:
            req_lon = ((req_lon + 180.0) % 360.0) - 180.0

        lon_i = int(np.argmin(np.abs(lon - req_lon)))
        lat_i = int(np.argmin(np.abs(lat - float(latitude))))

        # Detect which precipitation axis corresponds to latitude/longitude.
        shape = data.shape
        if shape == (len(lat), len(lon)):
            value = data[lat_i, lon_i]
        elif shape == (len(lon), len(lat)):
            value = data[lon_i, lat_i]
        else:
            raise ValueError(
                f"Precipitation shape {shape} does not match lat={len(lat)}, lon={len(lon)}"
            )

        if np.ma.isMaskedArray(value):
            value = value.filled(np.nan)
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("IMERG precipitation is missing/non-finite at requested location")
        units = str(getattr(var, "units", "")).lower()
        if units and "mm" not in units:
            raise ValueError(f"Unexpected IMERG precipitation units: {units}")
        return max(0.0, value)


def _candidate_nc4_files() -> list[Path]:
    files: list[Path] = []
    if SATELLITE_FILE:
        p = _resolve(SATELLITE_FILE)
        if p.exists() and p.is_file():
            files.append(p)
    d = _resolve(SATELLITE_DIR)
    if d.exists() and d.is_dir():
        files.extend(sorted((p for p in d.glob("*.nc4") if p.is_file() and p.stat().st_size > 1_000_000), key=lambda x: x.name))
    # De-duplicate while preserving order.
    seen = set()
    out = []
    for p in files:
        r = str(p.resolve())
        if r not in seen:
            out.append(p)
            seen.add(r)
    return out


def _date_from_imerg_filename(path: Path):
    import re
    from datetime import datetime
    m = re.search(r"(20\d{6})", path.name)
    return datetime.strptime(m.group(1), "%Y%m%d").date() if m else None


def _local_imerg_summary(latitude: float, longitude: float) -> Dict[str, Any]:
    files = _candidate_nc4_files()
    if not files:
        return {}

    # Process latest file plus history that may already be downloaded.
    rows = []
    errors = []
    for path in files:
        try:
            value = _nc4_rainfall_at(path, latitude, longitude)
            day = _date_from_imerg_filename(path)
            rows.append((day, path, value))
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")

    if not rows:
        return {"error": "; ".join(errors) if errors else "No readable IMERG NC4 files"}

    rows.sort(key=lambda x: (x[0] or 0, x[1].name))
    latest_day, latest_path, latest_value = rows[-1]

    from datetime import timedelta
    def rolling(days: int) -> Optional[float]:
        cutoff = latest_day - timedelta(days=days - 1) if latest_day else None
        vals = [v for d, _, v in rows if cutoff is None or d is None or d >= cutoff]
        return round(sum(vals), 3) if vals else None

    return {
        "available": True,
        "provider": "NASA GPM IMERG",
        "mode": "local_netcdf4",
        "path": str(latest_path),
        "date": latest_day.isoformat() if latest_day else None,
        "numeric_rainfall_available": True,
        "rainfall_24h_mm": round(latest_value, 3),
        "rainfall_3d_mm": rolling(3),
        "rainfall_7d_mm": rolling(7),
        "rainfall_15d_mm": rolling(15),
        "rainfall_30d_mm": rolling(30),
        "files_read": len(rows),
        "files_failed": len(errors),
        "errors": errors[:5],
    }

async def satellite_status() -> Dict[str, Any]:
    if SATELLITE_JSON_URL:
        payload = await fetch_json(SATELLITE_JSON_URL)
        value = _num(
            payload,
            "rainfall_24h_mm",
            "rainfall_satellite_24h_mm",
            "satellite_precipitation_mm",
        )
        return {
            "available": value is not None,
            "provider": "NASA GPM IMERG",
            "mode": "json",
            "numeric_rainfall_available": value is not None,
            "rainfall_24h_mm": value,
            "error": payload.get("_error"),
        }

    local = _local_imerg_summary(20.2961, 85.8245)
    if local:
        return local

    if SATELLITE_FILE:
        path = _resolve(SATELLITE_FILE)
        return {
            "available": path.exists(),
            "provider": "NASA GPM IMERG",
            "mode": "local_raster_or_file",
            "path": str(path),
            "numeric_rainfall_available": False,
            "note": "File exists but could not be sampled as a supported IMERG dataset."
        }

    pmm = await _pmm_latest_asset()
    if pmm.get("download_url"):
        return {
            "available": True,
            "provider": "NASA GPM IMERG",
            "mode": "PMM_Publisher_API",
            "numeric_rainfall_available": True,
            "dataset": pmm.get("dataset"),
            "date": pmm.get("date"),
            "resolution": pmm.get("resolution"),
            "download_url": pmm.get("download_url"),
            "note": "Latest IMERG 1-day precipitation asset discovered automatically via NASA PMM Publisher API."
        }

    return {
        "available": False,
        "provider": None,
        "numeric_rainfall_available": False,
        "note": "Configure EWS_SATELLITE_JSON_URL or EWS_SATELLITE_GPM_FILE, or ensure NASA PMM Publisher is reachable from the backend host.",
        "pmm_url": NASA_PMM_URL,
        "pmm_error": PMM_LAST_ERROR,
    }


async def fetch_satellite(latitude: float, longitude: float) -> Dict[str, Any]:
    # Preferred fast/demo integration: a trusted upstream adapter can expose
    # a point-sampled IMERG value as JSON.
    if SATELLITE_JSON_URL:
        payload = await fetch_json(
            SATELLITE_JSON_URL,
            params={"latitude": latitude, "longitude": longitude},
        )
        value = _num(
            payload,
            "rainfall_24h_mm",
            "rainfall_satellite_24h_mm",
            "satellite_precipitation_mm",
        )
        return {
            "available": value is not None,
            "provider": "NASA GPM IMERG",
            "rainfall_24h_mm": value or 0.0,
            "numeric": value is not None,
            "error": payload.get("_error"),
        }

    # Local NASA IMERG NetCDF4 daily files (preferred).
    local_files = _candidate_nc4_files()
    if local_files:
        latest = None
        latest_day = None
        for path in local_files:
            try:
                day = _date_from_imerg_filename(path)
                if latest is None or (day or 0) > (latest_day or 0):
                    latest = path
                    latest_day = day
            except Exception:
                continue
        if latest is not None:
            try:
                summary = _local_imerg_summary(latitude, longitude)
                if summary.get("numeric_rainfall_available"):
                    return summary
            except Exception as exc:
                return {
                    "available": False,
                    "provider": "NASA GPM IMERG",
                    "rainfall_24h_mm": 0.0,
                    "numeric": False,
                    "mode": "local_netcdf4",
                    "error": str(exc),
                }

    # GeoTIFF point sampling for a downloaded IMERG file.
    if SATELLITE_FILE:
        path = _resolve(SATELLITE_FILE)
        if path.exists() and path.suffix.lower() in {".tif", ".tiff"}:
            try:
                import rasterio  # type: ignore
                with rasterio.open(path) as ds:
                    value = next(ds.sample([(longitude, latitude)]))[0]
                    if value is None or not math.isfinite(float(value)):
                        raise ValueError("No finite IMERG value at location")
                    mm = float(value)
                    return {
                        "available": True,
                        "provider": "NASA GPM IMERG",
                        "rainfall_24h_mm": max(0.0, mm),
                        "numeric": True,
                        "file": str(path),
                    }
            except Exception as exc:
                return {
                    "available": False,
                    "provider": "NASA GPM IMERG",
                    "rainfall_24h_mm": 0.0,
                    "numeric": False,
                    "error": str(exc),
                }

    # Automatic public PMM Publisher integration. The Publisher API exposes
    # the latest IMERG assets; we download the GeoTIFF and sample the selected
    # coordinate. If NASA changes availability, the engine degrades safely.
    pmm = await _pmm_latest_asset(latitude, longitude)
    url = pmm.get("download_url")
    if url:
        try:
            import tempfile
            import rasterio  # type: ignore
            cache_dir = MODULE_DIR / "data"
            cache_dir.mkdir(exist_ok=True)
            safe_name = "imerg_pmm_latest_1day.tif"
            target = cache_dir / safe_name
            async with httpx.AsyncClient(
                timeout=max(TIMEOUT, 30),
                follow_redirects=True,
                headers={"User-Agent": "Odisha-Flood-EWS/1.0"},
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                target.write_bytes(response.content)
            with rasterio.open(target) as ds:
                value = next(ds.sample([(longitude, latitude)]))[0]
            mm = float(value) / 10.0
            if not math.isfinite(mm):
                raise ValueError("IMERG returned non-finite precipitation")
            return {
                "available": True,
                "provider": "NASA GPM IMERG",
                "rainfall_24h_mm": max(0.0, mm),
                "numeric": True,
                "mode": "PMM_Publisher_API",
                "dataset": pmm.get("dataset"),
                "date": pmm.get("date"),
                "resolution": pmm.get("resolution"),
            }
        except Exception as exc:
            return {
                "available": False,
                "provider": "NASA GPM IMERG",
                "rainfall_24h_mm": 0.0,
                "numeric": False,
                "mode": "PMM_Publisher_API",
                "error": str(exc),
            }

    return {
        "available": False,
        "provider": None,
        "rainfall_24h_mm": 0.0,
        "numeric": False,
    }


async def fetch_radar(latitude: float, longitude: float) -> Dict[str, Any]:
    if not RADAR_FEED_URL:
        # Metadata health is separate from numeric model input.
        status = await radar_status()
        return {
            "available": bool(status.get("available")),
            "numeric": False,
            "provider": "RainViewer" if status.get("available") else None,
            "rainfall_1h_mm": 0.0,
            "rainfall_3h_mm": 0.0,
            "metadata": status,
        }

    payload = await fetch_json(
        RADAR_FEED_URL,
        params={"latitude": latitude, "longitude": longitude},
    )
    r1 = _num(payload, "rainfall_1h_mm", "rainfall_radar_1h_mm")
    r3 = _num(payload, "rainfall_3h_mm", "rainfall_radar_3h_mm")
    numeric = r1 is not None or r3 is not None
    return {
        "available": numeric,
        "numeric": numeric,
        "provider": payload.get("provider") or "Configured radar rainfall feed",
        "rainfall_1h_mm": r1 or 0.0,
        "rainfall_3h_mm": r3 if r3 is not None else (r1 or 0.0),
        "error": payload.get("_error"),
    }
