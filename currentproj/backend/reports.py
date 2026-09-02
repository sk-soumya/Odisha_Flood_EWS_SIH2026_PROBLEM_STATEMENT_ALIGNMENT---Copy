# ============================================================
# ODISHA FLOOD RISK & EMERGENCY EVACUATION SYSTEM
# reports.py — FINAL
#
# CITIZEN FLOOD REPORTING + ADMIN REVIEW WORKFLOW
#
# WORKFLOW
#   Citizen submits
#        ↓
#   NEW
#        ↓
#   Admin reviews
#        ↓
#   REVIEWING
#      ↙   ↘
#  VERIFIED  REJECTED
#      ↓
#    CLOSED
#
# ADMIN CAN:
#   - View reports
#   - Open single report
#   - Edit report information
#   - Change status
#   - Change priority
#   - Add review notes
#   - Verify / reject / close
#   - Open GPS location on Google Maps
#   - View uploaded report photo
#
# IMPORTANT
#   Citizen reports are observations and are NOT automatically
#   treated as official government warnings.
# ============================================================

import secrets
import sqlite3

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
)

from pydantic import BaseModel, Field


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"

REPORT_UPLOAD_DIR = (
    BASE_DIR
    / "citizen"
    / "uploads"
    / "reports"
)

DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "ews_users.db"


# ============================================================
# ROUTERS
# ============================================================

citizen_router = APIRouter(
    prefix="/api/v1/citizen",
    tags=["Citizen Reports"],
)

admin_router = APIRouter(
    prefix="/api/v1/admin",
    tags=["Admin Reports"],
)


# ============================================================
# DATABASE
# ============================================================

def db() -> sqlite3.Connection:
    connection = sqlite3.connect(
        DB_PATH,
        timeout=20,
    )

    connection.row_factory = sqlite3.Row

    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    connection.execute(
        "PRAGMA journal_mode = WAL"
    )

    connection.execute(
        "PRAGMA busy_timeout = 20000"
    )

    return connection


# ============================================================
# TIME
# ============================================================

def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


# ============================================================
# AUTH DEPENDENCIES
# ============================================================

def get_current_user():
    try:
        from users import current_user

        return current_user

    except Exception as error:
        raise RuntimeError(
            "Citizen authentication could not be loaded."
        ) from error


def get_current_admin():
    try:
        from admin import current_admin

        return current_admin

    except Exception as error:
        raise RuntimeError(
            "Admin authentication could not be loaded."
        ) from error


# ============================================================
# ALLOWED VALUES
# ============================================================

ALLOWED_SEVERITIES = {
    "LOW",
    "MEDIUM",
    "HIGH",
    "CRITICAL",
}

# UI-compatible final workflow.
ALLOWED_STATUSES = {
    "NEW",
    "REVIEWING",
    "VERIFIED",
    "REJECTED",
    "CLOSED",
}

ALLOWED_PRIORITIES = {
    "LOW",
    "NORMAL",
    "HIGH",
    "URGENT",
}


STATUS_ALIASES = {
    # Older versions
    "SUBMITTED": "NEW",
    "UNDER_REVIEW": "REVIEWING",
    "ACTION_TAKEN": "VERIFIED",
}


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_text(
    value: Optional[str],
) -> Optional[str]:

    if value is None:
        return None

    value = value.strip()

    return value or None


def normalize_severity(
    value: str,
) -> str:

    severity = (
        value
        or "MEDIUM"
    ).strip().upper()

    if severity not in ALLOWED_SEVERITIES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Severity must be LOW, MEDIUM, "
                "HIGH or CRITICAL."
            ),
        )

    return severity


def normalize_status(
    value: str,
) -> str:

    status_value = (
        value
        or ""
    ).strip().upper()

    status_value = STATUS_ALIASES.get(
        status_value,
        status_value,
    )

    if status_value not in ALLOWED_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Status must be NEW, REVIEWING, "
                "VERIFIED, REJECTED or CLOSED."
            ),
        )

    return status_value


def normalize_priority(
    value: str,
) -> str:

    priority = (
        value
        or "NORMAL"
    ).strip().upper()

    if priority not in ALLOWED_PRIORITIES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Priority must be LOW, NORMAL, "
                "HIGH or URGENT."
            ),
        )

    return priority


# ============================================================
# UID
# ============================================================

