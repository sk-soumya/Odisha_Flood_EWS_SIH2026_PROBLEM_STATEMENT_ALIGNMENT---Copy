# ============================================================
# ODISHA FLOOD RISK & EMERGENCY EVACUATION SYSTEM
# users.py — v13.0
#
# CITIZEN SERVICE
#
# FEATURES
#   - Citizen registration
#   - Mandatory citizen name
#   - Cloudflare Turnstile CAPTCHA
#   - OTP login / signup
#   - Email / SMS / WhatsApp delivery selection
#   - Delivery fallback when one channel fails
#   - Registration confirmation
#   - Citizen profile
#   - Profile update
#   - Profile picture upload
#   - Notification preferences
#   - Location update
#   - Area-specific alerts
#   - Logout
#
# MESSAGE CHANNELS
#   Gmail SMTP
#   Twilio SMS
#   Twilio WhatsApp
#
# IMPORTANT
#   Never put secrets in HTML.
#   Keep Twilio/Gmail/Turnstile credentials in .env.
# ============================================================


# ============================================================
# IMPORTS
# ============================================================

import hashlib
import hmac
import os
import secrets
import sqlite3
import time

from contextlib import contextmanager

from datetime import (
    datetime,
    timezone,
)

from pathlib import Path

from typing import (
    Generator,
    Optional,
)


import httpx
import jwt

from dotenv import load_dotenv


from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)


from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)


