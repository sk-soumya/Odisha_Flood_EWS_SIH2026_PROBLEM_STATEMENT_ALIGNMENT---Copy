# ============================================================
# ODISHA FLOOD RISK & EMERGENCY EVACUATION SYSTEM
# messaging.py — v13.0
#
# CENTRAL NOTIFICATION DELIVERY SERVICE
#
# CHANNELS
#   dashboard -> EWS database
#   email     -> Gmail SMTP
#   whatsapp  -> Twilio WhatsApp
#   sms       -> Twilio SMS
#
# WORKFLOW
#   Admin / AI creates draft
#           ↓
#   Administrator reviews
#           ↓
#   Administrator approves
#           ↓
#   admin.py calls process_campaign()
#           ↓
#   messaging.py sends enabled channels
#           ↓
#   Delivery status stored in SQLite
#
# IMPORTANT
#   AI never broadcasts automatically.
#   Approval is mandatory.
#
# ============================================================

import json
import os
import smtplib
import sqlite3
import time

from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

import httpx

from dotenv import load_dotenv


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
# GENERAL CONFIGURATION
# ============================================================

try:

    REQUEST_TIMEOUT = float(
        os.getenv(
            "EWS_MESSAGING_TIMEOUT",
            "20",
        )
    )

except ValueError:

    REQUEST_TIMEOUT = 20.0


USER_AGENT = os.getenv(
    "EWS_USER_AGENT",
    "OdishaFloodEWS/13.0",
).strip()