def generate_report_uid() -> str:

    return (
        "RPT-"
        + secrets.token_hex(6).upper()
    )


# ============================================================
# ODisha LOCATION VALIDATION
# ============================================================

def valid_odisha_location(
    latitude: Optional[float],
    longitude: Optional[float],
) -> bool:

    if latitude is None or longitude is None:
        return True

    return (
        17.5 <= latitude <= 22.7
        and
        81.3 <= longitude <= 87.6
    )


# ============================================================
# DATABASE MIGRATION / INITIALIZATION
# ============================================================

def _column_names(
    connection: sqlite3.Connection,
) -> set[str]:

    return {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(flood_reports)"
        ).fetchall()
    }


def _ensure_column(
    connection: sqlite3.Connection,
    name: str,
    definition: str,
) -> None:

    if name not in _column_names(connection):

        connection.execute(
            f"ALTER TABLE flood_reports "
            f"ADD COLUMN {name} {definition}"
        )


def init_reports_table() -> None:

    with db() as connection:

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS flood_reports (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                report_uid TEXT UNIQUE NOT NULL,

                user_uid TEXT NOT NULL,

                reporter_name TEXT,

                reporter_mobile TEXT,

                area TEXT,

                village TEXT,

                landmark TEXT,

                latitude REAL,

                longitude REAL,

                water_level_cm REAL,

                severity TEXT NOT NULL
                    DEFAULT 'MEDIUM',

                description TEXT NOT NULL,

                photo_path TEXT,

                status TEXT NOT NULL
                    DEFAULT 'NEW',

                priority TEXT NOT NULL
                    DEFAULT 'NORMAL',

                admin_notes TEXT,

                reviewed_by TEXT,

                reviewed_at TEXT,

                created_at TEXT NOT NULL,

                updated_at TEXT NOT NULL
            )
            """
        )

        # ----------------------------------------------------
        # Compatibility migration for databases made by older
        # versions of reports.py.
        # ----------------------------------------------------

        migrations = {
            "reporter_name": "TEXT",
            "reporter_mobile": "TEXT",
            "area": "TEXT",
            "village": "TEXT",
            "landmark": "TEXT",
            "latitude": "REAL",
            "longitude": "REAL",
            "water_level_cm": "REAL",
            "severity": (
                "TEXT NOT NULL DEFAULT 'MEDIUM'"
            ),
            "description": "TEXT",
            "photo_path": "TEXT",
            "status": (
                "TEXT NOT NULL DEFAULT 'NEW'"
            ),
            "priority": (
                "TEXT NOT NULL DEFAULT 'NORMAL'"
            ),
            "admin_notes": "TEXT",
            "reviewed_by": "TEXT",
            "reviewed_at": "TEXT",
            "created_at": "TEXT",
            "updated_at": "TEXT",
        }

        for name, definition in migrations.items():
            _ensure_column(
                connection,
                name,
                definition,
            )

        # ----------------------------------------------------
        # Migrate legacy status names to the final UI names.
        # ----------------------------------------------------

        connection.execute(
            """
            UPDATE flood_reports
            SET status='NEW'
            WHERE upper(trim(status))='SUBMITTED'
               OR status IS NULL
               OR trim(status)=''
            """
        )

        connection.execute(
            """
            UPDATE flood_reports
            SET status='REVIEWING'
            WHERE upper(trim(status))='UNDER_REVIEW'
            """
        )

        connection.execute(
            """
            UPDATE flood_reports
            SET status='VERIFIED'
            WHERE upper(trim(status))='ACTION_TAKEN'
            """
        )

        connection.execute(
            """
            UPDATE flood_reports
            SET priority='NORMAL'
            WHERE priority IS NULL
               OR trim(priority)=''
            """
        )

        # ----------------------------------------------------
        # Indexes
        # ----------------------------------------------------

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_flood_reports_user
            ON flood_reports(user_uid)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_flood_reports_status
            ON flood_reports(status)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_flood_reports_area
            ON flood_reports(area)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_flood_reports_created
            ON flood_reports(created_at)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_flood_reports_severity
            ON flood_reports(severity)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_flood_reports_priority
            ON flood_reports(priority)
            """
        )


# Keep module-level behavior compatible with your existing main.py.
init_reports_table()


# ============================================================
# PYDANTIC MODELS
# ============================================================

