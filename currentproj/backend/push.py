# ============================================================
# ODISHA FLOOD RISK & EMERGENCY EVACUATION SYSTEM
# push.py — FINAL
#
# WEB PUSH / VAPID NOTIFICATION SERVICE
# ============================================================

import json
import os
import sqlite3

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional

from dotenv import load_dotenv

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field


# ============================================================
# ENVIRONMENT
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

load_dotenv(
    ENV_FILE,
    override=True,
)


# ============================================================
# DATABASE
# ============================================================

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

DB_PATH = DATA_DIR / "ews_users.db"


# ============================================================
# VAPID
# ============================================================

VAPID_PUBLIC_KEY = os.getenv(
    "EWS_VAPID_PUBLIC_KEY",
    "",
).strip()

VAPID_PRIVATE_KEY = os.getenv(
    "EWS_VAPID_PRIVATE_KEY",
    "",
).strip()

VAPID_EMAIL = os.getenv(
    "EWS_VAPID_EMAIL",
    "",
).strip()


# ============================================================
# ROUTERS
# ============================================================

citizen_router = APIRouter(
    prefix="/api/v1/citizen",
    tags=["Citizen Push"],
)

admin_router = APIRouter(
    prefix="/api/v1/admin",
    tags=["Admin Push"],
)


# ============================================================
# AUTHENTICATION
# ============================================================

from users import current_user
from admin import current_admin


# ============================================================
# DATABASE HELPERS
# ============================================================

def db() -> sqlite3.Connection:
    connection = sqlite3.connect(
        DB_PATH,
        timeout=20,
    )

    connection.row_factory = sqlite3.Row

    connection.execute(
        "PRAGMA busy_timeout = 20000"
    )

    return connection


@contextmanager
def database() -> Generator[
    sqlite3.Connection,
    None,
    None,
]:
    connection = db()

    try:
        yield connection
        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


# ============================================================
# TIME
# ============================================================

def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


# ============================================================
# CONFIGURATION
# ============================================================