from pydantic import (
    BaseModel,
    EmailStr,
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


UPLOAD_DIR = (
    BASE_DIR
    /
    "citizen"
    /
    "uploads"
)


DATA_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


UPLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


DB_PATH = (
    DATA_DIR / "ews_users.db"
)


# ============================================================
# ROUTER
# ============================================================

router = APIRouter(

    prefix="/api/v1/citizen",

    tags=[
        "Citizen"
    ],

)


bearer_scheme = HTTPBearer(
    auto_error=False,
)


# ============================================================
# SECURITY
# ============================================================

JWT_SECRET = os.getenv(
    "EWS_JWT_SECRET",
    "",
).strip()


if not JWT_SECRET:

    raise RuntimeError(
        "EWS_JWT_SECRET is not configured."
    )


JWT_ALGORITHM = "HS256"


JWT_TTL_SECONDS = int(
    os.getenv(
        "EWS_JWT_TTL_SECONDS",
        str(24 * 60 * 60),
    )
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
# OTP
# ============================================================

OTP_TTL_SECONDS = 5 * 60

OTP_COOLDOWN_SECONDS = 30

OTP_MAX_ATTEMPTS = 5


# ============================================================
# TURNSTILE
# ============================================================

TURNSTILE_SITE_KEY = os.getenv(
    "EWS_TURNSTILE_SITE_KEY",
    "",
).strip()


TURNSTILE_SECRET_KEY = os.getenv(
    "EWS_TURNSTILE_SECRET_KEY",
    "",
).strip()


TURNSTILE_VERIFY_URL = (
    "https://challenges.cloudflare.com/"
    "turnstile/v0/siteverify"
)


# ============================================================
# GMAIL
# ============================================================

SMTP_HOST = os.getenv(
    "EWS_SMTP_HOST",
    "smtp.gmail.com",
).strip()


try:

    SMTP_PORT = int(
        os.getenv(
            "EWS_SMTP_PORT",
            "587",
        )
    )

except ValueError:

    SMTP_PORT = 587


SMTP_USERNAME = os.getenv(
    "EWS_SMTP_USERNAME",
    "",
).strip()


SMTP_PASSWORD = os.getenv(
    "EWS_SMTP_PASSWORD",
    "",
).strip()


SMTP_FROM_NAME = os.getenv(
    "EWS_SMTP_FROM_NAME",
    "Odisha Flood Early Warning System",
).strip()


# ============================================================
# TWILIO
# ============================================================

TWILIO_ACCOUNT_SID = os.getenv(
    "EWS_TWILIO_ACCOUNT_SID",
    "",
).strip()


TWILIO_AUTH_TOKEN = os.getenv(
    "EWS_TWILIO_AUTH_TOKEN",
    "",
).strip()


TWILIO_WHATSAPP_FROM = os.getenv(
    "EWS_TWILIO_WHATSAPP_FROM",
    "",
).strip()


TWILIO_SMS_FROM = os.getenv(
    "EWS_TWILIO_SMS_FROM",
    "",
).strip()


# Optional dedicated WhatsApp OTP template.
#
# Example:
#
# EWS_TWILIO_WHATSAPP_OTP_CONTENT_SID=HXxxxxxxxx
#
TWILIO_WHATSAPP_OTP_CONTENT_SID = os.getenv(
    "EWS_TWILIO_WHATSAPP_OTP_CONTENT_SID",
    "",
).strip()


# General WhatsApp notification template.
TWILIO_WHATSAPP_CONTENT_SID = os.getenv(
    "EWS_TWILIO_WHATSAPP_CONTENT_SID",
    "",
).strip()


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
# DATABASE HELPERS
# ============================================================

def table_columns(
    connection: sqlite3.Connection,
    table_name: str,
) -> set[str]:

    rows = connection.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    return {
        row["name"]
        for row in rows
    }


def add_column_if_missing(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:

    columns = table_columns(
        connection,
        table_name,
    )


    if column_name not in columns:

        connection.execute(
            f"""
            ALTER TABLE {table_name}
            ADD COLUMN {column_name} {definition}
            """
        )


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def init_db() -> None:

    with database() as connection:

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_uid TEXT UNIQUE NOT NULL,

                name TEXT,

                mobile TEXT UNIQUE NOT NULL,

                whatsapp TEXT,

                email TEXT,

                area TEXT,

                latitude REAL,

                longitude REAL,

                location_accuracy REAL,

                location_updated_at TEXT,

                location_source TEXT DEFAULT 'browser_gps',

                profile_picture TEXT,

                is_mobile_verified INTEGER
                    NOT NULL DEFAULT 0,

                is_email_verified INTEGER
                    NOT NULL DEFAULT 0,

                is_active INTEGER
                    NOT NULL DEFAULT 1,

                whatsapp_opt_in INTEGER
                    NOT NULL DEFAULT 0,

                email_opt_in INTEGER
                    NOT NULL DEFAULT 1,

                sms_opt_in INTEGER
                    NOT NULL DEFAULT 1,

                dashboard_opt_in INTEGER
                    NOT NULL DEFAULT 1,

                preferred_language TEXT
                    DEFAULT 'en',

                created_at TEXT NOT NULL,

                updated_at TEXT NOT NULL
            )
            """
        )


        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS otp_requests (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                destination TEXT NOT NULL,

                otp_hash TEXT NOT NULL,

                expires_at INTEGER NOT NULL,

                last_sent_at INTEGER NOT NULL,

                attempts INTEGER NOT NULL DEFAULT 0
            )
            """
        )


        connection.execute(
            """
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

                delivery_status TEXT,

                recipients_count INTEGER
                    NOT NULL DEFAULT 0,

                delivered_count INTEGER
                    NOT NULL DEFAULT 0,

                failed_count INTEGER
                    NOT NULL DEFAULT 0
            )
            """
        )


        # ----------------------------------------------------
        # Upgrade existing users table.
        # ----------------------------------------------------

        add_column_if_missing(
            connection,
            "users",
            "name",
            "TEXT",
        )


        add_column_if_missing(
            connection,
            "users",
            "profile_picture",
            "TEXT",
        )


        add_column_if_missing(
            connection,
            "users",
            "location_accuracy",
            "REAL",
        )

        add_column_if_missing(
            connection,
            "users",
            "location_updated_at",
            "TEXT",
        )

        add_column_if_missing(
            connection,
            "users",
            "location_source",
            "TEXT DEFAULT 'browser_gps'",
        )


        add_column_if_missing(
            connection,
            "users",
            "whatsapp_opt_in",
            "INTEGER NOT NULL DEFAULT 0",
        )


        add_column_if_missing(
            connection,
            "users",
            "email_opt_in",
            "INTEGER NOT NULL DEFAULT 1",
        )


        add_column_if_missing(
            connection,
            "users",
            "sms_opt_in",
            "INTEGER NOT NULL DEFAULT 1",
        )


        add_column_if_missing(
            connection,
            "users",
            "dashboard_opt_in",
            "INTEGER NOT NULL DEFAULT 1",
        )


        add_column_if_missing(
            connection,
            "users",
            "preferred_language",
            "TEXT DEFAULT 'en'",
        )


        # ----------------------------------------------------
        # Indexes.
        # ----------------------------------------------------

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_users_mobile
            ON users(mobile)
            """
        )


        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_users_email
            ON users(email)
            """
        )


        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_users_area
            ON users(area)
            """
        )


        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_otp_destination
            ON otp_requests(destination)
            """
        )


        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_alerts_status_users
            ON alerts(status)
            """
        )


init_db()


# ============================================================
# REQUEST MODELS
# ============================================================

class NotificationPreferences(BaseModel):

    email: bool = True

    sms: bool = True

    whatsapp: bool = False

    dashboard: bool = True


class SignupRequest(BaseModel):

    name: str = Field(
        min_length=2,
        max_length=100,
    )

    mobile: str = Field(
        min_length=10,
        max_length=15,
    )

    whatsapp_same: bool = True

    whatsapp: Optional[str] = Field(
        default=None,
        min_length=10,
        max_length=15,
    )

    email: Optional[EmailStr] = None

    area: Optional[str] = Field(
        default=None,
        max_length=120,
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

    preferred_language: str = Field(
        default="en",
        min_length=2,
        max_length=10,
    )

    notifications: NotificationPreferences = (
        NotificationPreferences()
    )

    captcha_token: Optional[str] = None


class SignupVerifyRequest(BaseModel):

    signup: SignupRequest

    otp: str = Field(
        min_length=6,
        max_length=6,
    )


class LoginOTPRequest(BaseModel):

    identifier: str = Field(
        min_length=1,
        max_length=150,
    )

    delivery_channel: str = Field(
        default="auto",
        max_length=20,
    )

    captcha_token: Optional[str] = None


class VerifyOTPRequest(BaseModel):

    mobile: str = Field(
        min_length=10,
        max_length=15,
    )

    otp: str = Field(
        min_length=6,
        max_length=6,
    )


class LocationUpdateRequest(BaseModel):

    latitude: float = Field(
        ge=-90,
        le=90,
    )

    longitude: float = Field(
        ge=-180,
        le=180,
    )

    accuracy: Optional[float] = Field(
        default=None,
        ge=0,
    )


class ProfileUpdateRequest(BaseModel):

    name: str = Field(
        min_length=2,
        max_length=100,
    )

    email: Optional[EmailStr] = None

    whatsapp: Optional[str] = Field(
        default=None,
        min_length=10,
        max_length=15,
    )

    area: Optional[str] = Field(
        default=None,
        max_length=120,
    )

    preferred_language: str = Field(
        default="en",
        min_length=2,
        max_length=10,
    )


class PreferencesUpdateRequest(BaseModel):

    email_opt_in: bool = True

    sms_opt_in: bool = True

    whatsapp_opt_in: bool = False

    dashboard_opt_in: bool = True


# ============================================================
# BASIC HELPERS
# ============================================================

def generate_user_uid() -> str:

    return (
        "USR-"
        +
        secrets.token_hex(6).upper()
    )


def generate_alert_uid() -> str:

    return (
        "ALT-"
        +
        secrets.token_hex(6).upper()
    )


def normalize_email(
    value: Optional[str],
) -> Optional[str]:

    if not value:

        return None

    return (
        str(value)
        .strip()
        .lower()
    )


def normalize_phone(
    value: str,
) -> str:

    digits = "".join(
        character
        for character in (
            value or ""
        )
        if character.isdigit()
    )


    if (

        digits.startswith("91")
        and
        len(digits) == 12

    ):

        digits = digits[2:]


    if len(digits) != 10:

        raise HTTPException(

            status_code=400,

            detail=(
                "Enter a valid 10-digit "
                "Indian mobile number."
            ),

        )


    if digits[0] not in "6789":

        raise HTTPException(

            status_code=400,

            detail=(
                "Enter a valid Indian mobile number."
            ),

        )


    return (
        "+91"
        +
        digits
    )


def normalize_language(
    value: str,
) -> str:

    language = (
        value
        or
        "en"
    ).strip().lower()


    allowed = {
        "en",
        "hi",
        "or",
        "bn",
        "te",
    }


    if language not in allowed:

        return "en"


    return language


# ============================================================
# CHANNEL AVAILABILITY
# ============================================================

def email_available() -> bool:

    return bool(
        SMTP_USERNAME
        and
        SMTP_PASSWORD
    )


def twilio_available() -> bool:

    return bool(
        TWILIO_ACCOUNT_SID
        and
        TWILIO_AUTH_TOKEN
    )


def sms_available() -> bool:

    return bool(
        twilio_available()
        and
        TWILIO_SMS_FROM
    )


def whatsapp_available() -> bool:

    return bool(
        twilio_available()
        and
        TWILIO_WHATSAPP_FROM
    )


# ============================================================
# TURNSTILE
# ============================================================

def turnstile_fully_configured() -> bool:

    return bool(
        TURNSTILE_SITE_KEY
        and
        TURNSTILE_SECRET_KEY
    )


async def verify_turnstile(
    token: Optional[str],
    remote_ip: Optional[str] = None,
    required: bool = True,
) -> bool:

    if not turnstile_fully_configured():

        # Development can continue without Turnstile
        # only when explicitly running in DEV_MODE.
        if DEV_MODE:

            return True

        if required:

            raise HTTPException(

                status_code=503,

                detail=(
                    "CAPTCHA service is not configured."
                ),

            )

        return False


    if not token:

        if required:

            raise HTTPException(

                status_code=400,

                detail=(
                    "Please complete the CAPTCHA."
                ),

            )

        return False


    payload = {

        "secret":
            TURNSTILE_SECRET_KEY,

        "response":
            token,

    }


    if remote_ip:

        payload[
            "remoteip"
        ] = remote_ip


    try:

        async with httpx.AsyncClient(
            timeout=10,
        ) as client:

            response = await client.post(

                TURNSTILE_VERIFY_URL,

                data=payload,

            )

            response.raise_for_status()

            result = response.json()


    except Exception as error:

        print(
            "[TURNSTILE ERROR]",
            error,
        )

        raise HTTPException(

            status_code=503,

            detail=(
                "CAPTCHA verification service "
                "is temporarily unavailable."
            ),

        ) from error


    if not result.get(
        "success",
        False,
    ):

        if required:

            raise HTTPException(

                status_code=400,

                detail=(
                    "CAPTCHA verification failed. "
                    "Please try again."
                ),

            )

        return False


    return True


# ============================================================
# OTP
# ============================================================

def make_otp() -> str:

    return (
        f"{secrets.randbelow(1_000_000):06d}"
    )


def otp_hash(
    destination: str,
    otp: str,
) -> str:

    return hmac.new(

        JWT_SECRET.encode(
            "utf-8"
        ),

        (
            f"{destination}:{otp}"
        ).encode(
            "utf-8"
        ),

        hashlib.sha256,

    ).hexdigest()


def cleanup_old_otps(
    connection: sqlite3.Connection,
    destination: Optional[str] = None,
) -> None:

    current = int(
        time.time()
    )


    if destination:

        connection.execute(

            """
            DELETE FROM otp_requests
            WHERE destination=?
            AND expires_at < ?
            """,

            (
                destination,
                current,
            ),

        )

    else:

        connection.execute(

            """
            DELETE FROM otp_requests
            WHERE expires_at < ?
            """,

            (
                current,
            ),

        )


# ============================================================
# EMAIL OTP
# ============================================================

def send_email(
    recipient: str,
    subject: str,
    body: str,
) -> None:

    if not email_available():

        raise RuntimeError(
            "Email service is not configured."
        )


    import smtplib
    from email.message import EmailMessage


    message = EmailMessage()


    message["Subject"] = (
        subject
    )


    message["From"] = (

        f"{SMTP_FROM_NAME} "
        f"<{SMTP_USERNAME}>"

    )


    message["To"] = recipient


    message.set_content(
        body
    )


    with smtplib.SMTP(

        SMTP_HOST,

        SMTP_PORT,

        timeout=15,

    ) as smtp:

        smtp.ehlo()

        smtp.starttls()

        smtp.ehlo()

        smtp.login(

            SMTP_USERNAME,

            SMTP_PASSWORD,

        )

        smtp.send_message(
            message
        )


# ============================================================
# TWILIO LOW-LEVEL
# ============================================================

def twilio_url() -> str:

    return (

        "https://api.twilio.com/2010-04-01/"
        f"Accounts/{TWILIO_ACCOUNT_SID}/"
        "Messages.json"

    )


def twilio_post(
    payload: dict,
) -> dict:

    if not twilio_available():

        raise RuntimeError(
            "Twilio is not configured."
        )


    try:

        response = httpx.post(

            twilio_url(),

            data=payload,

            auth=(

                TWILIO_ACCOUNT_SID,

                TWILIO_AUTH_TOKEN,

            ),

            timeout=20,

        )

    except httpx.HTTPError as error:

        raise RuntimeError(

            "Twilio connection failed: "
            f"{error}"

        ) from error


    try:

        result = response.json()

    except Exception:

        result = {}


    if response.status_code >= 400:

        error_message = (

            result.get(
                "message"
            )

            or

            result.get(
                "error_message"
            )

            or

            response.text

            or

            f"HTTP {response.status_code}"

        )


        error_code = result.get(
            "code"
        )


        if error_code:

            raise RuntimeError(

                f"Twilio error "
                f"{error_code}: "
                f"{error_message}"

            )


        raise RuntimeError(
            f"Twilio rejected message: "
            f"{error_message}"
        )


    sid = result.get(
        "sid"
    )


    if not sid:

        raise RuntimeError(
            "Twilio did not return a message SID."
        )


    return result


# ============================================================
# SMS
# ============================================================

def send_sms(
    recipient: str,
    body: str,
) -> str:

    if not sms_available():

        raise RuntimeError(
            "Twilio SMS is not configured."
        )


    recipient = normalize_phone(
        recipient
    )


    if not body.strip():

        raise ValueError(
            "SMS message is empty."
        )


    result = twilio_post(

        {

            "From":
                TWILIO_SMS_FROM,

            "To":
                recipient,

            "Body":
                body,

        }

    )


    return str(
        result[
            "sid"
        ]
    )


# ============================================================
# WHATSAPP
# ============================================================

def send_whatsapp(
    recipient: str,
    body: str,
    content_sid: Optional[str] = None,
    content_variables: Optional[dict] = None,
) -> str:

    if not whatsapp_available():

        raise RuntimeError(
            "Twilio WhatsApp is not configured."
        )


    recipient = normalize_phone(
        recipient
    )


    payload = {

        "From":
            TWILIO_WHATSAPP_FROM,

        "To":
            "whatsapp:"
            +
            recipient,

    }


    selected_sid = (
        content_sid
        or
        TWILIO_WHATSAPP_CONTENT_SID
    )


    # --------------------------------------------------------
    # Template path.
    # --------------------------------------------------------

    if selected_sid:

        payload[
            "ContentSid"
        ] = selected_sid


        if content_variables:

            import json


            payload[
                "ContentVariables"
            ] = json.dumps(

                content_variables,

                ensure_ascii=False,

                separators=(
                    ",",
                    ":",
                ),

            )


    else:

        if not body.strip():

            raise ValueError(
                "WhatsApp message is empty."
            )


        payload[
            "Body"
        ] = body


    result = twilio_post(
        payload
    )


    return str(
        result[
            "sid"
        ]
    )


# ============================================================
# OTP DELIVERY
# ============================================================

def choose_delivery_channels(
    requested: str,
    user: Optional[dict],
) -> list[str]:

    requested = (
        requested
        or
        "auto"
    ).strip().lower()


    if requested in {
        "email",
        "sms",
        "whatsapp",
    }:

        return [
            requested
        ]


    if user:

        channels = []


        if (

            user.get(
                "email"
            )

            and

            bool(
                user.get(
                    "email_opt_in",
                    1,
                )
            )

        ):

            channels.append(
                "email"
            )


        if (

            user.get(
                "mobile"
            )

            and

            bool(
                user.get(
                    "sms_opt_in",
                    1,
                )
            )

        ):

            channels.append(
                "sms"
            )


        if (

            user.get(
                "whatsapp"
            )

            and

            bool(
                user.get(
                    "whatsapp_opt_in",
                    0,
                )
            )

        ):

            channels.append(
                "whatsapp"
            )


        return channels


    return [
        "email",
        "sms",
        "whatsapp",
    ]


def issue_otp_record(
    destination: str,
) -> str:

    current = int(
        time.time()
    )


    with database() as connection:

        cleanup_old_otps(

            connection,

            destination,

        )


        previous = connection.execute(

            """
            SELECT last_sent_at
            FROM otp_requests
            WHERE destination=?
            ORDER BY id DESC
            LIMIT 1
            """,

            (
                destination,
            ),

        ).fetchone()


        if previous:

            elapsed = (

                current
                -
                previous[
                    "last_sent_at"
                ]

            )


            if elapsed < OTP_COOLDOWN_SECONDS:

                wait = (

                    OTP_COOLDOWN_SECONDS
                    -
                    elapsed

                )


                raise HTTPException(

                    status_code=429,

                    detail=(

                        f"Please wait "
                        f"{wait} seconds "
                        "before requesting another OTP."

                    ),

                )


        otp = make_otp()


        connection.execute(

            """
            DELETE FROM otp_requests
            WHERE destination=?
            """,

            (
                destination,
            ),

        )


        connection.execute(

            """
            INSERT INTO otp_requests
            (
                destination,
                otp_hash,
                expires_at,
                last_sent_at,
                attempts
            )
            VALUES (?, ?, ?, ?, 0)
            """,

            (

                destination,

                otp_hash(
                    destination,
                    otp,
                ),

                current
                +
                OTP_TTL_SECONDS,

                current,

            ),

        )


    return otp


def deliver_otp(
    destination: str,
    otp: str,
    purpose: str,
    channels: list[str],
    user: Optional[dict] = None,
) -> dict:

    successful = []

    failed = []


    mobile = (
        user.get(
            "mobile"
        )
        if user
        else
        destination
    )


    email = (
        user.get(
            "email"
        )
        if user
        else
        None
    )


    whatsapp = (
        user.get(
            "whatsapp"
        )
        if user
        else
        mobile
    )


    for channel in channels:

        try:

            # ------------------------------------------------
            # EMAIL
            # ------------------------------------------------

            if channel == "email":

                if not email:

                    raise RuntimeError(
                        "No email address is registered."
                    )


                send_email(

                    email,

                    (
                        "Odisha Flood EWS — "
                        f"{purpose} OTP"
                    ),

                    (
                        "ODISHA FLOOD EARLY WARNING SYSTEM\n\n"
                        f"Your {purpose.lower()} verification "
                        f"OTP is: {otp}\n\n"
                        "This OTP is valid for 5 minutes.\n\n"
                        "Never share this OTP with anyone.\n"
                        "Odisha Flood EWS staff will never "
                        "ask for your OTP.\n\n"
                        "Odisha Flood Early Warning System"
                    ),

                )


                successful.append(
                    "email"
                )


            # ------------------------------------------------
            # SMS
            # ------------------------------------------------

            elif channel == "sms":

                if not mobile:

                    raise RuntimeError(
                        "No mobile number is registered."
                    )


                send_sms(

                    mobile,

                    (
                        "ODISHA FLOOD EWS: "
                        f"Your {purpose.lower()} OTP is "
                        f"{otp}. "
                        "Valid for 5 minutes. "
                        "Do not share this OTP."
                    ),

                )


                successful.append(
                    "sms"
                )


            # ------------------------------------------------
            # WHATSAPP
            # ------------------------------------------------

            elif channel == "whatsapp":

                if not whatsapp:

                    raise RuntimeError(
                        "No WhatsApp number is registered."
                    )


                # Dedicated OTP template is preferred.
                # The template must have variable {{1}}
                # containing the OTP.
                if TWILIO_WHATSAPP_OTP_CONTENT_SID:

                    send_whatsapp(

                        whatsapp,

                        "",

                        content_sid=(
                            TWILIO_WHATSAPP_OTP_CONTENT_SID
                        ),

                        content_variables={
                            "1":
                                otp,
                        },

                    )

                else:

                    # Use body only when no OTP template is
                    # configured. WhatsApp provider rules may
                    # require an approved template outside the
                    # permitted conversation window.
                    send_whatsapp(

                        whatsapp,

                        (
                            "🌊 Odisha Flood EWS\n\n"
                            f"Your {purpose.lower()} "
                            f"OTP is: {otp}\n\n"
                            "Valid for 5 minutes. "
                            "Do not share this OTP."
                        ),

                    )


                successful.append(
                    "whatsapp"
                )


            else:

                raise RuntimeError(
                    f"Unsupported channel: {channel}"
                )


        except Exception as error:

            failed.append(

                {
                    "channel":
                        channel,

                    "error":
                        str(error),

                }

            )


    if successful:

        delivery_status = (
            "DELIVERED"
            if not failed
            else
            "PARTIAL"
        )

    else:

        delivery_status = "FAILED"


    if not successful:

        # Keep the generated OTP record intact in DEV mode
        # so development testing can continue.
        if DEV_MODE:

            print(
                "\n========================================"
            )

            print(
                "[EWS DEV OTP]",
                otp,
            )

            print(
                "========================================\n"
            )

        else:

            raise HTTPException(

                status_code=503,

                detail=(
                    "OTP could not be delivered "
                    "through the selected channels."
                ),

            )


    return {

        "status":
            delivery_status,

        "successful_channels":
            successful,

        "failed_channels":
            failed,

        "fallback_used":
            len(successful) > 0
            and
            bool(failed),

    }


# ============================================================
# VERIFY OTP
# ============================================================

def verify_otp(
    destination: str,
    otp: str,
) -> bool:

    current = int(
        time.time()
    )


    with database() as connection:

        row = connection.execute(

            """
            SELECT *
            FROM otp_requests
            WHERE destination=?
            AND expires_at>=?
            ORDER BY id DESC
            LIMIT 1
            """,

            (
                destination,
                current,
            ),

        ).fetchone()


        if not row:

            return False


        if (

            row[
                "attempts"
            ]
            >=
            OTP_MAX_ATTEMPTS

        ):

            return False


        supplied = otp_hash(

            destination,

            (
                otp
                or
                ""
            ).strip(),

        )


        if not hmac.compare_digest(

            row[
                "otp_hash"
            ],

            supplied,

        ):

            connection.execute(

                """
                UPDATE otp_requests
                SET attempts=attempts+1
                WHERE id=?
                """,

                (
                    row[
                        "id"
                    ],
                ),

            )

            return False


        connection.execute(

            """
            DELETE FROM otp_requests
            WHERE id=?
            """,

            (
                row[
                    "id"
                ],
            ),

        )


        return True


# ============================================================
# JWT
# ============================================================

def token_for(
    user_uid: str,
) -> str:

    now = int(
        time.time()
    )


    payload = {

        "sub":
            user_uid,

        "role":
            "citizen",

        "iat":
            now,

        "exp":
            now
            +
            JWT_TTL_SECONDS,

    }


    return jwt.encode(

        payload,

        JWT_SECRET,

        algorithm=
            JWT_ALGORITHM,

    )


# ============================================================
# CURRENT USER
# ============================================================

def current_user(

    credentials:
        Optional[
            HTTPAuthorizationCredentials
        ] = Depends(
            bearer_scheme
        ),

) -> sqlite3.Row:

    if not credentials:

        raise HTTPException(

            status_code=401,

            detail=(
                "Citizen login required."
            ),

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
                "Login session expired. "
                "Please login again."
            ),

        )


    except jwt.PyJWTError:

        raise HTTPException(

            status_code=401,

            detail="Invalid login token.",

        )


    if payload.get(
        "role"
    ) != "citizen":

        raise HTTPException(

            status_code=403,

            detail=(
                "Citizen permission required."
            ),

        )


    user_uid = payload.get(
        "sub"
    )


    if not user_uid:

        raise HTTPException(

            status_code=401,

            detail="Invalid login token.",

        )


    with database() as connection:

        row = connection.execute(

            """
            SELECT *
            FROM users
            WHERE user_uid=?
            AND is_active=1
            """,

            (
                user_uid,
            ),

        ).fetchone()


    if not row:

        raise HTTPException(

            status_code=401,

            detail="Citizen account not found.",

        )


    return row


# ============================================================
# SEND REGISTRATION CONFIRMATION
# ============================================================

def send_registration_confirmation(
    user: dict,
) -> dict:

    successful = []

    failed = []


    name = (
        user.get(
            "name"
        )
        or
        "Citizen"
    )


    uid = user[
        "user_uid"
    ]


    message = (

        f"Welcome {name}! 🌊\n\n"

        "Your Odisha Flood EWS citizen account "
        "has been created successfully.\n\n"

        f"Citizen ID: {uid}\n"

        f"Registered mobile: {user['mobile']}\n\n"

        "Your account will help you receive "
        "location-specific flood warnings and "
        "emergency information.\n\n"

        "Stay safe. Follow official disaster-management "
        "instructions during emergencies."

    )


    # --------------------------------------------------------
    # EMAIL
    # --------------------------------------------------------

    if (

        user.get(
            "email"
        )

        and

        bool(
            user.get(
                "email_opt_in",
                1,
            )
        )

        and

        email_available()

    ):

        try:

            send_email(

                user[
                    "email"
                ],

                "Welcome to Odisha Flood EWS",

                message,

            )

            successful.append(
                "email"
            )

        except Exception as error:

            failed.append({

                "channel":
                    "email",

                "error":
                    str(error),

            })


    # --------------------------------------------------------
    # SMS
    # --------------------------------------------------------

    if (

        user.get(
            "mobile"
        )

        and

        bool(
            user.get(
                "sms_opt_in",
                1,
            )
        )

        and

        sms_available()

    ):

        try:

            send_sms(

                user[
                    "mobile"
                ],

                (
                    "Welcome "
                    f"{name}! Odisha Flood EWS "
                    "account created successfully. "
                    f"Citizen ID: {uid}. "
                    "You will receive emergency "
                    "warnings and safety notifications."
                ),

            )

            successful.append(
                "sms"
            )

        except Exception as error:

            failed.append({

                "channel":
                    "sms",

                "error":
                    str(error),

            })


    # --------------------------------------------------------
    # WHATSAPP
    # --------------------------------------------------------

    if (

        user.get(
            "whatsapp"
        )

        and

        bool(
            user.get(
                "whatsapp_opt_in",
                0,
            )
        )

        and

        whatsapp_available()

    ):

        try:

            send_whatsapp(

                user[
                    "whatsapp"
                ],

                message,

            )

            successful.append(
                "whatsapp"
            )

        except Exception as error:

            failed.append({

                "channel":
                    "whatsapp",

                "error":
                    str(error),

            })


    return {

        "successful_channels":
            successful,

        "failed_channels":
            failed,

    }


# ============================================================
# SIGNUP REQUEST OTP
# ============================================================

@router.post(
    "/signup/request-otp"
)
async def signup_request_otp(

    req: SignupRequest,

):

    await verify_turnstile(
        req.captcha_token
    )


    name = req.name.strip()


    if not name:

        raise HTTPException(

            status_code=400,

            detail="Name is required.",

        )


    mobile = normalize_phone(
        req.mobile
    )


    if req.whatsapp_same:

        whatsapp = mobile

    else:

        if not req.whatsapp:

            raise HTTPException(

                status_code=400,

                detail=(
                    "WhatsApp number is required."
                ),

            )


        whatsapp = normalize_phone(
            req.whatsapp
        )


    email = normalize_email(
        req.email
    )


    preferred_language = normalize_language(
        req.preferred_language
    )


    with database() as connection:

        existing = connection.execute(

            """
            SELECT
                id
            FROM users
            WHERE mobile=?
            """,

            (
                mobile,
            ),

        ).fetchone()


    if existing:

        raise HTTPException(

            status_code=409,

            detail=(
                "This mobile number is already "
                "registered. Please login instead."
            ),

        )


    if email:

        with database() as connection:

            duplicate_email = connection.execute(

                """
                SELECT id
                FROM users
                WHERE lower(email)=?
                """,

                (
                    email,
                ),

            ).fetchone()


        if duplicate_email:

            raise HTTPException(

                status_code=409,

                detail=(
                    "This email address is already "
                    "registered."
                ),

            )


    # --------------------------------------------------------
    # Ensure at least one OTP channel is configured.
    # --------------------------------------------------------

    preferred_channels = []


    if req.notifications.email:

        preferred_channels.append(
            "email"
        )


    if req.notifications.sms:

        preferred_channels.append(
            "sms"
        )


    if req.notifications.whatsapp:

        preferred_channels.append(
            "whatsapp"
        )


    if not preferred_channels:

        raise HTTPException(

            status_code=400,

            detail=(
                "Select at least one OTP delivery channel."
            ),

        )


    otp = issue_otp_record(
        mobile
    )


    temp_user = {

        "name":
            name,

        "mobile":
            mobile,

        "email":
            email,

        "whatsapp":
            whatsapp,

        "email_opt_in":
            int(
                req.notifications.email
            ),

        "sms_opt_in":
            int(
                req.notifications.sms
            ),

        "whatsapp_opt_in":
            int(
                req.notifications.whatsapp
            ),

    }


    delivery = deliver_otp(

        destination=
            mobile,

        otp=
            otp,

        purpose=
            "Signup",

        channels=
            preferred_channels,

        user=
            temp_user,

    )


    response = {

        "status":
            "OTP_SENT",

        "message":
            (
                "Signup OTP has been sent."
            ),

        "delivery":
            delivery,

        "channels":
            preferred_channels,

    }


    if DEV_MODE:

        response[
            "development_note"
        ] = (
            "Development mode enabled. "
            "OTP is also printed in the server console "
            "if delivery fails."
        )


    return response


# ============================================================
# SIGNUP VERIFY OTP
# ============================================================

@router.post(
    "/signup/verify-otp"
)
async def signup_verify_otp(

    req: SignupVerifyRequest,

):

    signup = req.signup


    mobile = normalize_phone(
        signup.mobile
    )


    if not verify_otp(

        mobile,

        req.otp,

    ):

        raise HTTPException(

            status_code=400,

            detail="Invalid or expired OTP.",

        )


    name = signup.name.strip()


    if not name:

        raise HTTPException(

            status_code=400,

            detail="Name is required.",

        )


    if signup.whatsapp_same:

        whatsapp = mobile

    else:

        if not signup.whatsapp:

            raise HTTPException(

                status_code=400,

                detail=(
                    "WhatsApp number is required."
                ),

            )

        whatsapp = normalize_phone(
            signup.whatsapp
        )


    email = normalize_email(
        signup.email
    )


    preferred_language = normalize_language(
        signup.preferred_language
    )


    now = utc_now()

    uid = generate_user_uid()


    with database() as connection:

        existing = connection.execute(

            """
            SELECT id
            FROM users
            WHERE mobile=?
            """,

            (
                mobile,
            ),

        ).fetchone()


        if existing:

            raise HTTPException(

                status_code=409,

                detail=(
                    "This mobile number is already registered."
                ),

            )


        existing_uid = connection.execute(

            """
            SELECT id
            FROM users
            WHERE user_uid=?
            """,

            (
                uid,
            ),

        ).fetchone()


        if existing_uid:

            uid = generate_user_uid()


        connection.execute(

            """
            INSERT INTO users
            (
                user_uid,
                name,
                mobile,
                whatsapp,
                email,
                area,
                latitude,
                longitude,
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
            )
            VALUES
            (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,

            (

                uid,

                name,

                mobile,

                whatsapp,

                email,

                (
                    signup.area.strip()
                    if signup.area
                    else None
                ),

                signup.latitude,

                signup.longitude,

                1,

                0,

                1,

                int(
                    signup.notifications.whatsapp
                ),

                int(
                    signup.notifications.email
                ),

                int(
                    signup.notifications.sms
                ),

                int(
                    signup.notifications.dashboard
                ),

                preferred_language,

                now,

                now,

            ),

        )


    with database() as connection:

        user = connection.execute(

            """
            SELECT *
            FROM users
            WHERE user_uid=?
            """,

            (
                uid,
            ),

        ).fetchone()


    confirmation = (
        send_registration_confirmation(
            dict(user)
        )
    )


    return {

        "status":
            "REGISTERED",

        "user_id":
            uid,

        "name":
            name,

        "message":
            (
                f"Welcome {name}! "
                "Your Odisha Flood EWS citizen account "
                "has been created successfully."
            ),

        "notification_confirmation":
            confirmation,

        "email_verified":
            False,

        "mobile_verified":
            True,

    }