class FloodReportCreateRequest(BaseModel):

    area: Optional[str] = Field(
        default=None,
        max_length=120,
    )

    village: Optional[str] = Field(
        default=None,
        max_length=120,
    )

    landmark: Optional[str] = Field(
        default=None,
        max_length=200,
    )

    latitude: Optional[float] = Field(
        default=None,
        ge=-90,
        le=90,
    )

    longitude: Optional[float] = Field(
        default=None,
        ge=-180,
        le=180,
    )

    water_level_cm: Optional[float] = Field(
        default=None,
        ge=0,
        le=100000,
    )

    severity: str = Field(
        default="MEDIUM",
        min_length=1,
        max_length=20,
    )

    description: str = Field(
        min_length=5,
        max_length=5000,
    )


class FloodReportEditRequest(BaseModel):

    area: Optional[str] = Field(
        default=None,
        max_length=120,
    )

    village: Optional[str] = Field(
        default=None,
        max_length=120,
    )

    landmark: Optional[str] = Field(
        default=None,
        max_length=200,
    )

    latitude: Optional[float] = Field(
        default=None,
        ge=-90,
        le=90,
    )

    longitude: Optional[float] = Field(
        default=None,
        ge=-180,
        le=180,
    )

    water_level_cm: Optional[float] = Field(
        default=None,
        ge=0,
        le=100000,
    )

    severity: Optional[str] = Field(
        default=None,
        max_length=20,
    )

    description: Optional[str] = Field(
        default=None,
        min_length=5,
        max_length=5000,
    )


class FloodReportStatusRequest(BaseModel):

    status: str = Field(
        min_length=2,
        max_length=30,
    )

    admin_notes: Optional[str] = Field(
        default=None,
        max_length=3000,
    )


class FloodReportPriorityRequest(BaseModel):

    priority: str = Field(
        min_length=2,
        max_length=20,
    )



def user_value(
    user,
    key: str,
    default=None,
):
    """Read a citizen field from either sqlite3.Row or dict."""
    try:
        return user[key]
    except (KeyError, IndexError, TypeError):
        try:
            return user.get(key, default)
        except AttributeError:
            return default


# ============================================================
# REPORT LOOKUP HELPERS
# ============================================================

def get_report(
    report_uid: str,
    user_uid: Optional[str] = None,
) -> Optional[sqlite3.Row]:

    with db() as connection:

        if user_uid is None:

            return connection.execute(
                """
                SELECT *
                FROM flood_reports
                WHERE report_uid=?
                """,
                (report_uid,),
            ).fetchone()

        return connection.execute(
            """
            SELECT *
            FROM flood_reports
            WHERE report_uid=?
              AND user_uid=?
            """,
            (
                report_uid,
                user_uid,
            ),
        ).fetchone()


# ============================================================
# CITIZEN CREATE REPORT
# ============================================================

@citizen_router.post(
    "/reports"
)
def create_report(
    req: FloodReportCreateRequest,
    user=Depends(get_current_user()),
):

    if not valid_odisha_location(
        req.latitude,
        req.longitude,
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "The supplied coordinates are "
                "outside the approximate Odisha area."
            ),
        )

    description = (
        req.description
        or ""
    ).strip()

    if len(description) < 5:
        raise HTTPException(
            status_code=400,
            detail=(
                "Flood report description is required."
            ),
        )

    severity = normalize_severity(
        req.severity
    )

    user_uid = user_value(
        user,
        "user_uid",
    )

    if not user_uid:
        raise HTTPException(
            status_code=401,
            detail="Citizen identity is unavailable.",
        )

    report_uid = generate_report_uid()
    now = utc_now()

    try:

        with db() as connection:

            connection.execute(
                """
                INSERT INTO flood_reports
                (
                    report_uid,
                    user_uid,
                    reporter_name,
                    reporter_mobile,
                    area,
                    village,
                    landmark,
                    latitude,
                    longitude,
                    water_level_cm,
                    severity,
                    description,
                    status,
                    priority,
                    created_at,
                    updated_at
                )
                VALUES
                (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, 'NEW', 'NORMAL', ?, ?
                )
                """,
                (
                    report_uid,
                    user_uid,
                    user_value(
                        user,
                        "name",
                    ),
                    user_value(
                        user,
                        "mobile",
                    ),
                    normalize_text(req.area),
                    normalize_text(req.village),
                    normalize_text(req.landmark),
                    req.latitude,
                    req.longitude,
                    req.water_level_cm,
                    severity,
                    description,
                    now,
                    now,
                ),
            )

    except sqlite3.Error as error:

        print(
            "[FLOOD REPORT CREATE ERROR]",
            error,
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "The flood report could not be saved. "
                "Please try again."
            ),
        ) from error

    return {
        "status": "REPORT_SUBMITTED",
        "report_uid": report_uid,
        "message": (
            "Your flood report was submitted successfully "
            "and is awaiting administrative review."
        ),
        "severity": severity,
        "review_status": "NEW",
    }


