# ============================================================
# ODISHA FLOOD RISK & EMERGENCY EVACUATION SYSTEM
# admin.py — v13.0
#
# ADMINISTRATION SERVICE
#
# FEATURES
#   - Admin login
#   - Dashboard statistics
#   - Citizen management
#   - Citizen activation/deactivation
#   - Emergency alert creation
#   - Alert approval/rejection
#   - Email alert delivery
#   - Message campaigns
#   - Campaign approval
#   - Campaign recipient preparation
#   - Campaign processing
#   - Campaign retry
#   - Delivery statistics
#   - Browser push integration
#   - AI draft generation placeholder
#
# IMPORTANT
#   AI-generated content NEVER broadcasts automatically.
#   Administrator approval is mandatory.
# ============================================================

import os
import secrets
import sqlite3

from datetime import (
    datetime,
    timezone,
)

from pathlib import Path
from typing import Optional

import jwt

from dotenv import load_dotenv

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)

from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from pydantic import (
    BaseModel,
    Field,
)


# ============================================================
# ENVIRONMENT
# ============================================================

BASE_DIR = Path(
    __file__
).resolve().parent

ENV_FILE = (
    BASE_DIR / ".env"
)

load_dotenv(
    ENV_FILE,
    override=True,
)


# ============================================================
# PATHS
# ============================================================

DATA_DIR = (
    BASE_DIR / "data"
)

DATA_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

DB_PATH = (
    DATA_DIR / "ews_users.db"
)


# ============================================================
# SECURITY
# ============================================================

JWT_SECRET = os.getenv(
    "EWS_JWT_SECRET",
    "",
).strip()

JWT_ALGORITHM = "HS256"

ADMIN_USERNAME = os.getenv(
    "EWS_ADMIN_USERNAME",
    "admin",
).strip()

ADMIN_PASSWORD = os.getenv(
    "EWS_ADMIN_PASSWORD",
    "",
).strip()

ADMIN_JWT_TTL_SECONDS = int(
    os.getenv(
        "EWS_ADMIN_JWT_TTL_SECONDS",
        str(12 * 60 * 60),
    )
)


if not JWT_SECRET:

    raise RuntimeError(
        "EWS_JWT_SECRET is not configured."
    )


if not ADMIN_PASSWORD:

    raise RuntimeError(
        "EWS_ADMIN_PASSWORD is not configured."
    )


# ============================================================
# DEVELOPMENT
# ============================================================

DEV_MODE = (
    os.getenv(
        "EWS_DEV_MODE",
        "true",
    )
    .strip()
    .lower()
    ==
    "true"
)


# ============================================================
# ROUTER
# ============================================================

router = APIRouter(

    prefix="/api/v1/admin",

    tags=[
        "Admin"
    ],

)