def push_configured() -> bool:
    return bool(
        VAPID_PUBLIC_KEY
        and VAPID_PRIVATE_KEY
        and VAPID_EMAIL
    )


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def init_push_table() -> None:
    with database() as connection:

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS push_subscriptions (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_uid TEXT NOT NULL,

                endpoint TEXT UNIQUE NOT NULL,

                p256dh TEXT NOT NULL,

                auth TEXT NOT NULL,

                user_agent TEXT,

                created_at TEXT NOT NULL,

                updated_at TEXT NOT NULL,

                last_success_at TEXT,

                last_failure_at TEXT,

                failure_count INTEGER
                    NOT NULL DEFAULT 0,

                is_active INTEGER
                    NOT NULL DEFAULT 1
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_push_user
            ON push_subscriptions(user_uid)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_push_active
            ON push_subscriptions(is_active)
            """
        )


init_push_table()


# ============================================================
# REQUEST MODELS
# ============================================================

class PushSubscriptionKeys(BaseModel):
    p256dh: str = Field(
        min_length=20,
        max_length=500,
    )

    auth: str = Field(
        min_length=10,
        max_length=500,
    )


class PushSubscriptionRequest(BaseModel):
    endpoint: str = Field(
        min_length=20,
        max_length=2000,
    )

    keys: PushSubscriptionKeys

    expirationTime: Optional[float] = None

    user_agent: Optional[str] = Field(
        default=None,
        max_length=1000,
    )


class PushUnsubscribeRequest(BaseModel):
    endpoint: str = Field(
        min_length=20,
        max_length=2000,
    )


class PushNotificationRequest(BaseModel):
    title: str = Field(
        min_length=1,
        max_length=200,
    )

    body: str = Field(
        min_length=1,
        max_length=3000,
    )

    url: str = Field(
        default="/citizen/",
        max_length=1000,
    )

    severity: str = Field(
        default="INFO",
        max_length=20,
    )

    area: Optional[str] = Field(
        default=None,
        max_length=120,
    )

    alarm_seconds: int = Field(
        default=8,
        ge=0,
        le=30,
    )

    require_interaction: bool = True


class AdminBroadcastPushRequest(
    PushNotificationRequest
):
    pass


class AdminUserPushRequest(
    PushNotificationRequest
):
    user_uid: str = Field(
        min_length=3,
        max_length=100,
    )


# ============================================================
# VALIDATION
# ============================================================

ALLOWED_SEVERITIES = {
    "INFO",
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
        or "INFO"
    ).strip().upper()

    if severity not in ALLOWED_SEVERITIES:

        raise HTTPException(
            status_code=400,
            detail=(
                "Severity must be INFO, LOW, MEDIUM, "
                "HIGH or CRITICAL."
            ),
        )

    return severity


# ============================================================
# SUBSCRIPTION VALIDATION
# ============================================================

def validate_subscription(
    subscription: PushSubscriptionRequest,
) -> dict:

    endpoint = (
        subscription.endpoint
        or ""
    ).strip()

    p256dh = (
        subscription.keys.p256dh
        or ""
    ).strip()

    auth = (
        subscription.keys.auth
        or ""
    ).strip()

    if not endpoint:
        raise HTTPException(
            status_code=400,
            detail="Push endpoint is required.",
        )

    if not p256dh:
        raise HTTPException(
            status_code=400,
            detail="Push p256dh key is required.",
        )

    if not auth:
        raise HTTPException(
            status_code=400,
            detail="Push auth key is required.",
        )

    return {
        "endpoint": endpoint,
        "p256dh": p256dh,
        "auth": auth,
        "expiration_time": subscription.expirationTime,
        "user_agent": subscription.user_agent,
    }


# ============================================================
# SAVE SUBSCRIPTION
# ============================================================

def save_push_subscription(
    user_uid: str,
    subscription: dict,
) -> None:

    now = utc_now()

    with database() as connection:

        existing = connection.execute(
            """
            SELECT id
            FROM push_subscriptions
            WHERE endpoint=?
            """,
            (
                subscription["endpoint"],
            ),
        ).fetchone()

        if existing:

            connection.execute(
                """
                UPDATE push_subscriptions
                SET
                    user_uid=?,
                    p256dh=?,
                    auth=?,
                    user_agent=?,
                    updated_at=?,
                    is_active=1,
                    failure_count=0
                WHERE endpoint=?
                """,
                (
                    user_uid,
                    subscription["p256dh"],
                    subscription["auth"],
                    subscription.get(
                        "user_agent"
                    ),
                    now,
                    subscription["endpoint"],
                ),
            )

        else:

            connection.execute(
                """
                INSERT INTO push_subscriptions
                (
                    user_uid,
                    endpoint,
                    p256dh,
                    auth,
                    user_agent,
                    created_at,
                    updated_at,
                    is_active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    user_uid,
                    subscription["endpoint"],
                    subscription["p256dh"],
                    subscription["auth"],
                    subscription.get(
                        "user_agent"
                    ),
                    now,
                    now,
                ),
            )


# ============================================================
# DEACTIVATE SUBSCRIPTION
# ============================================================

def deactivate_subscription(
    user_uid: str,
    endpoint: str,
) -> bool:

    with database() as connection:

        cursor = connection.execute(
            """
            UPDATE push_subscriptions
            SET
                is_active=0,
                updated_at=?
            WHERE user_uid=?
            AND endpoint=?
            """,
            (
                utc_now(),
                user_uid,
                endpoint,
            ),
        )

    return cursor.rowcount > 0


# ============================================================
# GET USER SUBSCRIPTIONS
# ============================================================