# ============================================================
# LOGIN REQUEST OTP
# ============================================================

@router.post(
    "/login/request-otp"
)
async def login_request_otp(

    req: LoginOTPRequest,

):

    await verify_turnstile(
        req.captcha_token
    )


    identifier = (
        req.identifier
        or
        ""
    ).strip()


    if not identifier:

        raise HTTPException(

            status_code=400,

            detail=(
                "Mobile number or email is required."
            ),

        )


    user = None


    # --------------------------------------------------------
    # Mobile
    # --------------------------------------------------------

    if (

        identifier
        .replace(
            "+",
            "",
        )
        .isdigit()

    ):

        mobile = normalize_phone(
            identifier
        )


        with database() as connection:

            row = connection.execute(

                """
                SELECT *
                FROM users
                WHERE mobile=?
                AND is_active=1
                """,

                (
                    mobile,
                ),

            ).fetchone()


        if row:

            user = dict(
                row
            )


    # --------------------------------------------------------
    # Email
    # --------------------------------------------------------

    else:

        email = normalize_email(
            identifier
        )


        with database() as connection:

            row = connection.execute(

                """
                SELECT *
                FROM users
                WHERE lower(email)=?
                AND is_active=1
                """,

                (
                    email,
                ),

            ).fetchone()


        if row:

            user = dict(
                row
            )


    if not user:

        raise HTTPException(

            status_code=404,

            detail=(
                "No active citizen account was found "
                "for this mobile number or email."
            ),

        )


    channels = choose_delivery_channels(

        req.delivery_channel,

        user,

    )


    if not channels:

        raise HTTPException(

            status_code=400,

            detail=(
                "No notification channel is available "
                "for this account."
            ),

        )


    otp = issue_otp_record(

        user[
            "mobile"
        ]

    )


    delivery = deliver_otp(

        destination=
            user[
                "mobile"
            ],

        otp=
            otp,

        purpose=
            "Login",

        channels=
            channels,

        user=
            user,

    )


    return {

        "status":
            "OTP_SENT",

        "message":
            (
                "Login OTP has been sent "
                "through the available channel(s)."
            ),

        "user_id":
            user[
                "user_uid"
            ],

        "name":
            user.get(
                "name"
            ),

        "channels":
            channels,

        "delivery":
            delivery,

    }