# ============================================================
# CITIZEN PHOTO
# ============================================================

@citizen_router.post(
    "/reports/{report_uid}/photo"
)
async def upload_report_photo(
    report_uid: str,
    photo: UploadFile = File(...),
    user=Depends(get_current_user()),
):

    allowed_types = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }

    extension = allowed_types.get(
        photo.content_type
    )

    if not extension:
        raise HTTPException(
            status_code=400,
            detail="Photo must be JPG, PNG or WEBP.",
        )

    user_uid = user_value(
        user,
        "user_uid",
    )

    report = get_report(
        report_uid,
        user_uid,
    )

    if not report:
        raise HTTPException(
            status_code=404,
            detail="Flood report not found.",
        )

    contents = await photo.read()

    if not contents:
        raise HTTPException(
            status_code=400,
            detail="Uploaded photo is empty.",
        )

    if len(contents) > 8 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=(
                "Flood-report photo must be "
                "smaller than 8 MB."
            ),
        )

    filename = (
        report_uid
        + "_"
        + secrets.token_hex(5)
        + extension
    )

    destination = (
        REPORT_UPLOAD_DIR
        / filename
    )

    destination.write_bytes(contents)

    public_path = (
        "/citizen/uploads/reports/"
        + filename
    )

    old_photo = report["photo_path"]

    with db() as connection:

        connection.execute(
            """
            UPDATE flood_reports
            SET
                photo_path=?,
                updated_at=?
            WHERE report_uid=?
              AND user_uid=?
            """,
            (
                public_path,
                utc_now(),
                report_uid,
                user_uid,
            ),
        )

    # Remove old photo only if it was inside our
    # controlled report upload directory.
    if (
        old_photo
        and old_photo.startswith(
            "/citizen/uploads/reports/"
        )
    ):

        old_path = (
            REPORT_UPLOAD_DIR
            /
            old_photo.rsplit(
                "/",
                1,
            )[-1]
        )

        try:
            old_path.unlink(
                missing_ok=True
            )
        except Exception:
            pass

    return {
        "status": "PHOTO_UPLOADED",
        "report_uid": report_uid,
        "photo_path": public_path,
        "message": (
            "Flood-report photo uploaded successfully."
        ),
    }


# ============================================================
# CITIZEN REPORT HISTORY
# ============================================================