def get_user_subscriptions(
    user_uid: str,
) -> list[dict]:

    with database() as connection:

        rows = connection.execute(
            """
            SELECT
                id,
                user_uid,
                endpoint,
                p256dh,
                auth,
                user_agent,
                created_at,
                updated_at,
                last_success_at,
                last_failure_at,
                failure_count,
                is_active
            FROM push_subscriptions
            WHERE user_uid=?
            AND is_active=1
            ORDER BY id DESC
            """,
            (
                user_uid,
            ),
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


# ============================================================
# PUSH PAYLOAD
# ============================================================

def build_push_payload(
    title: str,
    body: str,
    url: str,
    severity: str,
    area: Optional[str],
    alarm_seconds: int,
    require_interaction: bool,
) -> str:

    severity = normalize_severity(
        severity
    )

    if severity == "CRITICAL":

        vibration = [
            700,
            120,
            700,
            120,
            700,
            120,
            1000,
            150,
            1000,
        ]

    elif severity == "HIGH":

        vibration = [
            500,
            120,
            500,
            120,
            700,
        ]

    elif severity == "MEDIUM":

        vibration = [
            350,
            150,
            350,
        ]

    else:

        vibration = [
            200,
            100,
            200,
        ]

    payload = {
        "type":
            "EWS_EMERGENCY_NOTIFICATION",

        "title":
            title,

        "body":
            body,

        "url":
            url
            or
            "/citizen/",

        "severity":
            severity,

        "area":
            area
            or
            "All areas",

        "alarm_seconds":
            max(
                0,
                min(
                    int(alarm_seconds),
                    30,
                ),
            ),

        "requireInteraction":
            bool(
                require_interaction
            ),

        "timestamp":
            utc_now(),

        "vibrate":
            vibration,
    }

    return json.dumps(
        payload,
        ensure_ascii=False,
    )


# ============================================================
# SEND ONE PUSH
# ============================================================

def send_one_push(
    subscription: dict,
    payload: str,
) -> None:

    if not push_configured():

        raise RuntimeError(
            "Web Push is not configured. "
            "Check EWS_VAPID_PUBLIC_KEY, "
            "EWS_VAPID_PRIVATE_KEY and "
            "EWS_VAPID_EMAIL in .env."
        )

    try:

        from pywebpush import webpush

    except ImportError as error:

        raise RuntimeError(
            "pywebpush is not installed. "
            "Run: python -m pip install pywebpush"
        ) from error

    subscription_info = {

        "endpoint":
            subscription["endpoint"],

        "keys": {

            "p256dh":
                subscription["p256dh"],

            "auth":
                subscription["auth"],

        },

    }

    try:

        webpush(

            subscription_info=
                subscription_info,

            data=
                payload,

            vapid_private_key=
                VAPID_PRIVATE_KEY,

            vapid_claims={
                "sub":
                    VAPID_EMAIL,
            },

        )

    except Exception as error:

        raise RuntimeError(
            str(error)
        ) from error


# ============================================================
# SUCCESS
# ============================================================

def mark_push_success(
    subscription_id: int,
) -> None:

    now = utc_now()

    with database() as connection:

        connection.execute(
            """
            UPDATE push_subscriptions
            SET
                last_success_at=?,
                failure_count=0,
                is_active=1,
                updated_at=?
            WHERE id=?
            """,
            (
                now,
                now,
                subscription_id,
            ),
        )


# ============================================================
# FAILURE
# ============================================================

def mark_push_failure(
    subscription_id: int,
    permanent: bool = False,
) -> None:

    now = utc_now()

    with database() as connection:

        connection.execute(
            """
            UPDATE push_subscriptions
            SET
                last_failure_at=?,
                failure_count=failure_count+1,
                is_active=?,
                updated_at=?
            WHERE id=?
            """,
            (
                now,
                0 if permanent else 1,
                now,
                subscription_id,
            ),
        )


# ============================================================
# SEND TO ONE USER
# ============================================================

def send_push_to_user(
    user_uid: str,
    title: str,
    body: str,
    url: str = "/citizen/",
    severity: str = "INFO",
    area: Optional[str] = None,
    alarm_seconds: int = 8,
    require_interaction: bool = True,
) -> dict:

    subscriptions = get_user_subscriptions(
        user_uid
    )

    if not subscriptions:

        return {
            "status":
                "NO_SUBSCRIPTIONS",

            "user_uid":
                user_uid,

            "subscriptions":
                0,

            "sent":
                0,

            "failed":
                0,

            "errors":
                [],
        }

    payload = build_push_payload(
        title=title,
        body=body,
        url=url,
        severity=severity,
        area=area,
        alarm_seconds=alarm_seconds,
        require_interaction=require_interaction,
    )

    sent = 0
    failed = 0
    errors = []

    for subscription in subscriptions:

        try:

            send_one_push(
                subscription,
                payload,
            )

            mark_push_success(
                int(
                    subscription["id"]
                )
            )

            sent += 1

        except Exception as error:

            failed += 1

            error_text = str(
                error
            )

            lower_error = (
                error_text.lower()
            )

            permanent = (
                "404" in error_text
                or
                "410" in error_text
                or
                "gone" in lower_error
                or
                "not found" in lower_error
                or
                "unregistered" in lower_error
            )

            mark_push_failure(
                int(
                    subscription["id"]
                ),
                permanent=permanent,
            )

            errors.append(
                {
                    "subscription_id":
                        subscription["id"],

                    "error":
                        error_text,
                }
            )

    if sent == 0:

        status = "FAILED"

    elif failed > 0:

        status = "PARTIALLY_DELIVERED"

    else:

        status = "DELIVERED"

    return {
        "status":
            status,

        "user_uid":
            user_uid,

        "subscriptions":
            len(subscriptions),

        "sent":
            sent,

        "failed":
            failed,

        "errors":
            errors,
    }


# ============================================================
# ACTIVE SUBSCRIPTIONS
# ============================================================

def get_active_subscriptions(
    area: Optional[str] = None,
) -> list[dict]:

    requested_area = (
        area.strip().lower()
        if area
        else
        ""
    )

    with database() as connection:

        if requested_area:

            rows = connection.execute(
                """
                SELECT
                    p.id,
                    p.user_uid,
                    p.endpoint,
                    p.p256dh,
                    p.auth,
                    p.user_agent
                FROM push_subscriptions p
                INNER JOIN users u
                    ON u.user_uid=p.user_uid
                WHERE p.is_active=1
                AND u.is_active=1
                AND (
                    u.dashboard_opt_in=1
                    OR u.dashboard_opt_in IS NULL
                )
                AND (
                    u.area IS NULL
                    OR trim(u.area)=''
                    OR lower(trim(u.area))=?
                )
                ORDER BY p.id ASC
                """,
                (
                    requested_area,
                ),
            ).fetchall()

        else:

            rows = connection.execute(
                """
                SELECT
                    p.id,
                    p.user_uid,
                    p.endpoint,
                    p.p256dh,
                    p.auth,
                    p.user_agent
                FROM push_subscriptions p
                INNER JOIN users u
                    ON u.user_uid=p.user_uid
                WHERE p.is_active=1
                AND u.is_active=1
                AND (
                    u.dashboard_opt_in=1
                    OR u.dashboard_opt_in IS NULL
                )
                ORDER BY p.id ASC
                """
            ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


# ============================================================
# BROADCAST
# ============================================================

def broadcast_push(
    title: str,
    body: str,
    url: str = "/citizen/",
    severity: str = "HIGH",
    area: Optional[str] = None,
    alarm_seconds: int = 8,
    require_interaction: bool = True,
) -> dict:

    subscriptions = get_active_subscriptions(
        area=area
    )

    if not subscriptions:

        return {
            "status":
                "NO_RECIPIENTS",

            "recipients":
                0,

            "sent":
                0,

            "failed":
                0,

            "area":
                area,

            "errors":
                [],
        }

    payload = build_push_payload(
        title=title,
        body=body,
        url=url,
        severity=severity,
        area=area,
        alarm_seconds=alarm_seconds,
        require_interaction=require_interaction,
    )

    sent = 0
    failed = 0
    errors = []

    for subscription in subscriptions:

        try:

            send_one_push(
                subscription,
                payload,
            )

            mark_push_success(
                int(
                    subscription["id"]
                )
            )

            sent += 1

        except Exception as error:

            failed += 1

            error_text = str(
                error
            )

            lower_error = (
                error_text.lower()
            )

            permanent = (
                "404" in error_text
                or
                "410" in error_text
                or
                "gone" in lower_error
                or
                "not found" in lower_error
                or
                "unregistered" in lower_error
            )

            mark_push_failure(
                int(
                    subscription["id"]
                ),
                permanent=permanent,
            )

            errors.append(
                {
                    "user_uid":
                        subscription["user_uid"],

                    "subscription_id":
                        subscription["id"],

                    "error":
                        error_text,
                }
            )

    if sent == 0:

        status = "FAILED"

    elif failed > 0:

        status = "PARTIALLY_DELIVERED"

    else:

        status = "DELIVERED"

    return {
        "status":
            status,

        "recipients":
            len(subscriptions),

        "sent":
            sent,

        "failed":
            failed,

        "area":
            area,

        "errors":
            errors,
    }


# ============================================================
# CITIZEN — PUBLIC VAPID CONFIG
# ============================================================

@citizen_router.get(
    "/push/config"
)
def citizen_push_config(
    user=Depends(
        current_user
    ),
):

    return {

        "status":
            "SUCCESS",

        "configured":
            push_configured(),

        "provider":
            "Web Push / VAPID",

        "vapid_public_key":
            VAPID_PUBLIC_KEY
            or
            None,

    }


# ============================================================
# CITIZEN — SUBSCRIBE
# ============================================================

@citizen_router.post(
    "/push/subscribe"
)
def citizen_subscribe_push(

    req: PushSubscriptionRequest,

    user=Depends(
        current_user
    ),

):

    subscription = (
        validate_subscription(
            req
        )
    )

    save_push_subscription(

        user_uid=
            user["user_uid"],

        subscription=
            subscription,

    )

    count = len(
        get_user_subscriptions(
            user["user_uid"]
        )
    )

    return {

        "status":
            "PUSH_SUBSCRIBED",

        "configured":
            push_configured(),

        "subscription_count":
            count,

        "message":
            (
                "Emergency browser notifications "
                "have been enabled."
            ),

    }


# ============================================================
# CITIZEN — UNSUBSCRIBE
# ============================================================

@citizen_router.post(
    "/push/unsubscribe"
)
def citizen_unsubscribe_push(

    req: PushUnsubscribeRequest,

    user=Depends(
        current_user
    ),

):

    endpoint = (
        req.endpoint
        or
        ""
    ).strip()

    if not endpoint:

        raise HTTPException(
            status_code=400,
            detail=
                "Push endpoint is required.",
        )

    changed = deactivate_subscription(

        user_uid=
            user["user_uid"],

        endpoint=
            endpoint,

    )

    return {

        "status":
            "PUSH_UNSUBSCRIBED",

        "removed":
            changed,

        "message":
            (
                "Emergency browser notifications "
                "have been disabled."
            ),

    }


# ============================================================
# CITIZEN — STATUS
# ============================================================

@citizen_router.get(
    "/push/status"
)
def citizen_push_status(

    user=Depends(
        current_user
    ),

):

    subscriptions = get_user_subscriptions(

        user["user_uid"]

    )

    return {

        "status":
            "SUCCESS",

        "configured":
            push_configured(),

        "enabled":
            bool(
                subscriptions
            ),

        "subscription_count":
            len(
                subscriptions
            ),

    }


# ============================================================
# CITIZEN — TEST
# ============================================================

@citizen_router.post(
    "/push/test"
)
def citizen_test_push(

    user=Depends(
        current_user
    ),

):

    if not push_configured():

        raise HTTPException(

            status_code=503,

            detail=
                "Web Push is not configured on the server.",

        )

    return send_push_to_user(

        user_uid=
            user["user_uid"],

        title=
            "🌊 Odisha Flood EWS",

        body=
            (
                "This is a test notification. "
                "Your emergency browser push system is working."
            ),

        url=
            "/citizen/",

        severity=
            "INFO",

        area=
            user.get(
                "area"
            ),

        alarm_seconds=
            3,

        require_interaction=
            True,

    )


# ============================================================
# ADMIN — CONFIGURATION
# ============================================================

@admin_router.get(
    "/push/configuration"
)
def admin_push_configuration(

    admin=Depends(
        current_admin
    ),

):

    with database() as connection:

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
            push_configured(),

        "provider":
            "Web Push / VAPID",

        "active_subscriptions":
            active_subscriptions,

        "active_users":
            active_users,

        "vapid_public_key":
            VAPID_PUBLIC_KEY
            or
            None,

        "vapid_email":
            VAPID_EMAIL
            or
            None,

        "configured_by":
            admin,

    }


# ============================================================
# ADMIN — BROADCAST
# ============================================================

@admin_router.post(
    "/push/broadcast"
)
def admin_broadcast_push(

    req: AdminBroadcastPushRequest,

    admin=Depends(
        current_admin
    ),

):

    if not push_configured():

        raise HTTPException(

            status_code=503,

            detail=(
                "Web Push is not configured. "
                "Check your VAPID values in .env."
            ),

        )


    title = (
        req.title
        or
        ""
    ).strip()


    body = (
        req.body
        or
        ""
    ).strip()


    if not title:

        raise HTTPException(

            status_code=400,

            detail=
                "Push title is required.",

        )


    if not body:

        raise HTTPException(

            status_code=400,

            detail=
                "Push message is required.",

        )


    area = (
        req.area.strip()
        if req.area
        else
        None
    )


    result = broadcast_push(

        title=
            title,

        body=
            body,

        url=
            req.url
            or
            "/citizen/",

        severity=
            req.severity,

        area=
            area,

        alarm_seconds=
            req.alarm_seconds,

        require_interaction=
            req.require_interaction,

    )


    result[
        "approved_by"
    ] = admin


    return result


# ============================================================
# ADMIN — PUSH TO USER
# ============================================================

@admin_router.post(
    "/push/user"
)
def admin_push_user(

    req: AdminUserPushRequest,

    admin=Depends(
        current_admin
    ),

):

    if not push_configured():

        raise HTTPException(

            status_code=503,

            detail=
                "Web Push is not configured.",

        )


    with database() as connection:

        user = connection.execute(

            """
            SELECT
                user_uid,
                name,
                area,
                is_active
            FROM users
            WHERE user_uid=?
            """,

            (
                req.user_uid,
            ),

        ).fetchone()


    if not user:

        raise HTTPException(

            status_code=404,

            detail=
                "Citizen not found.",

        )


    if not user["is_active"]:

        raise HTTPException(

            status_code=409,

            detail=
                "Citizen account is inactive.",

        )


    result = send_push_to_user(

        user_uid=
            user["user_uid"],

        title=
            req.title.strip(),

        body=
            req.body.strip(),

        url=
            req.url
            or
            "/citizen/",

        severity=
            req.severity,

        area=(

            req.area.strip()

            if req.area

            else

            user["area"]

        ),

        alarm_seconds=
            req.alarm_seconds,

        require_interaction=
            req.require_interaction,

    )


    result[
        "approved_by"
    ] = admin


    return result


# ============================================================
# ADMIN — TEST BROADCAST
# ============================================================

@admin_router.post(
    "/push/test-broadcast"
)
def admin_test_broadcast(

    admin=Depends(
        current_admin
    ),

):

    if not push_configured():

        raise HTTPException(

            status_code=503,

            detail=
                "Web Push is not configured.",

        )


    result = broadcast_push(

        title=
            "🌊 Odisha Flood EWS",

        body=
            (
                "This is a system test notification. "
                "No emergency action is required."
            ),

        url=
            "/citizen/",

        severity=
            "INFO",

        area=
            None,

        alarm_seconds=
            3,

        require_interaction=
            True,

    )


    result[
        "approved_by"
    ] = admin


    return result


# ============================================================
# ADMIN — CLEANUP
# ============================================================

@admin_router.post(
    "/push/cleanup"
)
def admin_cleanup_push(

    admin=Depends(
        current_admin
    ),

):

    with database() as connection:

        removed = connection.execute(

            """
            DELETE FROM push_subscriptions
            WHERE is_active=0
            """

        ).rowcount


    return {

        "status":
            "CLEANUP_COMPLETE",

        "removed":
            removed,

        "performed_by":
            admin,

        "timestamp":
            utc_now(),

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
        " ODISHA FLOOD EWS — WEB PUSH SERVICE"
    )
    print(
        "=========================================================="
    )

    print(
        "Environment:",
        ENV_FILE,
    )

    print(
        "Database:",
        DB_PATH,
    )

    print(
        "VAPID:",
        (
            "READY"
            if push_configured()
            else
            "NOT CONFIGURED"
        ),
    )

    print(
        "Public key:",
        (
            "CONFIGURED"
            if VAPID_PUBLIC_KEY
            else
            "NOT CONFIGURED"
        ),
    )

    print(
        "Private key:",
        (
            "CONFIGURED"
            if VAPID_PRIVATE_KEY
            else
            "NOT CONFIGURED"
        ),
    )

    print(
        "VAPID email:",
        VAPID_EMAIL
        or
        "NOT CONFIGURED",
    )

    print(
        "Citizen config:",
        "/api/v1/citizen/push/config",
    )

    print(
        "Citizen subscribe:",
        "/api/v1/citizen/push/subscribe",
    )

    print(
        "Citizen status:",
        "/api/v1/citizen/push/status",
    )

    print(
        "Citizen test:",
        "/api/v1/citizen/push/test",
    )

    print(
        "Admin broadcast:",
        "/api/v1/admin/push/broadcast",
    )

    print(
        "=========================================================="
    )

    print()