# ============================================================
# LOGIN VERIFY OTP
# ============================================================

@router.post(
    "/login/verify-otp"
)
def login_verify_otp(

    req: VerifyOTPRequest,

):

    mobile = normalize_phone(
        req.mobile
    )


    if not verify_otp(

        mobile,

        req.otp,

    ):

        raise HTTPException(

            status_code=400,

            detail="Invalid or expired OTP.",

        )


    with database() as connection:

        row = connection.execute(

            """
            SELECT
                user_uid,
                name,
                mobile,
                email,
                area
            FROM users
            WHERE mobile=?
            AND is_active=1
            """,

            (
                mobile,
            ),

        ).fetchone()


    if not row:

        raise HTTPException(

            status_code=404,

            detail="Citizen account not found.",

        )


    token = token_for(
        row[
            "user_uid"
        ]
    )


    return {

        "status":
            "LOGIN_SUCCESS",

        "access_token":
            token,

        "token_type":
            "bearer",

        "expires_in":
            JWT_TTL_SECONDS,

        "user":
            {

                "user_id":
                    row[
                        "user_uid"
                    ],

                "name":
                    row[
                        "name"
                    ],

                "mobile":
                    row[
                        "mobile"
                    ],

                "email":
                    row[
                        "email"
                    ],

                "area":
                    row[
                        "area"
                    ],

            },

    }