@citizen_router.get(
    "/reports"
)
def citizen_report_history(
    user=Depends(get_current_user()),
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
):

    user_uid = user_value(
        user,
        "user_uid",
    )

    if not user_uid:
        raise HTTPException(
            status_code=401,
            detail="Citizen identity is unavailable.",
        )

    with db() as connection:

        rows = connection.execute(
            """
            SELECT
                report_uid,
                user_uid,
                reporter_name,
                reporter_mobile,
                area,
                village,
                landmark,
                latitude,
                longitude,
                water_level_cm,
                severity,
                description,
                photo_path,
                status,
                priority,
                admin_notes,
                reviewed_by,
                reviewed_at,
                created_at,
                updated_at
            FROM flood_reports
            WHERE user_uid=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                user_uid,
                limit,
            ),
        ).fetchall()

    return {
        "status": "SUCCESS",
        "count": len(rows),
        "reports": [
            dict(row)
            for row in rows
        ],
    }


# ============================================================
# CITIZEN SINGLE REPORT
# ============================================================

@citizen_router.get(
    "/reports/{report_uid}"
)
def citizen_get_report(
    report_uid: str,
    user=Depends(get_current_user()),
):

    row = get_report(
        report_uid,
        user.get("user_uid"),
    )

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Flood report not found.",
        )

    return {
        "status": "SUCCESS",
        "report": dict(row),
    }


# ============================================================
# ADMIN REPORT DASHBOARD
#
# NOTE:
# These fixed routes are intentionally declared BEFORE
# /reports/{report_uid} so "dashboard" and "priority-feed"
# cannot be interpreted as report IDs.
# ============================================================

@admin_router.get(
    "/reports/dashboard"
)
def admin_reports_dashboard(
    admin=Depends(get_current_admin()),
):

    with db() as connection:

        total = connection.execute(
            """
            SELECT COUNT(*)
            FROM flood_reports
            """
        ).fetchone()[0]

        new = connection.execute(
            """
            SELECT COUNT(*)
            FROM flood_reports
            WHERE status='NEW'
            """
        ).fetchone()[0]

        reviewing = connection.execute(
            """
            SELECT COUNT(*)
            FROM flood_reports
            WHERE status='REVIEWING'
            """
        ).fetchone()[0]

        verified = connection.execute(
            """
            SELECT COUNT(*)
            FROM flood_reports
            WHERE status='VERIFIED'
            """
        ).fetchone()[0]

        rejected = connection.execute(
            """
            SELECT COUNT(*)
            FROM flood_reports
            WHERE status='REJECTED'
            """
        ).fetchone()[0]

        closed = connection.execute(
            """
            SELECT COUNT(*)
            FROM flood_reports
            WHERE status='CLOSED'
            """
        ).fetchone()[0]

        high_or_critical_active = connection.execute(
            """
            SELECT COUNT(*)
            FROM flood_reports
            WHERE severity IN ('HIGH', 'CRITICAL')
              AND status NOT IN ('REJECTED', 'CLOSED')
            """
        ).fetchone()[0]

        urgent_active = connection.execute(
            """
            SELECT COUNT(*)
            FROM flood_reports
            WHERE priority='URGENT'
              AND status NOT IN ('REJECTED', 'CLOSED')
            """
        ).fetchone()[0]

        today = connection.execute(
            """
            SELECT COUNT(*)
            FROM flood_reports
            WHERE date(created_at)=date('now')
            """
        ).fetchone()[0]

    return {
        "status": "SUCCESS",
        "reported_by": admin,
        "statistics": {
            "total": total,
            "new": new,
            "submitted": new,
            "reviewing": reviewing,
            "under_review": reviewing,
            "verified": verified,
            "rejected": rejected,
            "closed": closed,
            "action_taken": verified,
            "high_or_critical_active":
                high_or_critical_active,
            "urgent_active":
                urgent_active,
            "today":
                today,
        },
        "timestamp": utc_now(),
    }


# ============================================================
# ADMIN PRIORITY FEED
# ============================================================

@admin_router.get(
    "/reports/priority-feed"
)
def admin_priority_feed(
    admin=Depends(get_current_admin()),
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
):

    with db() as connection:

        rows = connection.execute(
            """
            SELECT
                id,
                report_uid,
                user_uid,
                reporter_name,
                reporter_mobile,
                area,
                village,
                landmark,
                latitude,
                longitude,
                water_level_cm,
                severity,
                description,
                photo_path,
                status,
                priority,
                admin_notes,
                reviewed_by,
                reviewed_at,
                created_at,
                updated_at
            FROM flood_reports
            WHERE status NOT IN ('REJECTED', 'CLOSED')
              AND (
                   priority IN ('HIGH', 'URGENT')
                   OR
                   severity IN ('HIGH', 'CRITICAL')
              )
            ORDER BY
                CASE priority
                    WHEN 'URGENT' THEN 1
                    WHEN 'HIGH' THEN 2
                    WHEN 'NORMAL' THEN 3
                    ELSE 4
                END,
                CASE severity
                    WHEN 'CRITICAL' THEN 1
                    WHEN 'HIGH' THEN 2
                    WHEN 'MEDIUM' THEN 3
                    ELSE 4
                END,
                id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return {
        "status": "SUCCESS",
        "count": len(rows),
        "reports": [
            dict(row)
            for row in rows
        ],
    }


# ============================================================
# ADMIN REPORT LIST
# ============================================================

@admin_router.get(
    "/reports"
)
def admin_list_reports(
    admin=Depends(get_current_admin()),
    search: Optional[str] = Query(
        default=None,
        max_length=150,
    ),
    area: Optional[str] = Query(
        default=None,
        max_length=120,
    ),
    status_filter: Optional[str] = Query(
        default=None,
        max_length=30,
    ),
    severity: Optional[str] = Query(
        default=None,
        max_length=20,
    ),
    priority: Optional[str] = Query(
        default=None,
        max_length=20,
    ),
    limit: int = Query(
        default=500,
        ge=1,
        le=2000,
    ),
):

    conditions: list[str] = []
    parameters: list[Any] = []

    if search:

        search_value = (
            "%"
            + search.strip().lower()
            + "%"
        )

        conditions.append(
            """
            (
                lower(report_uid) LIKE ?
                OR lower(user_uid) LIKE ?
                OR lower(reporter_name) LIKE ?
                OR lower(reporter_mobile) LIKE ?
                OR lower(area) LIKE ?
                OR lower(village) LIKE ?
                OR lower(landmark) LIKE ?
                OR lower(description) LIKE ?
            )
            """
        )

        parameters.extend(
            [search_value] * 8
        )

    if area:

        conditions.append(
            "lower(trim(area))=?"
        )

        parameters.append(
            area.strip().lower()
        )

    if (
        status_filter
        and status_filter.upper() != "ALL"
    ):

        conditions.append(
            "status=?"
        )

        parameters.append(
            normalize_status(
                status_filter
            )
        )

    if (
        severity
        and severity.upper() != "ALL"
    ):

        conditions.append(
            "severity=?"
        )

        parameters.append(
            normalize_severity(
                severity
            )
        )

    if (
        priority
        and priority.upper() != "ALL"
    ):

        conditions.append(
            "priority=?"
        )

        parameters.append(
            normalize_priority(
                priority
            )
        )

    where_clause = ""

    if conditions:
        where_clause = (
            "WHERE "
            + " AND ".join(
                conditions
            )
        )

    with db() as connection:

        rows = connection.execute(
            f"""
            SELECT
                id,
                report_uid,
                user_uid,
                reporter_name,
                reporter_mobile,
                area,
                village,
                landmark,
                latitude,
                longitude,
                water_level_cm,
                severity,
                description,
                photo_path,
                status,
                priority,
                admin_notes,
                reviewed_by,
                reviewed_at,
                created_at,
                updated_at
            FROM flood_reports
            {where_clause}
            ORDER BY id DESC
            LIMIT ?
            """,
            tuple(parameters) + (limit,),
        ).fetchall()

    return {
        "status": "SUCCESS",
        "count": len(rows),
        "reports": [
            dict(row)
            for row in rows
        ],
    }


# ============================================================
# ADMIN SINGLE REPORT
# ============================================================

@admin_router.get(
    "/reports/{report_uid}"
)
def admin_get_report(
    report_uid: str,
    admin=Depends(get_current_admin()),
):

    row = get_report(report_uid)

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Flood report not found.",
        )

    return {
        "status": "SUCCESS",
        "report": dict(row),
    }