security = HTTPBearer(
    auto_error=False,
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
# HELPERS
# ============================================================

def utc_now() -> str:

    return datetime.now(
        timezone.utc
    ).isoformat()


def generate_uid(
    prefix: str,
) -> str:

    return (
        prefix
        +
        "-"
        +
        secrets.token_hex(
            6
        ).upper()
    )


def normalize_area(
    value: Optional[str],
) -> Optional[str]:

    if not value:

        return None

    value = value.strip()

    return value or None


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def init_admin_tables() -> None:

    with db() as connection:

        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS admin_users (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                username TEXT UNIQUE NOT NULL,

                password_hash TEXT NOT NULL,

                is_active INTEGER NOT NULL DEFAULT 1,

                created_at TEXT NOT NULL
            );


            CREATE TABLE IF NOT EXISTS alerts (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                alert_uid TEXT UNIQUE NOT NULL,

                title TEXT NOT NULL,

                message TEXT NOT NULL,

                area TEXT,

                severity TEXT NOT NULL,

                status TEXT NOT NULL
                    DEFAULT 'PENDING_APPROVAL',

                created_by TEXT NOT NULL,

                approved_by TEXT,

                created_at TEXT NOT NULL,

                approved_at TEXT,

                sent_at TEXT,

                delivery_status TEXT
                    DEFAULT 'NOT_SENT',

                recipients_count INTEGER
                    NOT NULL DEFAULT 0,

                delivered_count INTEGER
                    NOT NULL DEFAULT 0,

                failed_count INTEGER
                    NOT NULL DEFAULT 0
            );


            CREATE TABLE IF NOT EXISTS message_campaigns (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                campaign_uid TEXT UNIQUE NOT NULL,

                title TEXT NOT NULL,

                message TEXT NOT NULL,

                whatsapp_message TEXT,

                sms_message TEXT,

                whatsapp_content_variables TEXT,

                area TEXT,

                severity TEXT NOT NULL,

                source TEXT NOT NULL
                    DEFAULT 'ADMIN',

                ai_generated INTEGER NOT NULL
                    DEFAULT 0,

                status TEXT NOT NULL
                    DEFAULT 'DRAFT',

                created_by TEXT NOT NULL,

                approved_by TEXT,

                created_at TEXT NOT NULL,

                updated_at TEXT NOT NULL,

                approved_at TEXT,

                sent_at TEXT,

                recipients_count INTEGER
                    NOT NULL DEFAULT 0,

                delivered_count INTEGER
                    NOT NULL DEFAULT 0,

                failed_count INTEGER
                    NOT NULL DEFAULT 0
            );


            CREATE TABLE IF NOT EXISTS campaign_channels (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                campaign_uid TEXT NOT NULL,

                channel TEXT NOT NULL,

                enabled INTEGER NOT NULL DEFAULT 0,

                UNIQUE(
                    campaign_uid,
                    channel
                )
            );


            CREATE TABLE IF NOT EXISTS campaign_recipients (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                campaign_uid TEXT NOT NULL,

                user_uid TEXT NOT NULL,

                channel TEXT NOT NULL,

                destination TEXT,

                status TEXT NOT NULL
                    DEFAULT 'PENDING',

                provider_message_id TEXT,

                error_message TEXT,

                created_at TEXT NOT NULL,

                sent_at TEXT,

                delivered_at TEXT
            );


            CREATE INDEX IF NOT EXISTS
                idx_admin_alert_status
            ON alerts(status);


            CREATE INDEX IF NOT EXISTS
                idx_admin_alert_area
            ON alerts(area);


            CREATE INDEX IF NOT EXISTS
                idx_admin_campaign_status
            ON message_campaigns(status);


            CREATE INDEX IF NOT EXISTS
                idx_admin_campaign_area
            ON message_campaigns(area);


            CREATE INDEX IF NOT EXISTS
                idx_admin_recipient_campaign
            ON campaign_recipients(campaign_uid);


            CREATE INDEX IF NOT EXISTS
                idx_admin_recipient_status
            ON campaign_recipients(status);
            """
        )


init_admin_tables()


# ============================================================
# REQUEST MODELS
# ============================================================

class AdminLoginRequest(BaseModel):

    username: str = Field(
        min_length=1,
        max_length=100,
    )

    password: str = Field(
        min_length=1,
        max_length=200,
    )


class AlertCreateRequest(BaseModel):

    title: str = Field(
        min_length=3,
        max_length=150,
    )

    message: str = Field(
        min_length=5,
        max_length=5000,
    )

    area: Optional[str] = Field(
        default=None,
        max_length=120,
    )

    severity: str = Field(
        default="HIGH",
        max_length=20,
    )


class AlertApprovalRequest(BaseModel):

    approved: bool


class CitizenStatusRequest(BaseModel):

    is_active: bool


class CampaignCreateRequest(BaseModel):

    title: str = Field(
        min_length=3,
        max_length=150,
    )

    message: str = Field(
        min_length=5,
        max_length=5000,
    )

    whatsapp_message: Optional[str] = Field(
        default=None,
        max_length=4000,
    )

    sms_message: Optional[str] = Field(
        default=None,
        max_length=1000,
    )

    whatsapp_content_variables: Optional[str] = Field(
        default=None,
        max_length=4000,
    )

    area: Optional[str] = Field(
        default=None,
        max_length=120,
    )

    severity: str = Field(
        default="HIGH",
        max_length=20,
    )

    dashboard_enabled: bool = True

    email_enabled: bool = True

    whatsapp_enabled: bool = False

    sms_enabled: bool = False

    source: str = Field(
        default="ADMIN",
        max_length=30,
    )

    ai_generated: bool = False


class CampaignApprovalRequest(BaseModel):

    approved: bool


class AIDraftRequest(BaseModel):

    prompt: str = Field(
        min_length=5,
        max_length=2000,
    )

    area: Optional[str] = Field(
        default=None,
        max_length=120,
    )

    severity: str = Field(
        default="HIGH",
        max_length=20,
    )


class CampaignProcessRequest(BaseModel):

    max_recipients: int = Field(
        default=5000,
        ge=1,
        le=20000,
    )


# ============================================================
# VALIDATION
# ============================================================

ALLOWED_SEVERITIES = {
    "LOW",
    "MEDIUM",
    "HIGH",
    "CRITICAL",
}


def normalize_severity(
    value: str,
) -> str:

    severity = (
        value
        or
        "HIGH"
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


# ============================================================
# ADMIN JWT
# ============================================================

def admin_token(
    username: str,
) -> str:

    now = int(
        datetime.now(
            timezone.utc
        ).timestamp()
    )


    payload = {

        "sub":
            username,

        "role":
            "admin",

        "iat":
            now,

        "exp":
            now
            +
            ADMIN_JWT_TTL_SECONDS,

    }


    return jwt.encode(

        payload,

        JWT_SECRET,

        algorithm=
            JWT_ALGORITHM,

    )


def current_admin(

    credentials:
        Optional[
            HTTPAuthorizationCredentials
        ] = Depends(
            security
        ),

) -> str:

    if not credentials:

        raise HTTPException(

            status_code=401,

            detail="Admin login required.",

        )


    try:

        payload = jwt.decode(

            credentials.credentials,

            JWT_SECRET,

            algorithms=[
                JWT_ALGORITHM
            ],

        )

    except jwt.ExpiredSignatureError:

        raise HTTPException(

            status_code=401,

            detail=(
                "Admin session expired. "
                "Please login again."
            ),

        )

    except jwt.PyJWTError:

        raise HTTPException(

            status_code=401,

            detail="Invalid admin token.",

        )


    if payload.get(
        "role"
    ) != "admin":

        raise HTTPException(

            status_code=403,

            detail="Admin permission required.",

        )


    username = payload.get(
        "sub"
    )


    if not username:

        raise HTTPException(

            status_code=401,

            detail="Invalid admin token.",

        )


    if str(username) != ADMIN_USERNAME:

        raise HTTPException(

            status_code=401,

            detail=(
                "Admin account is not recognized."
            ),

        )


    return str(
        username
    )


# ============================================================
# CITIZEN QUERY
# ============================================================

def find_citizens(
    area: Optional[str] = None,
) -> list[dict]:

    requested_area = (

        area.strip().lower()

        if area

        else

        ""

    )


    with db() as connection:

        if requested_area:

            rows = connection.execute(

                """
                SELECT *
                FROM users
                WHERE is_active=1
                AND lower(trim(area))=?
                ORDER BY id ASC
                """,

                (
                    requested_area,
                ),

            ).fetchall()

        else:

            rows = connection.execute(

                """
                SELECT *
                FROM users
                WHERE is_active=1
                ORDER BY id ASC
                """

            ).fetchall()


    return [

        dict(row)

        for row in rows

    ]


# ============================================================
# SEND ALERT THROUGH MESSAGING SERVICE
# ============================================================

def send_alert_through_messaging(
    alert: dict,
) -> dict:

    try:

        from messaging import (
            send_email,
            send_sms,
            send_whatsapp,
        )

    except Exception as error:

        raise RuntimeError(
            "messaging.py could not be loaded."
        ) from error


    citizens = find_citizens(
        alert.get("area")
    )


    total = 0
    delivered = 0
    failed = 0

    errors = []


    for citizen in citizens:

        # ----------------------------------------------------
        # EMAIL
        # ----------------------------------------------------

        if (

            citizen.get(
                "email"
            )

            and

            bool(
                citizen.get(
                    "email_opt_in",
                    1,
                )
            )

        ):

            total += 1

            try:

                send_email(

                    citizen[
                        "email"
                    ],

                    (
                        "🚨 Odisha Flood EWS — "
                        f"{alert['severity']} Alert"
                    ),

                    (
                        "ODISHA FLOOD EARLY WARNING SYSTEM\n\n"

                        f"Dear {citizen.get('name') or 'Citizen'},\n\n"

                        f"Severity: {alert['severity']}\n"

                        f"Affected Area: "
                        f"{alert.get('area') or 'All areas'}\n\n"

                        f"{alert['title']}\n\n"

                        f"{alert['message']}\n\n"

                        "Please follow official disaster-management "
                        "instructions and evacuate when instructed "
                        "by the authorities.\n\n"

                        "Odisha Flood Early Warning System"
                    ),

                )

                delivered += 1

            except Exception as error:

                failed += 1

                errors.append({

                    "channel":
                        "email",

                    "user_uid":
                        citizen[
                            "user_uid"
                        ],

                    "error":
                        str(error),

                })


        # ----------------------------------------------------
        # SMS
        # ----------------------------------------------------

        if (

            citizen.get(
                "mobile"
            )

            and

            bool(
                citizen.get(
                    "sms_opt_in",
                    1,
                )
            )

        ):

            total += 1

            try:

                send_sms(

                    citizen[
                        "mobile"
                    ],

                    (
                        "ODISHA FLOOD EWS: "
                        f"{alert['severity']} ALERT. "
                        f"{alert.get('area') or 'All areas'}. "
                        f"{alert['title']}: "
                        f"{alert['message']}"
                    ),

                )

                delivered += 1

            except Exception as error:

                failed += 1

                errors.append({

                    "channel":
                        "sms",

                    "user_uid":
                        citizen[
                            "user_uid"
                        ],

                    "error":
                        str(error),

                })


        # ----------------------------------------------------
        # WHATSAPP
        # ----------------------------------------------------

        if (

            citizen.get(
                "whatsapp"
            )

            and

            bool(
                citizen.get(
                    "whatsapp_opt_in",
                    0,
                )
            )

        ):

            total += 1

            try:

                send_whatsapp(

                    citizen[
                        "whatsapp"
                    ],

                    (
                        "🚨 Odisha Flood EWS\n\n"
                        f"{alert['severity']} ALERT\n"
                        f"Area: "
                        f"{alert.get('area') or 'All areas'}\n\n"
                        f"{alert['title']}\n\n"
                        f"{alert['message']}\n\n"
                        "Follow official emergency instructions."
                    ),

                )

                delivered += 1

            except Exception as error:

                failed += 1

                errors.append({

                    "channel":
                        "whatsapp",

                    "user_uid":
                        citizen[
                            "user_uid"
                        ],

                    "error":
                        str(error),

                })


    if total == 0:

        delivery_status = (
            "NO_RECIPIENTS"
        )

    elif failed == 0:

        delivery_status = (
            "DELIVERED"
        )

    elif delivered > 0:

        delivery_status = (
            "PARTIALLY_DELIVERED"
        )

    else:

        delivery_status = (
            "FAILED"
        )


    return {

        "recipients_count":
            total,

        "delivered_count":
            delivered,

        "failed_count":
            failed,

        "delivery_status":
            delivery_status,

        "errors":
            errors,

    }


# ============================================================
# LOGIN
# ============================================================

@router.post(
    "/login"
)
def admin_login(
    req: AdminLoginRequest,
):

    username = (
        req.username
        or
        ""
    ).strip()


    if username != ADMIN_USERNAME:

        raise HTTPException(

            status_code=401,

            detail=(
                "Invalid admin username or password."
            ),

        )


    if req.password != ADMIN_PASSWORD:

        raise HTTPException(

            status_code=401,

            detail=(
                "Invalid admin username or password."
            ),

        )


    return {

        "status":
            "LOGIN_SUCCESS",

        "access_token":
            admin_token(
                username
            ),

        "token_type":
            "bearer",

        "expires_in":
            ADMIN_JWT_TTL_SECONDS,

    }


# ============================================================
# ADMIN PROFILE
# ============================================================

@router.get(
    "/me"
)
def admin_me(

    admin: str = Depends(
        current_admin
    ),

):

    return {

        "status":
            "SUCCESS",

        "username":
            admin,

        "role":
            "admin",

    }


# ============================================================
# DASHBOARD
# ============================================================

@router.get(
    "/dashboard"
)
def admin_dashboard(

    admin: str = Depends(
        current_admin
    ),

):

    with db() as connection:

        active_citizens = connection.execute(

            """
            SELECT COUNT(*)
            FROM users
            WHERE is_active=1
            """

        ).fetchone()[0]


        total_citizens = connection.execute(

            """
            SELECT COUNT(*)
            FROM users
            """

        ).fetchone()[0]


        total_alerts = connection.execute(

            """
            SELECT COUNT(*)
            FROM alerts
            """

        ).fetchone()[0]


        pending_alerts = connection.execute(

            """
            SELECT COUNT(*)
            FROM alerts
            WHERE status='PENDING_APPROVAL'
            """

        ).fetchone()[0]


        approved_alerts = connection.execute(

            """
            SELECT COUNT(*)
            FROM alerts
            WHERE status='APPROVED'
            """

        ).fetchone()[0]


        rejected_alerts = connection.execute(

            """
            SELECT COUNT(*)
            FROM alerts
            WHERE status='REJECTED'
            """

        ).fetchone()[0]


        delivered_alerts = connection.execute(

            """
            SELECT COUNT(*)
            FROM alerts
            WHERE delivery_status='DELIVERED'
            """

        ).fetchone()[0]


        total_campaigns = connection.execute(

            """
            SELECT COUNT(*)
            FROM message_campaigns
            """

        ).fetchone()[0]


        pending_campaigns = connection.execute(

            """
            SELECT COUNT(*)
            FROM message_campaigns
            WHERE status IN
            ('DRAFT', 'PENDING_APPROVAL')
            """

        ).fetchone()[0]


        approved_campaigns = connection.execute(

            """
            SELECT COUNT(*)
            FROM message_campaigns
            WHERE status='APPROVED'
            """

        ).fetchone()[0]


        delivered_messages = connection.execute(

            """
            SELECT COUNT(*)
            FROM campaign_recipients
            WHERE status='DELIVERED'
            """

        ).fetchone()[0]


        sent_messages = connection.execute(

            """
            SELECT COUNT(*)
            FROM campaign_recipients
            WHERE status='SENT'
            """

        ).fetchone()[0]


        failed_messages = connection.execute(

            """
            SELECT COUNT(*)
            FROM campaign_recipients
            WHERE status='FAILED'
            """

        ).fetchone()[0]


    return {

        "status":
            "SUCCESS",

        "admin":
            admin,

        "statistics":
            {

                "active_citizens":
                    active_citizens,

                "total_citizens":
                    total_citizens,

                "total_alerts":
                    total_alerts,

                "pending_alerts":
                    pending_alerts,

                "approved_alerts":
                    approved_alerts,

                "rejected_alerts":
                    rejected_alerts,

                "fully_delivered_alerts":
                    delivered_alerts,

                "campaigns":
                    total_campaigns,

                "pending_campaigns":
                    pending_campaigns,

                "approved_campaigns":
                    approved_campaigns,

                "delivered_messages":
                    delivered_messages,

                "sent_messages":
                    sent_messages,

                "failed_messages":
                    failed_messages,

            },

        "timestamp":
            utc_now(),

    }


# ============================================================
# CITIZEN LIST
# ============================================================

@router.get(
    "/citizens"
)
def list_citizens(

    admin: str = Depends(
        current_admin
    ),

    search: Optional[str] = Query(
        default=None,
        max_length=120,
    ),

    area: Optional[str] = Query(
        default=None,
        max_length=120,
    ),

    active_only: bool = Query(
        default=False,
    ),

):

    conditions = []

    parameters = []


    if active_only:

        conditions.append(
            "is_active=1"
        )


    if search:

        search_value = (
            "%"
            +
            search.strip().lower()
            +
            "%"
        )


        conditions.append(

            """
            (
                lower(user_uid) LIKE ?
                OR lower(name) LIKE ?
                OR lower(mobile) LIKE ?
                OR lower(email) LIKE ?
                OR lower(whatsapp) LIKE ?
                OR lower(area) LIKE ?
            )
            """

        )


        parameters.extend([

            search_value,
            search_value,
            search_value,
            search_value,
            search_value,
            search_value,

        ])


    if area:

        conditions.append(
            "lower(trim(area))=?"
        )

        parameters.append(
            area.strip().lower()
        )


    where_clause = ""


    if conditions:

        where_clause = (
            "WHERE "
            +
            " AND ".join(
                conditions
            )
        )


    with db() as connection:

        rows = connection.execute(

            f"""
            SELECT
                user_uid,
                name,
                mobile,
                whatsapp,
                email,
                area,
                latitude,
                longitude,
                profile_picture,
                is_mobile_verified,
                is_email_verified,
                is_active,
                whatsapp_opt_in,
                email_opt_in,
                sms_opt_in,
                dashboard_opt_in,
                preferred_language,
                created_at,
                updated_at
            FROM users
            {where_clause}
            ORDER BY id DESC
            LIMIT 1000
            """,

            tuple(
                parameters
            ),

        ).fetchall()


    return {

        "status":
            "SUCCESS",

        "count":
            len(rows),

        "citizens":
            [
                dict(row)
                for row in rows
            ],

    }


# ============================================================
# SINGLE CITIZEN
# ============================================================

@router.get(
    "/citizens/{user_uid}"
)
def get_citizen(

    user_uid: str,

    admin: str = Depends(
        current_admin
    ),

):

    with db() as connection:

        row = connection.execute(

            """
            SELECT
                user_uid,
                name,
                mobile,
                whatsapp,
                email,
                area,
                latitude,
                longitude,
                profile_picture,
                is_mobile_verified,
                is_email_verified,
                is_active,
                whatsapp_opt_in,
                email_opt_in,
                sms_opt_in,
                dashboard_opt_in,
                preferred_language,
                created_at,
                updated_at
            FROM users
            WHERE user_uid=?
            """,

            (
                user_uid,
            ),

        ).fetchone()


    if not row:

        raise HTTPException(

            status_code=404,

            detail="Citizen not found.",

        )


    return {

        "status":
            "SUCCESS",

        "citizen":
            dict(row),

    }


# ============================================================
# CITIZEN ACTIVE / INACTIVE
# ============================================================

@router.patch(
    "/citizens/{user_uid}/status"
)
def update_citizen_status(

    user_uid: str,

    req: CitizenStatusRequest,

    admin: str = Depends(
        current_admin
    ),

):

    with db() as connection:

        cursor = connection.execute(

            """
            UPDATE users
            SET
                is_active=?,
                updated_at=?
            WHERE user_uid=?
            """,

            (

                int(
                    req.is_active
                ),

                utc_now(),

                user_uid,

            ),

        )


        if cursor.rowcount == 0:

            raise HTTPException(

                status_code=404,

                detail="Citizen not found.",

            )


    return {

        "status":
            "UPDATED",

        "user_uid":
            user_uid,

        "is_active":
            req.is_active,

        "message":
            "Citizen status updated successfully.",

    }


# ============================================================
# CREATE ALERT
# ============================================================

@router.post(
    "/alerts"
)
def create_alert(

    req: AlertCreateRequest,

    admin: str = Depends(
        current_admin
    ),

):

    title = req.title.strip()

    message = req.message.strip()

    area = normalize_area(
        req.area
    )

    severity = normalize_severity(
        req.severity
    )


    if not title:

        raise HTTPException(

            status_code=400,

            detail="Alert title is required.",

        )


    if not message:

        raise HTTPException(

            status_code=400,

            detail="Alert message is required.",

        )


    alert_uid = generate_uid(
        "ALT"
    )

    now = utc_now()


    with db() as connection:

        connection.execute(

            """
            INSERT INTO alerts
            (
                alert_uid,
                title,
                message,
                area,
                severity,
                status,
                created_by,
                created_at,
                delivery_status,
                recipients_count,
                delivered_count,
                failed_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,

            (

                alert_uid,

                title,

                message,

                area,

                severity,

                "PENDING_APPROVAL",

                admin,

                now,

                "NOT_SENT",

                0,

                0,

                0,

            ),

        )


    return {

        "status":
            "ALERT_CREATED",

        "alert_uid":
            alert_uid,

        "approval_required":
            True,

        "delivery_status":
            "NOT_SENT",

        "message":
            (
                "Alert created and is waiting "
                "for administrator approval."
            ),

    }


# ============================================================
# APPROVE ALERT
# ============================================================

@router.post(
    "/alerts/{alert_uid}/approval"
)
def approve_alert(

    alert_uid: str,

    req: AlertApprovalRequest,

    admin: str = Depends(
        current_admin
    ),

):

    with db() as connection:

        alert = connection.execute(

            """
            SELECT *
            FROM alerts
            WHERE alert_uid=?
            """,

            (
                alert_uid,
            ),

        ).fetchone()


    if not alert:

        raise HTTPException(

            status_code=404,

            detail="Alert not found.",

        )


    if alert[
        "status"
    ] != "PENDING_APPROVAL":

        raise HTTPException(

            status_code=409,

            detail=(
                "This alert is no longer "
                "awaiting approval."
            ),

        )


    now = utc_now()


    # --------------------------------------------------------
    # REJECT
    # --------------------------------------------------------

    if not req.approved:

        with db() as connection:

            connection.execute(

                """
                UPDATE alerts
                SET
                    status='REJECTED',
                    approved_by=?,
                    approved_at=?,
                    delivery_status='NOT_SENT'
                WHERE alert_uid=?
                """,

                (

                    admin,

                    now,

                    alert_uid,

                ),

            )


        return {

            "status":
                "SUCCESS",

            "alert_uid":
                alert_uid,

            "approved":
                False,

            "delivery_status":
                "NOT_SENT",

            "message":
                (
                    "Alert rejected. "
                    "No notification was sent."
                ),

        }


    # --------------------------------------------------------
    # APPROVE
    # --------------------------------------------------------

    with db() as connection:

        connection.execute(

            """
            UPDATE alerts
            SET
                status='APPROVED',
                approved_by=?,
                approved_at=?
            WHERE alert_uid=?
            """,

            (

                admin,

                now,

                alert_uid,

            ),

        )


    # --------------------------------------------------------
    # DELIVER
    # --------------------------------------------------------

    delivery = send_alert_through_messaging(

        dict(
            alert
        )

    )


    sent_at = utc_now()


    with db() as connection:

        connection.execute(

            """
            UPDATE alerts
            SET
                sent_at=?,
                delivery_status=?,
                recipients_count=?,
                delivered_count=?,
                failed_count=?
            WHERE alert_uid=?
            """,

            (

                sent_at,

                delivery[
                    "delivery_status"
                ],

                delivery[
                    "recipients_count"
                ],

                delivery[
                    "delivered_count"
                ],

                delivery[
                    "failed_count"
                ],

                alert_uid,

            ),

        )


    return {

        "status":
            "SUCCESS",

        "alert_uid":
            alert_uid,

        "approved":
            True,

        "delivery_status":
            delivery[
                "delivery_status"
            ],

        "recipients_count":
            delivery[
                "recipients_count"
            ],

        "delivered_count":
            delivery[
                "delivered_count"
            ],

        "failed_count":
            delivery[
                "failed_count"
            ],

        "message":
            (
                "Alert approved and notification "
                "delivery completed."
            ),

        "delivery_errors":
            (
                delivery[
                    "errors"
                ]
                if DEV_MODE
                else
                []
            ),

    }


# ============================================================
# RESEND ALERT
# ============================================================

@router.post(
    "/alerts/{alert_uid}/resend"
)
def resend_alert(

    alert_uid: str,

    admin: str = Depends(
        current_admin
    ),

):

    with db() as connection:

        alert = connection.execute(

            """
            SELECT *
            FROM alerts
            WHERE alert_uid=?
            """,

            (
                alert_uid,
            ),

        ).fetchone()


    if not alert:

        raise HTTPException(

            status_code=404,

            detail="Alert not found.",

        )


    if alert[
        "status"
    ] != "APPROVED":

        raise HTTPException(

            status_code=409,

            detail=(
                "Only approved alerts "
                "can be resent."
            ),

        )


    delivery = send_alert_through_messaging(

        dict(
            alert
        )

    )


    now = utc_now()


    with db() as connection:

        connection.execute(

            """
            UPDATE alerts
            SET
                sent_at=?,
                delivery_status=?,
                recipients_count=?,
                delivered_count=?,
                failed_count=?
            WHERE alert_uid=?
            """,

            (

                now,

                delivery[
                    "delivery_status"
                ],

                delivery[
                    "recipients_count"
                ],

                delivery[
                    "delivered_count"
                ],

                delivery[
                    "failed_count"
                ],

                alert_uid,

            ),

        )


    return {

        "status":
            "SUCCESS",

        "alert_uid":
            alert_uid,

        "delivery_status":
            delivery[
                "delivery_status"
            ],

        "recipients_count":
            delivery[
                "recipients_count"
            ],

        "delivered_count":
            delivery[
                "delivered_count"
            ],

        "failed_count":
            delivery[
                "failed_count"
            ],

        "message":
            "Alert resend completed.",

        "delivery_errors":
            (
                delivery[
                    "errors"
                ]
                if DEV_MODE
                else
                []
            ),

    }


# ============================================================
# LIST ALERTS
# ============================================================

@router.get(
    "/alerts"
)
def list_alerts(

    admin: str = Depends(
        current_admin
    ),

):

    with db() as connection:

        rows = connection.execute(

            """
            SELECT
                id,
                alert_uid,
                title,
                message,
                area,
                severity,
                status,
                created_by,
                approved_by,
                created_at,
                approved_at,
                sent_at,
                delivery_status,
                recipients_count,
                delivered_count,
                failed_count
            FROM alerts
            ORDER BY id DESC
            LIMIT 1000
            """

        ).fetchall()


    return {

        "status":
            "SUCCESS",

        "alerts":
            [
                dict(row)
                for row in rows
            ],

    }


# ============================================================
# GET ALERT
# ============================================================

@router.get(
    "/alerts/{alert_uid}"
)
def get_alert(

    alert_uid: str,

    admin: str = Depends(
        current_admin
    ),

):

    with db() as connection:

        row = connection.execute(

            """
            SELECT *
            FROM alerts
            WHERE alert_uid=?
            """,

            (
                alert_uid,
            ),

        ).fetchone()


    if not row:

        raise HTTPException(

            status_code=404,

            detail="Alert not found.",

        )


    return {

        "status":
            "SUCCESS",

        "alert":
            dict(row),

    }


# ============================================================
# CREATE CAMPAIGN
# ============================================================

@router.post(
    "/campaigns"
)
def create_campaign(

    req: CampaignCreateRequest,

    admin: str = Depends(
        current_admin
    ),

):

    title = req.title.strip()

    message = req.message.strip()

    whatsapp_message = (

        req.whatsapp_message.strip()

        if req.whatsapp_message

        else

        None

    )


    sms_message = (

        req.sms_message.strip()

        if req.sms_message

        else

        None

    )


    area = normalize_area(
        req.area
    )


    severity = normalize_severity(
        req.severity
    )


    if not title:

        raise HTTPException(

            status_code=400,

            detail="Campaign title is required.",

        )


    if not message:

        raise HTTPException(

            status_code=400,

            detail="Campaign message is required.",

        )


    if (

        req.whatsapp_enabled

        and

        not whatsapp_message

    ):

        raise HTTPException(

            status_code=400,

            detail=(
                "WhatsApp message is required "
                "when WhatsApp is enabled."
            ),

        )


    if (

        req.sms_enabled

        and

        not sms_message

    ):

        raise HTTPException(

            status_code=400,

            detail=(
                "SMS message is required "
                "when SMS is enabled."
            ),

        )


    campaign_uid = generate_uid(
        "CMP"
    )

    now = utc_now()


    with db() as connection:

        connection.execute(

            """
            INSERT INTO message_campaigns
            (
                campaign_uid,
                title,
                message,
                whatsapp_message,
                sms_message,
                whatsapp_content_variables,
                area,
                severity,
                source,
                ai_generated,
                status,
                created_by,
                created_at,
                updated_at
            )
            VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,

            (

                campaign_uid,

                title,

                message,

                whatsapp_message,

                sms_message,

                req.whatsapp_content_variables,

                area,

                severity,

                (
                    req.source
                    or
                    "ADMIN"
                ).strip().upper(),

                int(
                    req.ai_generated
                ),

                "DRAFT",

                admin,

                now,

                now,

            ),

        )


        channels = {

            "dashboard":
                req.dashboard_enabled,

            "email":
                req.email_enabled,

            "whatsapp":
                req.whatsapp_enabled,

            "sms":
                req.sms_enabled,

        }


        for channel, enabled in channels.items():

            connection.execute(

                """
                INSERT OR REPLACE INTO campaign_channels
                (
                    campaign_uid,
                    channel,
                    enabled
                )
                VALUES (?, ?, ?)
                """,

                (

                    campaign_uid,

                    channel,

                    int(enabled),

                ),

            )


    return {

        "status":
            "CAMPAIGN_CREATED",

        "campaign_uid":
            campaign_uid,

        "approval_required":
            True,

        "message":
            (
                "Campaign saved as a draft. "
                "Administrator approval is required."
            ),

        "channels":
            channels,

    }


# ============================================================
# AI DRAFT
# ============================================================

@router.post(
    "/campaigns/ai-draft"
)
def create_ai_draft(

    req: AIDraftRequest,

    admin: str = Depends(
        current_admin
    ),

):

    severity = normalize_severity(
        req.severity
    )


    prompt = req.prompt.strip()

    area = normalize_area(
        req.area
    )


    if not prompt:

        raise HTTPException(

            status_code=400,

            detail="AI prompt is required.",

        )


    area_text = (
        area
        or
        "the affected area"
    )


    title = (

        f"{severity.title()} Flood "
        f"Safety Notification — "
        f"{area_text}"

    )


    message = (

        f"Emergency information for "
        f"{area_text}. "

        f"{prompt} "

        "Please avoid flooded roads and "
        "low-lying areas, monitor official "
        "disaster-management instructions, "
        "and evacuate to a safe location "
        "if authorities issue an order."

    )


    whatsapp_message = (

        "🚨 Odisha Flood EWS\n\n"

        f"{severity} ALERT\n"

        f"Area: {area_text}\n\n"

        f"{prompt}\n\n"

        "Follow official emergency instructions."

    )


    sms_message = (

        "ODISHA FLOOD EWS: "

        f"{severity} alert for "

        f"{area_text}. "

        f"{prompt}"

    )


    return {

        "status":
            "AI_DRAFT_CREATED",

        "draft":

            {

                "title":
                    title,

                "message":
                    message,

                "whatsapp_message":
                    whatsapp_message,

                "sms_message":
                    sms_message,

                "area":
                    area,

                "severity":
                    severity,

                "ai_generated":
                    True,

                "requires_admin_review":
                    True,

            },

        "message":
            (
                "AI draft created. "
                "Review and approve before sending."
            ),

    }


# ============================================================
# LIST CAMPAIGNS
# ============================================================

@router.get(
    "/campaigns"
)
def list_campaigns(

    admin: str = Depends(
        current_admin
    ),

):

    with db() as connection:

        rows = connection.execute(

            """
            SELECT *
            FROM message_campaigns
            ORDER BY id DESC
            LIMIT 1000
            """

        ).fetchall()


    campaigns = []


    for row in rows:

        campaign = dict(
            row
        )


        channels = connection.execute(

            """
            SELECT
                channel,
                enabled
            FROM campaign_channels
            WHERE campaign_uid=?
            """,

            (
                row[
                    "campaign_uid"
                ],
            ),

        ).fetchall()


        campaign[
            "channels"
        ] = {

            channel[
                "channel"
            ]:
                bool(
                    channel[
                        "enabled"
                    ]
                )

            for channel in channels

        }


        campaigns.append(
            campaign
        )


    return {

        "status":
            "SUCCESS",

        "campaigns":
            campaigns,

    }


# ============================================================
# SINGLE CAMPAIGN
# ============================================================

@router.get(
    "/campaigns/{campaign_uid}"
)
def get_campaign(

    campaign_uid: str,

    admin: str = Depends(
        current_admin
    ),

):

    with db() as connection:

        campaign = connection.execute(

            """
            SELECT *
            FROM message_campaigns
            WHERE campaign_uid=?
            """,

            (
                campaign_uid,
            ),

        ).fetchone()


        if not campaign:

            raise HTTPException(

                status_code=404,

                detail="Campaign not found.",

            )


        channels = connection.execute(

            """
            SELECT
                channel,
                enabled
            FROM campaign_channels
            WHERE campaign_uid=?
            """,

            (
                campaign_uid,
            ),

        ).fetchall()


        summary = connection.execute(

            """
            SELECT
                channel,
                status,
                COUNT(*) AS count
            FROM campaign_recipients
            WHERE campaign_uid=?
            GROUP BY channel, status
            ORDER BY channel, status
            """,

            (
                campaign_uid,
            ),

        ).fetchall()


    return {

        "status":
            "SUCCESS",

        "campaign":
            dict(
                campaign
            ),

        "channels":
            {

                row[
                    "channel"
                ]:
                    bool(
                        row[
                            "enabled"
                        ]
                    )

                for row in channels

            },

        "recipient_summary":
            [
                dict(row)
                for row in summary
            ],

    }


# ============================================================
# CAMPAIGN RECIPIENT PREVIEW
# ============================================================

@router.get(
    "/campaigns/{campaign_uid}/recipients/preview"
)
def campaign_recipient_preview(

    campaign_uid: str,

    admin: str = Depends(
        current_admin
    ),

):

    with db() as connection:

        campaign = connection.execute(

            """
            SELECT *
            FROM message_campaigns
            WHERE campaign_uid=?
            """,

            (
                campaign_uid,
            ),

        ).fetchone()


        if not campaign:

            raise HTTPException(

                status_code=404,

                detail="Campaign not found.",

            )


        channels_rows = connection.execute(

            """
            SELECT
                channel,
                enabled
            FROM campaign_channels
            WHERE campaign_uid=?
            """,

            (
                campaign_uid,
            ),

        ).fetchall()


    channels = {

        row[
            "channel"
        ]:
            bool(
                row[
                    "enabled"
                ]
            )

        for row in channels_rows

    }


    citizens = find_citizens_for_area(

        campaign[
            "area"
        ]

    )


    preview = []


    for citizen in citizens:

        if (

            channels.get(
                "dashboard"
            )

            and

            bool(
                citizen.get(
                    "dashboard_opt_in",
                    1,
                )
            )

        ):

            preview.append({

                "user_uid":
                    citizen[
                        "user_uid"
                    ],

                "name":
                    citizen.get(
                        "name"
                    ),

                "channel":
                    "dashboard",

                "destination":
                    citizen[
                        "user_uid"
                    ],

            })


        if (

            channels.get(
                "email"
            )

            and

            citizen.get(
                "email"
            )

            and

            bool(
                citizen.get(
                    "email_opt_in",
                    1,
                )
            )

        ):

            preview.append({

                "user_uid":
                    citizen[
                        "user_uid"
                    ],

                "name":
                    citizen.get(
                        "name"
                    ),

                "channel":
                    "email",

                "destination":
                    citizen[
                        "email"
                    ],

            })


        if (

            channels.get(
                "whatsapp"
            )

            and

            citizen.get(
                "whatsapp"
            )

            and

            bool(
                citizen.get(
                    "whatsapp_opt_in",
                    0,
                )
            )

        ):

            preview.append({

                "user_uid":
                    citizen[
                        "user_uid"
                    ],

                "name":
                    citizen.get(
                        "name"
                    ),

                "channel":
                    "whatsapp",

                "destination":
                    citizen[
                        "whatsapp"
                    ],

            })


        if (

            channels.get(
                "sms"
            )

            and

            citizen.get(
                "mobile"
            )

            and

            bool(
                citizen.get(
                    "sms_opt_in",
                    1,
                )
            )

        ):

            preview.append({

                "user_uid":
                    citizen[
                        "user_uid"
                    ],

                "name":
                    citizen.get(
                        "name"
                    ),

                "channel":
                    "sms",

                "destination":
                    citizen[
                        "mobile"
                    ],

            })


    return {

        "status":
            "SUCCESS",

        "campaign_uid":
            campaign_uid,

        "count":
            len(
                preview
            ),

        "recipients":
            preview[
                :2000
            ],

    }


# ============================================================
# APPROVE / REJECT CAMPAIGN
# ============================================================

@router.post(
    "/campaigns/{campaign_uid}/approval"
)
def approve_campaign(

    campaign_uid: str,

    req: CampaignApprovalRequest,

    admin: str = Depends(
        current_admin
    ),

):

    with db() as connection:

        campaign = connection.execute(

            """
            SELECT *
            FROM message_campaigns
            WHERE campaign_uid=?
            """,

            (
                campaign_uid,
            ),

        ).fetchone()


    if not campaign:

        raise HTTPException(

            status_code=404,

            detail="Campaign not found.",

        )


    if campaign[
        "status"
    ] not in {

        "DRAFT",
        "PENDING_APPROVAL",

    }:

        raise HTTPException(

            status_code=409,

            detail=(
                "This campaign is no longer "
                "awaiting approval."
            ),

        )


    now = utc_now()


    # --------------------------------------------------------
    # REJECT
    # --------------------------------------------------------

    if not req.approved:

        with db() as connection:

            connection.execute(

                """
                UPDATE message_campaigns
                SET
                    status='REJECTED',
                    approved_by=?,
                    approved_at=?,
                    updated_at=?
                WHERE campaign_uid=?
                """,

                (

                    admin,

                    now,

                    now,

                    campaign_uid,

                ),

            )


        return {

            "status":
                "SUCCESS",

            "campaign_uid":
                campaign_uid,

            "approved":
                False,

            "message":
                (
                    "Campaign rejected. "
                    "No notifications were sent."
                ),

        }


    # --------------------------------------------------------
    # APPROVE
    # --------------------------------------------------------

    with db() as connection:

        connection.execute(

            """
            UPDATE message_campaigns
            SET
                status='APPROVED',
                approved_by=?,
                approved_at=?,
                updated_at=?
            WHERE campaign_uid=?
            """,

            (

                admin,

                now,

                now,

                campaign_uid,

            ),

        )


    # --------------------------------------------------------
    # PREPARE + PROCESS
    # --------------------------------------------------------

    try:

        from messaging import (
            process_campaign,
        )


        result = process_campaign(

            campaign_uid,

            max_recipients=
                5000,

        )


        return {

            "status":
                "SUCCESS",

            "campaign_uid":
                campaign_uid,

            "approved":
                True,

            "delivery_status":
                "PROCESSED",

            "processing":
                result,

            "message":
                (
                    "Campaign approved and "
                    "delivery processing started."
                ),

        }


    except Exception as error:

        return {

            "status":
                "APPROVED",

            "campaign_uid":
                campaign_uid,

            "approved":
                True,

            "delivery_status":
                "READY_FOR_RETRY",

            "message":
                (
                    "Campaign approved, but "
                    "delivery processing could not "
                    "complete."
                ),

            "error":
                (
                    str(error)
                    if DEV_MODE
                    else
                    "Delivery processing failed."
                ),

        }


# ============================================================
# PROCESS CAMPAIGN MANUALLY
# ============================================================

@router.post(
    "/campaigns/{campaign_uid}/process"
)
def process_campaign_endpoint(

    campaign_uid: str,

    req: CampaignProcessRequest,

    admin: str = Depends(
        current_admin
    ),

):

    try:

        from messaging import (
            process_campaign,
        )


        result = process_campaign(

            campaign_uid,

            max_recipients=
                req.max_recipients,

        )


    except ValueError as error:

        raise HTTPException(

            status_code=409,

            detail=str(error),

        )


    except Exception as error:

        raise HTTPException(

            status_code=503,

            detail=(

                str(error)

                if DEV_MODE

                else

                "Campaign delivery processing failed."

            ),

        )


    return {

        "status":
            "SUCCESS",

        "processed_by":
            admin,

        **result,

    }


# ============================================================
# RETRY FAILED CAMPAIGN
# ============================================================

@router.post(
    "/campaigns/{campaign_uid}/retry"
)
def retry_campaign(

    campaign_uid: str,

    req: CampaignProcessRequest,

    admin: str = Depends(
        current_admin
    ),

):

    try:

        from messaging import (
            retry_failed_campaign,
        )


        result = retry_failed_campaign(

            campaign_uid,

            max_recipients=
                req.max_recipients,

        )


    except ValueError as error:

        raise HTTPException(

            status_code=409,

            detail=str(error),

        )


    except Exception as error:

        raise HTTPException(

            status_code=503,

            detail=(

                str(error)

                if DEV_MODE

                else
                "Campaign retry failed."

            ),

        )


    return {

        "status":
            "SUCCESS",

        "processed_by":
            admin,

        **result,

    }


# ============================================================
# DELIVERY STATUS
# ============================================================

@router.get(
    "/campaigns/{campaign_uid}/delivery"
)
def campaign_delivery(

    campaign_uid: str,

    admin: str = Depends(
        current_admin
    ),

):

    with db() as connection:

        campaign = connection.execute(

            """
            SELECT *
            FROM message_campaigns
            WHERE campaign_uid=?
            """,

            (
                campaign_uid,
            ),

        ).fetchone()


        if not campaign:

            raise HTTPException(

                status_code=404,

                detail="Campaign not found.",

            )


        summary = connection.execute(

            """
            SELECT
                channel,
                status,
                COUNT(*) AS count
            FROM campaign_recipients
            WHERE campaign_uid=?
            GROUP BY channel, status
            ORDER BY channel, status
            """,

            (
                campaign_uid,
            ),

        ).fetchall()


        recipients = connection.execute(

            """
            SELECT
                user_uid,
                channel,
                destination,
                status,
                provider_message_id,
                error_message,
                created_at,
                sent_at,
                delivered_at
            FROM campaign_recipients
            WHERE campaign_uid=?
            ORDER BY id DESC
            LIMIT 2000
            """,

            (
                campaign_uid,
            ),

        ).fetchall()


    return {

        "status":
            "SUCCESS",

        "campaign_uid":
            campaign_uid,

        "campaign":
            dict(
                campaign
            ),

        "summary":
            [
                dict(row)
                for row in summary
            ],

        "recipients":
            [
                dict(row)
                for row in recipients
            ],

    }


# ============================================================
# PREPARE RECIPIENTS
# ============================================================

@router.post(
    "/campaigns/{campaign_uid}/prepare-recipients"
)
def prepare_campaign_recipients(

    campaign_uid: str,

    admin: str = Depends(
        current_admin
    ),

):

    with db() as connection:

        campaign = connection.execute(

            """
            SELECT *
            FROM message_campaigns
            WHERE campaign_uid=?
            """,

            (
                campaign_uid,
            ),

        ).fetchone()


        if not campaign:

            raise HTTPException(

                status_code=404,

                detail="Campaign not found.",

            )


    if campaign[
        "status"
    ] != "APPROVED":

        raise HTTPException(

            status_code=409,

            detail=(
                "Campaign must be approved "
                "before recipients are prepared."
            ),

        )


    try:

        from messaging import (
            prepare_campaign,
        )


        result = prepare_campaign(
            campaign_uid
        )


    except ValueError as error:

        raise HTTPException(

            status_code=409,

            detail=str(error),

        )


    except Exception as error:

        raise HTTPException(

            status_code=503,

            detail=(

                str(error)

                if DEV_MODE

                else
                "Recipient preparation failed."

            ),

        )


    result[
        "prepared_by"
    ] = admin


    return result


# ============================================================
# CONFIGURATION
# ============================================================

@router.get(
    "/configuration"
)
def configuration_status(

    admin: str = Depends(
        current_admin
    ),

):

    email_ready = False
    sms_ready = False
    whatsapp_ready = False
    push_ready = False
    captcha_ready = False


    try:

        from users import (

            email_available,

            sms_available,

            whatsapp_available,

        )


        email_ready = bool(
            email_available()
        )

        sms_ready = bool(
            sms_available()
        )

        whatsapp_ready = bool(
            whatsapp_available()
        )


    except Exception:

        pass


    try:

        from push import (
            push_configured,
        )


        push_ready = bool(
            push_configured()
        )


    except Exception:

        pass


    try:

        from captcha import (
            turnstile_fully_configured,
        )


        captcha_ready = bool(
            turnstile_fully_configured()
        )


    except Exception:

        pass


    return {

        "status":
            "SUCCESS",

        "channels":
            {

                "dashboard":
                    True,

                "email":
                    email_ready,

                "whatsapp":
                    whatsapp_ready,

                "sms":
                    sms_ready,

                "push":
                    push_ready,

            },

        "captcha":
            {

                "turnstile":
                    captcha_ready,

            },

        "ai":
            {

                "approval_required":
                    True,

            },

        "admin":
            admin,

    }


# ============================================================
# PUSH CONFIGURATION
# ============================================================

@router.get(
    "/push/configuration"
)
def push_configuration(

    admin: str = Depends(
        current_admin
    ),

):

    try:

        from push import (
            push_configured,
        )


        configured = bool(
            push_configured()
        )


        with db() as connection:

            active_subscriptions = connection.execute(

                """
                SELECT COUNT(*)
                FROM push_subscriptions
                WHERE is_active=1
                """

            ).fetchone()[0]


            active_users = connection.execute(

                """
                SELECT COUNT(DISTINCT user_uid)
                FROM push_subscriptions
                WHERE is_active=1
                """

            ).fetchone()[0]


        return {

            "status":
                "SUCCESS",

            "configured":
                configured,

            "provider":
                "Web Push / VAPID",

            "active_subscriptions":
                active_subscriptions,

            "active_users":
                active_users,

        }


    except Exception as error:

        raise HTTPException(

            status_code=503,

            detail=(

                str(error)

                if DEV_MODE

                else
                "Push service is unavailable."

            ),

        )


# ============================================================
# ADMIN PUSH BROADCAST
# ============================================================

@router.post(
    "/push/broadcast"
)
def admin_push_broadcast(

    payload: dict,

    admin: str = Depends(
        current_admin
    ),

):

    try:

        from push import (
            broadcast_push,
        )

    except Exception as error:

        raise HTTPException(

            status_code=503,

            detail=(
                "Push service is unavailable."
            ),

        ) from error


    title = str(
        payload.get(
            "title",
            "",
        )
        or
        ""
    ).strip()


    body = str(
        payload.get(
            "body",
            "",
        )
        or
        ""
    ).strip()


    area = (
        str(
            payload.get(
                "area",
                "",
            )
            or
            ""
        ).strip()
        or
        None
    )


    severity = normalize_severity(
        str(
            payload.get(
                "severity",
                "HIGH",
            )
        )
    )


    if not title:

        raise HTTPException(

            status_code=400,

            detail="Push title is required.",

        )


    if not body:

        raise HTTPException(

            status_code=400,

            detail="Push body is required.",

        )


    try:

        result = broadcast_push(

            title=title,

            body=body,

            url=str(
                payload.get(
                    "url",
                    "/",
                )
                or
                "/"
            ),

            severity=severity,

            area=area,

            alarm_seconds=int(
                payload.get(
                    "alarm_seconds",
                    8,
                )
            ),

            require_interaction=bool(
                payload.get(
                    "require_interaction",
                    True,
                )
            ),

        )


    except Exception as error:

        raise HTTPException(

            status_code=503,

            detail=(

                str(error)

                if DEV_MODE

                else
                "Push broadcast failed."

            ),

        )


    result[
        "approved_by"
    ] = admin


    return result


# ============================================================
# HEALTH
# ============================================================

@router.get(
    "/health"
)
def admin_health(

    admin: str = Depends(
        current_admin
    ),

):

    return {

        "status":
            "OK",

        "admin":
            admin,

        "service":
            "Admin Control Centre",

        "timestamp":
            utc_now(),

    }


# ============================================================
# DIAGNOSTIC
# ============================================================

if __name__ == "__main__":

    print(
        "=============================================="
    )

    print(
        "Odisha Flood EWS — Admin Service"
    )

    print(
        "=============================================="
    )

    print(
        "Database:",
        DB_PATH,
    )

    print(
        "Admin username:",
        ADMIN_USERNAME,
    )

    print(
        "Development mode:",
        DEV_MODE,
    )

    print(
        "=============================================="
    )