# ============================================================
# PROFILE
# ============================================================

@router.get(
    "/me"
)
def me(

    row: sqlite3.Row = Depends(
        current_user
    ),

):

    return {

        "status":
            "SUCCESS",

        "user_id":
            row[
                "user_uid"
            ],

        "name":
            row[
                "name"
            ],

        "mobile":
            row[
                "mobile"
            ],

        "whatsapp":
            row[
                "whatsapp"
            ],

        "email":
            row[
                "email"
            ],

        "area":
            row[
                "area"
            ],

        "latitude":
            row[
                "latitude"
            ],

        "longitude":
            row[
                "longitude"
            ],

        "location_accuracy":
            row[
                "location_accuracy"
            ],

        "location_updated_at":
            row[
                "location_updated_at"
            ],

        "location_source":
            row[
                "location_source"
            ],

        "profile_picture":
            row[
                "profile_picture"
            ],

        "mobile_verified":
            bool(
                row[
                    "is_mobile_verified"
                ]
            ),

        "email_verified":
            bool(
                row[
                    "is_email_verified"
                ]
            ),

        "notification_preferences":
            {

                "email":
                    bool(
                        row[
                            "email_opt_in"
                        ]
                    ),

                "sms":
                    bool(
                        row[
                            "sms_opt_in"
                        ]
                    ),

                "whatsapp":
                    bool(
                        row[
                            "whatsapp_opt_in"
                        ]
                    ),

                "dashboard":
                    bool(
                        row[
                            "dashboard_opt_in"
                        ]
                    ),

            },

        "preferred_language":
            row[
                "preferred_language"
            ],

        "created_at":
            row[
                "created_at"
            ],

        "updated_at":
            row[
                "updated_at"
            ],

    }