# ============================================================
# ADMIN EDIT REPORT
#
# This is the endpoint for "Edit" from the admin portal.
# It updates the citizen's submitted observation without
# changing who the original reporter was.
# ============================================================

@admin_router.patch(
    "/reports/{report_uid}"
)
def admin_edit_report(
    report_uid: str,
    req: FloodReportEditRequest,
    admin=Depends(get_current_admin()),
):

    current = get_report(report_uid)

    if not current:
        raise HTTPException(
            status_code=404,
            detail="Flood report not found.",
        )

    # Only update fields explicitly supplied.
    values = {
        "area": (
            normalize_text(req.area)
            if req.area is not None
            else current["area"]
        ),
        "village": (
            normalize_text(req.village)
            if req.village is not None
            else current["village"]
        ),
        "landmark": (
            normalize_text(req.landmark)
            if req.landmark is not None
            else current["landmark"]
        ),
        "latitude": (
            req.latitude
            if req.latitude is not None
            else current["latitude"]
        ),
        "longitude": (
            req.longitude
            if req.longitude is not None
            else current["longitude"]
        ),
        "water_level_cm": (
            req.water_level_cm
            if req.water_level_cm is not None
            else current["water_level_cm"]
        ),
        "severity": (
            normalize_severity(req.severity)
            if req.severity is not None
            else current["severity"]
        ),
        "description": (
            normalize_text(req.description)
            if req.description is not None
            else current["description"]
        ),
    }

    if not valid_odisha_location(
        values["latitude"],
        values["longitude"],
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "The supplied coordinates are "
                "outside the approximate Odisha area."
            ),
        )

    if not values["description"]:
        raise HTTPException(
            status_code=400,
            detail="Description cannot be empty.",
        )

    now = utc_now()

    with db() as connection:

        connection.execute(
            """
            UPDATE flood_reports
            SET
                area=?,
                village=?,
                landmark=?,
                latitude=?,
                longitude=?,
                water_level_cm=?,
                severity=?,
                description=?,
                reviewed_by=?,
                reviewed_at=?,
                updated_at=?
            WHERE report_uid=?
            """,
            (
                values["area"],
                values["village"],
                values["landmark"],
                values["latitude"],
                values["longitude"],
                values["water_level_cm"],
                values["severity"],
                values["description"],
                admin,
                now,
                now,
                report_uid,
            ),
        )

    return {
        "status": "REPORT_EDITED",
        "report_uid": report_uid,
        "updated_by": admin,
        "message": (
            "Flood report details updated successfully."
        ),
    }