DEV_MODE = (
    os.getenv(
        "EWS_DEV_MODE",
        "true",
    ).strip().lower()
    ==
    "true"
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


TWILIO_WHATSAPP_CONTENT_SID = os.getenv(
    "EWS_TWILIO_WHATSAPP_CONTENT_SID",
    "",
).strip()


TWILIO_WHATSAPP_OTP_CONTENT_SID = os.getenv(
    "EWS_TWILIO_WHATSAPP_OTP_CONTENT_SID",
    "",
).strip()


TWILIO_WHATSAPP_CONTENT_VARIABLES = os.getenv(
    "EWS_TWILIO_WHATSAPP_CONTENT_VARIABLES",
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

def table_exists(
    connection: sqlite3.Connection,
    table_name: str,
) -> bool:

    row = connection.execute(

        """
        SELECT name
        FROM sqlite_master
        WHERE type='table'
        AND name=?
        """,

        (
            table_name,
        ),

    ).fetchone()


    return bool(
        row
    )


def table_columns(
    connection: sqlite3.Connection,
    table_name: str,
) -> set[str]:

    if not table_exists(
        connection,
        table_name,
    ):

        return set()


    rows = connection.execute(

        f"PRAGMA table_info({table_name})"

    ).fetchall()


    return {

        row[
            "name"
        ]

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
# SCHEMA
# ============================================================

def ensure_messaging_schema() -> None:

    with db() as connection:

        # ----------------------------------------------------
        # Users compatibility columns
        # ----------------------------------------------------

        if table_exists(
            connection,
            "users",
        ):

            add_column_if_missing(
                connection,
                "users",
                "name",
                "TEXT",
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
        # Campaigns
        # ----------------------------------------------------

        connection.execute(

            """
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
            )
            """

        )


        add_column_if_missing(
            connection,
            "message_campaigns",
            "whatsapp_content_variables",
            "TEXT",
        )


        # ----------------------------------------------------
        # Channels
        # ----------------------------------------------------

        connection.execute(

            """
            CREATE TABLE IF NOT EXISTS campaign_channels (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                campaign_uid TEXT NOT NULL,

                channel TEXT NOT NULL,

                enabled INTEGER NOT NULL
                    DEFAULT 0,

                UNIQUE(
                    campaign_uid,
                    channel
                )
            )
            """

        )


        # ----------------------------------------------------
        # Recipients
        # ----------------------------------------------------

        connection.execute(

            """
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
            )
            """

        )


        # ----------------------------------------------------
        # Indexes
        # ----------------------------------------------------

        connection.execute(

            """
            CREATE INDEX IF NOT EXISTS
                idx_campaign_recipient_campaign
            ON campaign_recipients(campaign_uid)
            """

        )


        connection.execute(

            """
            CREATE INDEX IF NOT EXISTS
                idx_campaign_recipient_status
            ON campaign_recipients(status)
            """

        )


        connection.execute(

            """
            CREATE INDEX IF NOT EXISTS
                idx_campaign_recipient_user
            ON campaign_recipients(user_uid)
            """

        )


ensure_messaging_schema()


# ============================================================
# PROVIDER AVAILABILITY
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
# PHONE NORMALIZATION
# ============================================================

def normalize_e164(
    value: str,
) -> str:

    value = (
        value
        or
        ""
    ).strip()


    if not value:

        raise ValueError(
            "Phone number is empty."
        )


    # +919938268156
    if value.startswith("+"):

        digits = "".join(

            char

            for char in value[1:]

            if char.isdigit()

        )


        if len(digits) < 10:

            raise ValueError(
                "Invalid phone number."
            )


        if len(digits) > 15:

            raise ValueError(
                "Phone number is too long."
            )


        return "+" + digits


    digits = "".join(

        char

        for char in value

        if char.isdigit()

    )


    # India 10-digit
    if (

        len(digits) == 10

        and

        digits[0] in "6789"

    ):

        return (
            "+91"
            +
            digits
        )


    # India with 91
    if (

        len(digits) == 12

        and

        digits.startswith("91")

    ):

        return (
            "+"
            +
            digits
        )


    if 10 <= len(digits) <= 15:

        return (
            "+"
            +
            digits
        )


    raise ValueError(
        "Invalid E.164-compatible phone number."
    )


# ============================================================
# TWILIO URL
# ============================================================

def twilio_messages_url() -> str:

    return (

        "https://api.twilio.com/"
        "2010-04-01/"
        f"Accounts/{TWILIO_ACCOUNT_SID}/"
        "Messages.json"

    )


# ============================================================
# TWILIO REQUEST
# ============================================================

def twilio_send(
    payload: dict,
) -> dict:

    if not twilio_available():

        raise RuntimeError(
            "Twilio credentials are not configured."
        )


    try:

        response = httpx.post(

            twilio_messages_url(),

            data=payload,

            auth=(

                TWILIO_ACCOUNT_SID,

                TWILIO_AUTH_TOKEN,

            ),

            timeout=REQUEST_TIMEOUT,

            headers={

                "User-Agent":
                    USER_AGENT,

            },

        )

    except httpx.HTTPError as error:

        raise RuntimeError(

            "Unable to connect to Twilio: "
            f"{error}"

        ) from error


    try:

        result = response.json()

    except Exception:

        result = {}


    if response.status_code >= 400:

        code = result.get(
            "code"
        )

        message = (

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


        if code:

            raise RuntimeError(

                f"Twilio error {code}: "
                f"{message}"

            )


        raise RuntimeError(
            f"Twilio rejected message: {message}"
        )


    sid = result.get(
        "sid"
    )


    if not sid:

        raise RuntimeError(
            "Twilio response did not contain a message SID."
        )


    return result


# ============================================================
# EMAIL
# ============================================================

def send_email(
    recipient: str,
    subject: str,
    body: str,
) -> str:

    if not email_available():

        raise RuntimeError(
            "Gmail SMTP is not configured."
        )


    recipient = (
        recipient
        or
        ""
    ).strip()


    if not recipient:

        raise ValueError(
            "Email recipient is empty."
        )


    message = EmailMessage()


    message["Subject"] = (
        subject
    )


    message["From"] = (

        f"{SMTP_FROM_NAME} "
        f"<{SMTP_USERNAME}>"

    )


    message["To"] = (
        recipient
    )


    message.set_content(
        body
    )


    with smtplib.SMTP(

        SMTP_HOST,

        SMTP_PORT,

        timeout=REQUEST_TIMEOUT,

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


    return (

        "EMAIL-"
        +
        str(
            int(
                time.time()
            )
        )

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


    phone = normalize_e164(
        recipient
    )


    payload = {

        "From":
            TWILIO_WHATSAPP_FROM,

        "To":
            "whatsapp:"
            +
            phone,

    }


    selected_sid = (

        content_sid

        or

        TWILIO_WHATSAPP_CONTENT_SID

    )


    if selected_sid:

        payload[
            "ContentSid"
        ] = selected_sid


        variables = content_variables


        if variables is None:

            if TWILIO_WHATSAPP_CONTENT_VARIABLES:

                try:

                    variables = json.loads(
                        TWILIO_WHATSAPP_CONTENT_VARIABLES
                    )

                except json.JSONDecodeError as error:

                    raise ValueError(

                        "EWS_TWILIO_WHATSAPP_CONTENT_VARIABLES "
                        "must contain valid JSON."

                    ) from error


        if variables:

            if not isinstance(
                variables,
                dict,
            ):

                raise ValueError(
                    "ContentVariables must be a JSON object."
                )


            payload[
                "ContentVariables"
            ] = json.dumps(

                variables,

                ensure_ascii=False,

                separators=(
                    ",",
                    ":",
                ),

            )


    else:

        if not body.strip():

            raise ValueError(
                "WhatsApp body is empty."
            )


        payload[
            "Body"
        ] = body


    result = twilio_send(
        payload
    )


    return str(
        result[
            "sid"
        ]
    )


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


    if not body.strip():

        raise ValueError(
            "SMS body is empty."
        )


    phone = normalize_e164(
        recipient
    )


    result = twilio_send(

        {

            "From":
                TWILIO_SMS_FROM,

            "To":
                phone,

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
# CAMPAIGN ACCESS
# ============================================================

def get_campaign(
    campaign_uid: str,
) -> Optional[dict]:

    ensure_messaging_schema()


    with db() as connection:

        row = connection.execute(

            """
            SELECT *
            FROM message_campaigns
            WHERE campaign_uid=?
            """,

            (
                campaign_uid,
            ),

        ).fetchone()


    if not row:

        return None


    return dict(
        row
    )


def get_campaign_channels(
    campaign_uid: str,
) -> dict:

    with db() as connection:

        rows = connection.execute(

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


    return {

        row[
            "channel"
        ]:
            bool(
                row[
                    "enabled"
                ]
            )

        for row in rows

    }


# ============================================================
# CITIZENS
# ============================================================

def find_citizens_for_area(
    area: Optional[str],
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
# RECIPIENT INSERTION
# ============================================================

def insert_recipient_if_missing(

    connection: sqlite3.Connection,

    campaign_uid: str,

    user_uid: str,

    channel: str,

    destination: str,

) -> bool:

    existing = connection.execute(

        """
        SELECT id
        FROM campaign_recipients
        WHERE campaign_uid=?
        AND user_uid=?
        AND channel=?
        """,

        (

            campaign_uid,

            user_uid,

            channel,

        ),

    ).fetchone()


    if existing:

        return False


    connection.execute(

        """
        INSERT INTO campaign_recipients
        (
            campaign_uid,
            user_uid,
            channel,
            destination,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, 'PENDING', ?)
        """,

        (

            campaign_uid,

            user_uid,

            channel,

            destination,

            utc_now(),

        ),

    )


    return True


# ============================================================
# PREPARE CAMPAIGN
# ============================================================

def prepare_campaign(
    campaign_uid: str,
) -> dict:

    campaign = get_campaign(
        campaign_uid
    )


    if not campaign:

        raise ValueError(
            "Campaign not found."
        )


    if campaign[
        "status"
    ] != "APPROVED":

        raise ValueError(
            "Only approved campaigns can be prepared."
        )


    channels = get_campaign_channels(
        campaign_uid
    )


    citizens = find_citizens_for_area(

        campaign.get(
            "area"
        )

    )


    created = 0


    with db() as connection:

        for citizen in citizens:

            uid = citizen[
                "user_uid"
            ]


            # ------------------------------------------------
            # Dashboard
            # ------------------------------------------------

            if (

                channels.get(
                    "dashboard",
                    False,
                )

                and

                bool(
                    citizen.get(
                        "dashboard_opt_in",
                        1,
                    )
                )

            ):

                created += int(

                    insert_recipient_if_missing(

                        connection,

                        campaign_uid,

                        uid,

                        "dashboard",

                        uid,

                    )

                )


            # ------------------------------------------------
            # Email
            # ------------------------------------------------

            email = (

                citizen.get(
                    "email"
                )
                or
                ""
            ).strip()


            if (

                channels.get(
                    "email",
                    False,
                )

                and

                email

                and

                bool(
                    citizen.get(
                        "email_opt_in",
                        1,
                    )
                )

            ):

                created += int(

                    insert_recipient_if_missing(

                        connection,

                        campaign_uid,

                        uid,

                        "email",

                        email,

                    )

                )


            # ------------------------------------------------
            # WhatsApp
            # ------------------------------------------------

            whatsapp = (

                citizen.get(
                    "whatsapp"
                )
                or
                ""
            ).strip()


            if (

                channels.get(
                    "whatsapp",
                    False,
                )

                and

                whatsapp

                and

                bool(
                    citizen.get(
                        "whatsapp_opt_in",
                        0,
                    )
                )

            ):

                created += int(

                    insert_recipient_if_missing(

                        connection,

                        campaign_uid,

                        uid,

                        "whatsapp",

                        whatsapp,

                    )

                )


            # ------------------------------------------------
            # SMS
            # ------------------------------------------------

            mobile = (

                citizen.get(
                    "mobile"
                )
                or
                ""
            ).strip()


            if (

                channels.get(
                    "sms",
                    False,
                )

                and

                mobile

                and

                bool(
                    citizen.get(
                        "sms_opt_in",
                        1,
                    )
                )

            ):

                created += int(

                    insert_recipient_if_missing(

                        connection,

                        campaign_uid,

                        uid,

                        "sms",

                        mobile,

                    )

                )


    counts = refresh_campaign_counts(
        campaign_uid
    )


    return {

        "status":
            "RECIPIENTS_PREPARED",

        "campaign_uid":
            campaign_uid,

        "new_recipients":
            created,

        **counts,

    }


# ============================================================
# RECIPIENT STATUS
# ============================================================

def update_recipient(

    recipient_id: int,

    status: str,

    provider_message_id: Optional[str] = None,

    error_message: Optional[str] = None,

    sent_at: Optional[str] = None,

    delivered_at: Optional[str] = None,

) -> None:

    with db() as connection:

        connection.execute(

            """
            UPDATE campaign_recipients
            SET
                status=?,
                provider_message_id=?,
                error_message=?,
                sent_at=COALESCE(?, sent_at),
                delivered_at=COALESCE(?, delivered_at)
            WHERE id=?
            """,

            (

                status,

                provider_message_id,

                error_message,

                sent_at,

                delivered_at,

                recipient_id,

            ),

        )


# ============================================================
# DELIVER DASHBOARD
# ============================================================

def deliver_dashboard(
    campaign: dict,
    recipient: dict,
) -> dict:

    return {

        "status":
            "DELIVERED",

        "provider_message_id":
            (
                "DASH-"
                +
                str(
                    campaign[
                        "campaign_uid"
                    ]
                )
                +
                "-"
                +
                str(
                    recipient[
                        "user_uid"
                    ]
                )
            ),

    }


# ============================================================
# DELIVER EMAIL
# ============================================================

def deliver_email(
    campaign: dict,
    recipient: dict,
) -> dict:

    area = (

        campaign.get(
            "area"
        )
        or
        "All areas"

    )


    body = (

        "ODISHA FLOOD EARLY WARNING SYSTEM\n\n"

        "EMERGENCY NOTIFICATION\n\n"

        f"Severity: {campaign['severity'].upper()}\n"

        f"Area: {area}\n\n"

        f"{campaign['title']}\n\n"

        f"{campaign['message']}\n\n"

        "Please follow official disaster-management "
        "instructions and evacuate when instructed "
        "by the authorities.\n\n"

        "Odisha Flood Early Warning System"

    )


    subject = (

        "🚨 Odisha Flood EWS — "

        f"{campaign['severity'].upper()} Alert"

    )


    provider_id = send_email(

        recipient=recipient[
            "destination"
        ],

        subject=subject,

        body=body,

    )


    return {

        "status":
            "DELIVERED",

        "provider_message_id":
            provider_id,

    }


# ============================================================
# DELIVER WHATSAPP
# ============================================================

def deliver_whatsapp(
    campaign: dict,
    recipient: dict,
) -> dict:

    body = (

        campaign.get(
            "whatsapp_message"
        )

        or

        campaign.get(
            "message"
        )

        or

        ""

    )


    variables = None


    raw_variables = campaign.get(
        "whatsapp_content_variables"
    )


    if raw_variables:

        try:

            variables = json.loads(
                raw_variables
            )

        except json.JSONDecodeError as error:

            raise ValueError(

                "Campaign WhatsApp ContentVariables "
                "must be valid JSON."

            ) from error


    provider_id = send_whatsapp(

        recipient=recipient[
            "destination"
        ],

        body=body,

        content_sid=(
            TWILIO_WHATSAPP_CONTENT_SID
            or
            None
        ),

        content_variables=variables,

    )


    return {

        # Twilio accepted the request.
        "status":
            "SENT",

        "provider_message_id":
            provider_id,

    }


# ============================================================
# DELIVER SMS
# ============================================================

def deliver_sms(
    campaign: dict,
    recipient: dict,
) -> dict:

    body = (

        campaign.get(
            "sms_message"
        )

        or

        campaign.get(
            "message"
        )

        or

        ""

    )


    provider_id = send_sms(

        recipient[
            "destination"
        ],

        body,

    )


    return {

        "status":
            "SENT",

        "provider_message_id":
            provider_id,

    }


# ============================================================
# DELIVER ONE
# ============================================================

def deliver_recipient(

    campaign: dict,

    recipient: dict,

) -> dict:

    channel = (

        recipient.get(
            "channel"
        )
        or
        ""
    ).strip().lower()


    destination = (

        recipient.get(
            "destination"
        )
        or
        ""
    ).strip()


    if not destination:

        raise RuntimeError(
            "Recipient destination is empty."
        )


    if channel == "dashboard":

        return deliver_dashboard(

            campaign,

            recipient,

        )


    if channel == "email":

        return deliver_email(

            campaign,

            recipient,

        )


    if channel == "whatsapp":

        return deliver_whatsapp(

            campaign,

            recipient,

        )


    if channel == "sms":

        return deliver_sms(

            campaign,

            recipient,

        )


    raise RuntimeError(
        f"Unsupported messaging channel: {channel}"
    )


# ============================================================
# PROCESS ONE RECIPIENT
# ============================================================

def process_recipient(

    recipient: dict,

    campaign: dict,

) -> dict:

    recipient_id = int(
        recipient[
            "id"
        ]
    )


    current_status = (

        recipient.get(
            "status"
        )
        or
        ""

    )


    if current_status == "DELIVERED":

        return {

            "status":
                "ALREADY_DELIVERED",

            "recipient_id":
                recipient_id,

        }


    started_at = utc_now()


    update_recipient(

        recipient_id,

        "PROCESSING",

        error_message=None,

    )


    try:

        result = deliver_recipient(

            campaign,

            recipient,

        )


        result_status = (

            result.get(
                "status"
            )

            or

            "SENT"

        )


        provider_id = result.get(
            "provider_message_id"
        )


        if result_status == "DELIVERED":

            update_recipient(

                recipient_id,

                "DELIVERED",

                provider_message_id=
                    provider_id,

                sent_at=
                    started_at,

                delivered_at=
                    started_at,

            )


        else:

            update_recipient(

                recipient_id,

                "SENT",

                provider_message_id=
                    provider_id,

                sent_at=
                    started_at,

            )


        return {

            "status":
                result_status,

            "recipient_id":
                recipient_id,

            "provider_message_id":
                provider_id,

        }


    except Exception as error:

        update_recipient(

            recipient_id,

            "FAILED",

            error_message=str(
                error
            ),

        )


        return {

            "status":
                "FAILED",

            "recipient_id":
                recipient_id,

            "error":
                str(
                    error
                ),

        }


# ============================================================
# COUNTERS
# ============================================================

def refresh_campaign_counts(
    campaign_uid: str,
) -> dict:

    with db() as connection:

        total = connection.execute(

            """
            SELECT COUNT(*)
            FROM campaign_recipients
            WHERE campaign_uid=?
            """,

            (
                campaign_uid,
            ),

        ).fetchone()[0]


        delivered = connection.execute(

            """
            SELECT COUNT(*)
            FROM campaign_recipients
            WHERE campaign_uid=?
            AND status='DELIVERED'
            """,

            (
                campaign_uid,
            ),

        ).fetchone()[0]


        failed = connection.execute(

            """
            SELECT COUNT(*)
            FROM campaign_recipients
            WHERE campaign_uid=?
            AND status='FAILED'
            """,

            (
                campaign_uid,
            ),

        ).fetchone()[0]


        sent = connection.execute(

            """
            SELECT COUNT(*)
            FROM campaign_recipients
            WHERE campaign_uid=?
            AND status='SENT'
            """,

            (
                campaign_uid,
            ),

        ).fetchone()[0]


        pending = connection.execute(

            """
            SELECT COUNT(*)
            FROM campaign_recipients
            WHERE campaign_uid=?
            AND status IN
            ('PENDING', 'PROCESSING')
            """,

            (
                campaign_uid,
            ),

        ).fetchone()[0]


        if total == 0:

            delivery_status = (
                "NO_RECIPIENTS"
            )

        elif pending > 0:

            delivery_status = (
                "PROCESSING"
            )

        elif delivered == total:

            delivery_status = (
                "DELIVERED"
            )

        elif failed == total:

            delivery_status = (
                "FAILED"
            )

        else:

            delivery_status = (
                "PARTIALLY_DELIVERED"
            )


        connection.execute(

            """
            UPDATE message_campaigns
            SET
                recipients_count=?,
                delivered_count=?,
                failed_count=?,
                updated_at=?
            WHERE campaign_uid=?
            """,

            (

                total,

                delivered,

                failed,

                utc_now(),

                campaign_uid,

            ),

        )


    return {

        "recipients_count":
            total,

        "delivered_count":
            delivered,

        "failed_count":
            failed,

        "sent_count":
            sent,

        "pending_count":
            pending,

        "delivery_status":
            delivery_status,

    }


# ============================================================
# PROCESS CAMPAIGN
# ============================================================

def process_campaign(

    campaign_uid: str,

    max_recipients: int = 5000,

) -> dict:

    ensure_messaging_schema()


    campaign = get_campaign(
        campaign_uid
    )


    if not campaign:

        raise ValueError(
            "Campaign not found."
        )


    if campaign.get(
        "status"
    ) != "APPROVED":

        raise ValueError(
            "Only approved campaigns can be delivered."
        )


    max_recipients = max(

        1,

        min(

            int(
                max_recipients
            ),

            20000,

        ),

    )


    preparation = prepare_campaign(
        campaign_uid
    )


    with db() as connection:

        recipients = connection.execute(

            """
            SELECT *
            FROM campaign_recipients
            WHERE campaign_uid=?
            AND status IN
            ('PENDING', 'FAILED')
            ORDER BY id ASC
            LIMIT ?
            """,

            (

                campaign_uid,

                max_recipients,

            ),

        ).fetchall()


    results = {

        "processed":
            0,

        "delivered":
            0,

        "sent":
            0,

        "failed":
            0,

        "already_delivered":
            0,

    }


    for row in recipients:

        outcome = process_recipient(

            dict(
                row
            ),

            campaign,

        )


        results[
            "processed"
        ] += 1


        status_value = outcome.get(
            "status"
        )


        if status_value == "DELIVERED":

            results[
                "delivered"
            ] += 1


        elif status_value == "SENT":

            results[
                "sent"
            ] += 1


        elif status_value == "FAILED":

            results[
                "failed"
            ] += 1


        elif status_value == "ALREADY_DELIVERED":

            results[
                "already_delivered"
            ] += 1


    delivery = refresh_campaign_counts(
        campaign_uid
    )


    if (

        delivery[
            "pending_count"
        ]
        ==
        0

    ):

        with db() as connection:

            connection.execute(

                """
                UPDATE message_campaigns
                SET
                    sent_at=COALESCE(
                        sent_at,
                        ?
                    ),
                    updated_at=?
                WHERE campaign_uid=?
                """,

                (

                    utc_now(),

                    utc_now(),

                    campaign_uid,

                ),

            )


    return {

        "status":
            "CAMPAIGN_PROCESSED",

        "campaign_uid":
            campaign_uid,

        "preparation":
            preparation,

        "results":
            results,

        "delivery":
            delivery,

    }


# ============================================================
# RETRY FAILED
# ============================================================

def retry_failed_campaign(

    campaign_uid: str,

    max_recipients: int = 1000,

) -> dict:

    campaign = get_campaign(
        campaign_uid
    )


    if not campaign:

        raise ValueError(
            "Campaign not found."
        )


    if campaign.get(
        "status"
    ) != "APPROVED":

        raise ValueError(
            "Only approved campaigns can be retried."
        )


    with db() as connection:

        connection.execute(

            """
            UPDATE campaign_recipients
            SET
                status='PENDING',
                error_message=NULL
            WHERE campaign_uid=?
            AND status='FAILED'
            """,

            (
                campaign_uid,
            ),

        )


    return process_campaign(

        campaign_uid,

        max_recipients=max_recipients,

    )


# ============================================================
# CAMPAIGN SUMMARY
# ============================================================

def campaign_summary(
    campaign_uid: str,
) -> dict:

    campaign = get_campaign(
        campaign_uid
    )


    if not campaign:

        raise ValueError(
            "Campaign not found."
        )


    with db() as connection:

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


        recent = connection.execute(

            """
            SELECT
                id,
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

        "campaign":
            campaign,

        "summary":
            [
                dict(row)
                for row in summary
            ],

        "recent_recipients":
            [
                dict(row)
                for row in recent
            ],

    }


# ============================================================
# CONFIGURATION STATUS
# ============================================================

def configuration_status() -> dict:

    whatsapp_template_ready = bool(
        TWILIO_WHATSAPP_CONTENT_SID
    )


    return {

        "email":
            {

                "configured":
                    email_available(),

                "provider":
                    "Gmail SMTP",

                "username_configured":
                    bool(
                        SMTP_USERNAME
                    ),

            },


        "sms":
            {

                "configured":
                    sms_available(),

                "provider":
                    "Twilio SMS",

                "sender_configured":
                    bool(
                        TWILIO_SMS_FROM
                    ),

            },


        "whatsapp":
            {

                "configured":
                    whatsapp_available(),

                "provider":
                    "Twilio WhatsApp",

                "from_configured":
                    bool(
                        TWILIO_WHATSAPP_FROM
                    ),

                "content_sid_configured":
                    whatsapp_template_ready,

                "otp_template_configured":
                    bool(
                        TWILIO_WHATSAPP_OTP_CONTENT_SID
                    ),

            },


        "dashboard":
            {

                "configured":
                    True,

                "provider":
                    "EWS Database",

            },


    }


# ============================================================
# TEST WHATSAPP
# ============================================================

def test_whatsapp(
    recipient: str,
) -> dict:

    if not whatsapp_available():

        raise RuntimeError(
            "Twilio WhatsApp is not configured."
        )


    sid = send_whatsapp(

        recipient=recipient,

        body=(
            "🌊 Odisha Flood EWS\n\n"
            "This is a test notification. "
            "No emergency action is required."
        ),

    )


    return {

        "status":
            "SENT",

        "provider":
            "Twilio WhatsApp",

        "message_sid":
            sid,

    }


# ============================================================
# TEST SMS
# ============================================================

def test_sms(
    recipient: str,
) -> dict:

    if not sms_available():

        raise RuntimeError(
            "Twilio SMS is not configured."
        )


    sid = send_sms(

        recipient,

        (
            "ODISHA FLOOD EWS: "
            "This is a test notification. "
            "No emergency action is required."
        ),

    )


    return {

        "status":
            "SENT",

        "provider":
            "Twilio SMS",

        "message_sid":
            sid,

    }


# ============================================================
# MAIN DIAGNOSTIC
# ============================================================

if __name__ == "__main__":

    print()
    print(
        "=========================================================="
    )
    print(
        " ODISHA FLOOD EWS — MESSAGING SERVICE"
    )
    print(
        "=========================================================="
    )

    print(
        "Database:",
        DB_PATH,
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
        "Twilio:",
        (
            "READY"
            if twilio_available()
            else
            "NOT CONFIGURED"
        ),
    )

    print(
        "SMS:",
        (
            "READY"
            if sms_available()
            else
            "NOT CONFIGURED"
        ),
    )

    print(
        "WhatsApp:",
        (
            "READY"
            if whatsapp_available()
            else
            "NOT CONFIGURED"
        ),
    )

    print(
        "WhatsApp ContentSid:",
        (
            "CONFIGURED"
            if TWILIO_WHATSAPP_CONTENT_SID
            else
            "NOT CONFIGURED"
        ),
    )

    print(
        "WhatsApp OTP template:",
        (
            "CONFIGURED"
            if TWILIO_WHATSAPP_OTP_CONTENT_SID
            else
            "NOT CONFIGURED"
        ),
    )

    print(
        "=========================================================="
    )
    print()