# ============================================================
# PROFILE UPDATE
# ============================================================

@router.put(
    "/profile"
)
def update_profile(

    req: ProfileUpdateRequest,

    row: sqlite3.Row = Depends(
        current_user
    ),

):

    name = req.name.strip()


    if not name:

        raise HTTPException(

            status_code=400,

            detail="Name is required.",

        )


    whatsapp = (

        normalize_phone(
            req.whatsapp
        )

        if req.whatsapp

        else

        row[
            "whatsapp"
        ]

    )


    email = normalize_email(
        req.email
    )


    area = (

        req.area.strip()
        if req.area
        else
        None

    )


    language = normalize_language(
        req.preferred_language
    )


    now = utc_now()


    with database() as connection:

        if email:

            duplicate = connection.execute(

                """
                SELECT id
                FROM users
                WHERE lower(email)=?
                AND user_uid!=?
                """,

                (
                    email,

                    row[
                        "user_uid"
                    ],

                ),

            ).fetchone()


            if duplicate:

                raise HTTPException(

                    status_code=409,

                    detail=(
                        "This email address is "
                        "already in use."
                    ),

                )


        connection.execute(

            """
            UPDATE users
            SET
                name=?,
                email=?,
                whatsapp=?,
                area=?,
                preferred_language=?,
                updated_at=?
            WHERE user_uid=?
            """,

            (

                name,

                email,

                whatsapp,

                area,

                language,

                now,

                row[
                    "user_uid"
                ],

            ),

        )


    return {

        "status":
            "PROFILE_UPDATED",

        "message":
            "Your profile was updated successfully.",

        "user_id":
            row[
                "user_uid"
            ],

        "name":
            name,

        "email":
            email,

        "whatsapp":
            whatsapp,

        "area":
            area,

        "preferred_language":
            language,

        "updated_at":
            now,

    }