# ============================================================
# ADMIN UPDATE STATUS
# ============================================================

@admin_router.patch(
    "/reports/{report_uid}/status"
)
def admin_update_report_status(
    report_uid: str,
    req: FloodReportStatusRequest,
    admin=Depends(get_current_admin()),
):

    new_status = normalize_status(
        req.status
    )

    notes = normalize_text(
        req.admin_notes
    )

    current = get_report(
        report_uid
    )

    if not current:
        raise HTTPException(
            status_code=404,
            detail="Flood report not found.",
        )

    # When admin is only changing the status and no new notes
    # were supplied, preserve the existing notes.
    if req.admin_notes is None:
        notes = current["admin_notes"]

    now = utc_now()

    with db() as connection:

        connection.execute(
            """
            UPDATE flood_reports
            SET
                status=?,
                admin_notes=?,
                reviewed_by=?,
                reviewed_at=?,
                updated_at=?
            WHERE report_uid=?
            """,
            (
                new_status,
                notes,
                admin,
                now,
                now,
                report_uid,
            ),
        )

    return {
        "status": "REPORT_UPDATED",
        "report_uid": report_uid,
        "report_status": new_status,
        "reviewed_by": admin,
        "message": (
            "Flood report status updated successfully."
        ),
    }


# ============================================================
# ADMIN UPDATE PRIORITY
# ============================================================

@admin_router.patch(
    "/reports/{report_uid}/priority"
)
def admin_update_report_priority(
    report_uid: str,
    req: FloodReportPriorityRequest,
    admin=Depends(get_current_admin()),
):

    priority = normalize_priority(
        req.priority
    )

    current = get_report(
        report_uid
    )

    if not current:
        raise HTTPException(
            status_code=404,
            detail="Flood report not found.",
        )

    with db() as connection:

        connection.execute(
            """
            UPDATE flood_reports
            SET
                priority=?,
                updated_at=?
            WHERE report_uid=?
            """,
            (
                priority,
                utc_now(),
                report_uid,
            ),
        )

    return {
        "status": "PRIORITY_UPDATED",
        "report_uid": report_uid,
        "priority": priority,
        "updated_by": admin,
    }


# ============================================================
# ADMIN QUICK REVIEWING
# ============================================================

@admin_router.post(
    "/reports/{report_uid}/review"
)
def admin_review_report(
    report_uid: str,
    admin=Depends(get_current_admin()),
):

    current = get_report(
        report_uid
    )

    if not current:
        raise HTTPException(
            status_code=404,
            detail="Flood report not found.",
        )

    now = utc_now()

    with db() as connection:

        connection.execute(
            """
            UPDATE flood_reports
            SET
                status='REVIEWING',
                reviewed_by=?,
                reviewed_at=?,
                updated_at=?
            WHERE report_uid=?
            """,
            (
                admin,
                now,
                now,
                report_uid,
            ),
        )

    return {
        "status": "REPORT_REVIEWING",
        "report_uid": report_uid,
        "reviewed_by": admin,
        "message": (
            "Flood report moved to administrative review."
        ),
    }


# ============================================================
# ADMIN QUICK VERIFY
# ============================================================