# ============================================================
# PROFILE PHOTO UPLOAD
# ============================================================

@router.post(
    "/profile/photo"
)
async def upload_profile_photo(

    photo: UploadFile = File(...),

    row: sqlite3.Row = Depends(
        current_user
    ),

):

    allowed_types = {

        "image/jpeg":
            ".jpg",

        "image/png":
            ".png",

        "image/webp":
            ".webp",

    }


    extension = allowed_types.get(

        photo.content_type

    )


    if not extension:

        raise HTTPException(

            status_code=400,

            detail=(
                "Profile picture must be "
                "JPG, PNG or WEBP."
            ),

        )


    contents = await photo.read()


    if not contents:

        raise HTTPException(

            status_code=400,

            detail="Uploaded picture is empty.",

        )


    if len(contents) > 5 * 1024 * 1024:

        raise HTTPException(

            status_code=413,

            detail=(
                "Profile picture must be "
                "smaller than 5 MB."
            ),

        )


    filename = (

        row[
            "user_uid"
        ]

        +

        "_"

        +

        secrets.token_hex(
            5
        )

        +

        extension

    )


    destination = (
        UPLOAD_DIR
        /
        filename
    )


    with open(
        destination,
        "wb",
    ) as file:

        file.write(
            contents
        )


    public_path = (
        "/citizen/uploads/"
        +
        filename
    )


    old_picture = row[
        "profile_picture"
    ]


    with database() as connection:

        connection.execute(

            """
            UPDATE users
            SET
                profile_picture=?,
                updated_at=?
            WHERE user_uid=?
            """,

            (

                public_path,

                utc_now(),

                row[
                    "user_uid"
                ],

            ),

        )


    # Remove old local picture when possible.
    if old_picture and old_picture.startswith(
        "/citizen/uploads/"
    ):

        old_name = (
            old_picture
            .split(
                "/"
            )[-1]
        )


        old_path = (
            UPLOAD_DIR
            /
            old_name
        )


        if (

            old_path.exists()

            and

            old_path != destination

        ):

            try:

                old_path.unlink()

            except Exception:

                pass


    return {

        "status":
            "PROFILE_PHOTO_UPDATED",

        "message":
            (
                "Profile picture updated successfully."
            ),

        "profile_picture":
            public_path,

    }


# ============================================================
# NOTIFICATION PREFERENCES
# ============================================================

@router.put(
    "/preferences"
)
def update_preferences(

    req: PreferencesUpdateRequest,

    row: sqlite3.Row = Depends(
        current_user
    ),

):

    if not (

        req.email_opt_in
        or
        req.sms_opt_in
        or
        req.whatsapp_opt_in
        or
        req.dashboard_opt_in

    ):

        raise HTTPException(

            status_code=400,

            detail=(
                "At least one notification channel "
                "must remain enabled."
            ),

        )


    if req.email_opt_in and not row[
        "email"
    ]:

        # Email cannot be selected without an email.
        raise HTTPException(

            status_code=400,

            detail=(
                "Add an email address before "
                "enabling email notifications."
            ),

        )


    if req.whatsapp_opt_in and not row[
        "whatsapp"
    ]:

        raise HTTPException(

            status_code=400,

            detail=(
                "Add a WhatsApp number before "
                "enabling WhatsApp notifications."
            ),

        )


    now = utc_now()


    with database() as connection:

        connection.execute(

            """
            UPDATE users
            SET
                email_opt_in=?,
                sms_opt_in=?,
                whatsapp_opt_in=?,
                dashboard_opt_in=?,
                updated_at=?
            WHERE user_uid=?
            """,

            (

                int(
                    req.email_opt_in
                ),

                int(
                    req.sms_opt_in
                ),

                int(
                    req.whatsapp_opt_in
                ),

                int(
                    req.dashboard_opt_in
                ),

                now,

                row[
                    "user_uid"
                ],

            ),

        )


    return {

        "status":
            "PREFERENCES_UPDATED",

        "message":
            (
                "Notification preferences "
                "updated successfully."
            ),

        "preferences":
            {

                "email":
                    req.email_opt_in,

                "sms":
                    req.sms_opt_in,

                "whatsapp":
                    req.whatsapp_opt_in,

                "dashboard":
                    req.dashboard_opt_in,

            },

    }


# ============================================================
# LOCATION
# ============================================================

@router.post(
    "/location"
)
def update_location(

    req: LocationUpdateRequest,

    row: sqlite3.Row = Depends(
        current_user
    ),

):

    now = utc_now()


    with database() as connection:

        connection.execute(

            """
            UPDATE users
            SET
                latitude=?,
                longitude=?,
                location_accuracy=?,
                location_updated_at=?,
                location_source=?,
                updated_at=?
            WHERE user_uid=?
            """,

            (

                req.latitude,

                req.longitude,

                req.accuracy,

                now,

                "browser_gps",

                now,

                row[
                    "user_uid"
                ],

            ),

        )


    return {

        "status":
            "LOCATION_UPDATED",

        "user_id":
            row[
                "user_uid"
            ],

        "latitude":
            req.latitude,

        "longitude":
            req.longitude,

        "accuracy":
            req.accuracy,

        "location_updated_at":
            now,

        "location_source":
            "browser_gps",

        "message":
            (
                "Citizen location saved successfully."
            ),

    }


# ============================================================
# AI / RISK ENGINE CONTEXT
# ============================================================

@router.get(
    "/risk-context"
)
def risk_context(
    row: sqlite3.Row = Depends(
        current_user
    ),
):
    """Return authenticated citizen location context for the risk engine.

    This endpoint does not calculate flood risk. It only provides the
    citizen's latest GPS context and metadata so main.py or a future ML
    service can combine it with rainfall, radar, satellite, observations,
    NWP and other geospatial features.
    """

    return {
        "status": "SUCCESS",
        "user_id": row["user_uid"],
        "location": {
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "accuracy_m": row["location_accuracy"],
            "updated_at": row["location_updated_at"],
            "source": row["location_source"] or "browser_gps",
        },
        "area": row["area"],
    }


# ============================================================
# ACTIVE ALERTS
# ============================================================

@router.get(
    "/alerts"
)
def citizen_alerts(

    row: sqlite3.Row = Depends(
        current_user
    ),

):

    citizen_area = (

        row[
            "area"
        ]
        or
        ""
    ).strip().lower()


    with database() as connection:

        alerts = connection.execute(

            """
            SELECT
                alert_uid,
                title,
                message,
                area,
                severity,
                status,
                created_by,
                created_at,
                approved_by,
                approved_at,
                sent_at
            FROM alerts
            WHERE status='APPROVED'
            AND
            (
                area IS NULL
                OR trim(area)=''
                OR lower(trim(area))=?
            )
            ORDER BY id DESC
            LIMIT 100
            """,

            (
                citizen_area,
            ),

        ).fetchall()


    return {

        "status":
            "SUCCESS",

        "count":
            len(
                alerts
            ),

        "alerts":
            [
                dict(alert)
                for alert in alerts
            ],

    }


# ============================================================
# LOGOUT
# ============================================================

@router.post(
    "/logout"
)
def logout(

    row: sqlite3.Row = Depends(
        current_user
    ),

):

    return {

        "status":
            "LOGOUT_SUCCESS",

        "message":
            (
                "Logout successful. "
                "Remove the access token from the client."
            ),

    }


# ============================================================
# SERVICE STATUS
# ============================================================

@router.get(
    "/notification-status"
)
def notification_status(

    row: sqlite3.Row = Depends(
        current_user
    ),

):

    return {

        "status":
            "SUCCESS",

        "channels":

            {

                "email":
                    {

                        "available":
                            email_available(),

                        "selected":
                            bool(
                                row[
                                    "email_opt_in"
                                ]
                            ),

                        "destination":
                            row[
                                "email"
                            ],

                    },

                "sms":
                    {

                        "available":
                            sms_available(),

                        "selected":
                            bool(
                                row[
                                    "sms_opt_in"
                                ]
                            ),

                        "destination":
                            row[
                                "mobile"
                            ],

                    },

                "whatsapp":
                    {

                        "available":
                            whatsapp_available(),

                        "selected":
                            bool(
                                row[
                                    "whatsapp_opt_in"
                                ]
                            ),

                        "destination":
                            row[
                                "whatsapp"
                            ],

                    },

                "dashboard":
                    {

                        "available":
                            True,

                        "selected":
                            bool(
                                row[
                                    "dashboard_opt_in"
                                ]
                            ),

                    },

            },

    }


# ============================================================
# DIAGNOSTIC
# ============================================================

if __name__ == "__main__":

    print(
        "=============================================="
    )

    print(
        " Odisha Flood EWS — users.py"
    )

    print(
        "=============================================="
    )

    print(
        "Database:",
        DB_PATH,
    )

    print(
        "Turnstile:",
        (
            "READY"
            if turnstile_fully_configured()
            else
            "NOT CONFIGURED"
        ),
    )

    print(
        "Gmail:",
        (
            "READY"
            if email_available()
            else
            "NOT CONFIGURED"
        ),
    )

    print(
        "Twilio SMS:",
        (
            "READY"
            if sms_available()
            else
            "NOT CONFIGURED"
        ),
    )

    print(
        "Twilio WhatsApp:",
        (
            "READY"
            if whatsapp_available()
            else
            "NOT CONFIGURED"
        ),
    )

    print(
        "=============================================="
    )