@admin_router.post(
    "/reports/{report_uid}/verify"
)
def admin_verify_report(
    report_uid: str,
    admin=Depends(get_current_admin()),
):

    current = get_report(
        report_uid
    )

    if not current:
        raise HTTPException(
            status_code=404,
            detail="Flood report not found.",
        )

    now = utc_now()

    with db() as connection:

        connection.execute(
            """
            UPDATE flood_reports
            SET
                status='VERIFIED',
                reviewed_by=?,
                reviewed_at=?,
                updated_at=?
            WHERE report_uid=?
            """,
            (
                admin,
                now,
                now,
                report_uid,
            ),
        )

    return {
        "status": "REPORT_VERIFIED",
        "report_uid": report_uid,
        "verified_by": admin,
        "message": (
            "Flood report marked as verified."
        ),
    }


# ============================================================
# ADMIN QUICK REJECT
# ============================================================

@admin_router.post(
    "/reports/{report_uid}/reject"
)
def admin_reject_report(
    report_uid: str,
    req: Optional[FloodReportStatusRequest] = None,
    admin=Depends(get_current_admin()),
):

    current = get_report(
        report_uid
    )

    if not current:
        raise HTTPException(
            status_code=404,
            detail="Flood report not found.",
        )

    notes = (
        normalize_text(req.admin_notes)
        if req is not None
        else None
    )

    if notes is None:
        notes = current["admin_notes"]

    now = utc_now()

    with db() as connection:

        connection.execute(
            """
            UPDATE flood_reports
            SET
                status='REJECTED',
                admin_notes=?,
                reviewed_by=?,
                reviewed_at=?,
                updated_at=?
            WHERE report_uid=?
            """,
            (
                notes,
                admin,
                now,
                now,
                report_uid,
            ),
        )

    return {
        "status": "REPORT_REJECTED",
        "report_uid": report_uid,
        "rejected_by": admin,
        "message": (
            "Flood report rejected after administrative review."
        ),
    }


# ============================================================
# ADMIN QUICK CLOSE
# ============================================================

@admin_router.post(
    "/reports/{report_uid}/close"
)
def admin_close_report(
    report_uid: str,
    admin=Depends(get_current_admin()),
):

    current = get_report(
        report_uid
    )

    if not current:
        raise HTTPException(
            status_code=404,
            detail="Flood report not found.",
        )

    now = utc_now()

    with db() as connection:

        connection.execute(
            """
            UPDATE flood_reports
            SET
                status='CLOSED',
                reviewed_by=?,
                reviewed_at=?,
                updated_at=?
            WHERE report_uid=?
            """,
            (
                admin,
                now,
                now,
                report_uid,
            ),
        )

    return {
        "status": "REPORT_CLOSED",
        "report_uid": report_uid,
        "closed_by": admin,
    }


# ============================================================
# ADMIN DELETE REPORT
# ============================================================

@admin_router.delete(
    "/reports/{report_uid}"
)
def admin_delete_report(
    report_uid: str,
    admin=Depends(get_current_admin()),
):

    with db() as connection:

        row = connection.execute(
            """
            SELECT photo_path
            FROM flood_reports
            WHERE report_uid=?
            """,
            (report_uid,),
        ).fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail="Flood report not found.",
            )

        connection.execute(
            """
            DELETE FROM flood_reports
            WHERE report_uid=?
            """,
            (report_uid,),
        )

    photo_path = row["photo_path"]

    if (
        photo_path
        and photo_path.startswith(
            "/citizen/uploads/reports/"
        )
    ):

        local_photo = (
            REPORT_UPLOAD_DIR
            /
            photo_path.rsplit(
                "/",
                1,
            )[-1]
        )

        try:
            local_photo.unlink(
                missing_ok=True
            )
        except Exception:
            pass

    return {
        "status": "REPORT_DELETED",
        "report_uid": report_uid,
        "deleted_by": admin,
        "message": (
            "Flood report deleted successfully."
        ),
    }


# ============================================================
# DIAGNOSTIC
# ============================================================

if __name__ == "__main__":

    print()
    print(
        "=========================================================="
    )
    print(
        " ODISHA FLOOD EWS — FLOOD REPORT SERVICE"
    )
    print(
        "=========================================================="
    )
    print(
        "Database:",
        DB_PATH,
    )
    print(
        "Report upload directory:",
        REPORT_UPLOAD_DIR,
    )
    print(
        "Workflow:",
        "NEW -> REVIEWING -> VERIFIED/REJECTED -> CLOSED",
    )
    print(
        "Service:",
        "READY",
    )
    print(
        "=========================================================="
    )
    print()
