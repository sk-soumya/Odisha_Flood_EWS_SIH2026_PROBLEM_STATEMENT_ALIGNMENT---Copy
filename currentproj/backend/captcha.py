# ============================================================
# ODISHA FLOOD RISK & EMERGENCY EVACUATION SYSTEM
# captcha.py — v13.0
#
# CLOUDFLARE TURNSTILE CAPTCHA SERVICE
#
# FEATURES
#   - Turnstile configuration detection
#   - Server-side token verification
#   - Public site-key endpoint
#   - Admin configuration/status endpoint
#   - Optional direct verification endpoint
#
# IMPORTANT
#   The SECRET KEY must remain server-side.
#   Never place EWS_TURNSTILE_SECRET_KEY in HTML/JS.
#
# Required .env:
#
#   EWS_TURNSTILE_SITE_KEY=xxxxxxxx
#   EWS_TURNSTILE_SECRET_KEY=xxxxxxxx
#
# ============================================================

import os

from pathlib import Path
from typing import Optional

import httpx

from dotenv import load_dotenv

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
)

from pydantic import (
    BaseModel,
    Field,
)


# ============================================================
# ENVIRONMENT
# ============================================================

BASE_DIR = (
    Path(__file__).resolve().parent
)

ENV_FILE = (
    BASE_DIR / ".env"
)

load_dotenv(
    ENV_FILE,
    override=True,
)


# ============================================================
# CONFIGURATION
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


try:

    TURNSTILE_TIMEOUT = float(
        os.getenv(
            "EWS_TURNSTILE_TIMEOUT",
            "10",
        )
    )

except ValueError:

    TURNSTILE_TIMEOUT = 10.0


DEV_MODE = (
    os.getenv(
        "EWS_DEV_MODE",
        "true",
    ).strip().lower()
    == "true"
)


# ============================================================
# ROUTER
# ============================================================

router = APIRouter(
    prefix="/api/v1/captcha",
    tags=["CAPTCHA"],
)


# ============================================================
# MODELS
# ============================================================

class TurnstileVerifyRequest(BaseModel):

    token: str = Field(
        min_length=1,
        max_length=5000,
    )


# ============================================================
# CONFIGURATION STATUS
# ============================================================

def turnstile_fully_configured() -> bool:

    return bool(

        TURNSTILE_SITE_KEY

        and

        TURNSTILE_SECRET_KEY

    )


def turnstile_public_configured() -> bool:

    return bool(
        TURNSTILE_SITE_KEY
    )


# ============================================================
# CLIENT IP
# ============================================================

def get_client_ip(
    request: Request,
) -> Optional[str]:

    # --------------------------------------------------------
    # Prefer direct client information.
    #
    # In production behind a trusted proxy, forwarded headers
    # can be used, but do not blindly trust arbitrary forwarded
    # headers unless the proxy is controlled by you.
    # --------------------------------------------------------

    if request.client:

        host = (
            request.client.host
        )

        if host:

            return host

    return None


# ============================================================
# TURNSTILE VERIFICATION
# ============================================================

async def verify_turnstile_token(
    token: Optional[str],
    remote_ip: Optional[str] = None,
    required: bool = True,
) -> bool:
    """
    Verify a Cloudflare Turnstile token server-side.

    Returns:
        True  -> verification successful
        False -> verification unsuccessful when
                 required=False

    Raises:
        HTTPException for required verification failures.
    """

    # --------------------------------------------------------
    # Configuration check
    # --------------------------------------------------------

    if not turnstile_fully_configured():

        # Development fallback is intentionally available
        # only in DEV_MODE.
        if DEV_MODE:

            return True

        if required:

            raise HTTPException(

                status_code=503,

                detail=(
                    "Cloudflare Turnstile is not configured."
                ),

            )

        return False


    # --------------------------------------------------------
    # Token check
    # --------------------------------------------------------

    token = (
        token
        or
        ""
    ).strip()


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


    # --------------------------------------------------------
    # Server-side verification with Cloudflare.
    # --------------------------------------------------------

    try:

        async with httpx.AsyncClient(
            timeout=TURNSTILE_TIMEOUT,
        ) as client:

            response = await client.post(

                TURNSTILE_VERIFY_URL,

                data=payload,

            )

            response.raise_for_status()

            result = response.json()


    except httpx.HTTPError as error:

        print(
            "[TURNSTILE CONNECTION ERROR]",
            error,
        )

        if required:

            raise HTTPException(

                status_code=503,

                detail=(
                    "CAPTCHA verification service "
                    "is temporarily unavailable."
                ),

            ) from error

        return False


    except ValueError as error:

        print(
            "[TURNSTILE JSON ERROR]",
            error,
        )

        if required:

            raise HTTPException(

                status_code=503,

                detail=(
                    "Invalid response from CAPTCHA service."
                ),

            ) from error

        return False


    # --------------------------------------------------------
    # Cloudflare result
    # --------------------------------------------------------

    success = bool(
        result.get(
            "success",
            False,
        )
    )


    if success:

        return True


    error_codes = (
        result.get(
            "error-codes"
        )
        or
        []
    )


    if required:

        # Do not expose the secret or unnecessary internal
        # details to the browser.
        raise HTTPException(

            status_code=400,

            detail=(
                "CAPTCHA verification failed. "
                "Please try again."
            ),

        )


    if DEV_MODE:

        print(
            "[TURNSTILE FAILED]",
            error_codes,
        )


    return False


# ============================================================
# PUBLIC SITE KEY
# ============================================================

@router.get(
    "/site-key"
)
async def get_site_key():

    if not TURNSTILE_SITE_KEY:

        raise HTTPException(

            status_code=503,

            detail=(
                "Turnstile site key is not configured."
            ),

        )


    return {

        "status":
            "SUCCESS",

        "site_key":
            TURNSTILE_SITE_KEY,

    }


# ============================================================
# CONFIGURATION STATUS
# ============================================================

@router.get(
    "/status"
)
async def captcha_status():

    return {

        "status":
            "SUCCESS",

        "provider":
            "Cloudflare Turnstile",

        "configured":
            turnstile_fully_configured(),

        "site_key_configured":
            bool(
                TURNSTILE_SITE_KEY
            ),

        "secret_key_configured":
            bool(
                TURNSTILE_SECRET_KEY
            ),

        "server_verification":
            True,

        "development_mode":
            DEV_MODE,

    }


# ============================================================
# DIRECT VERIFY ENDPOINT
# ============================================================

@router.post(
    "/verify"
)
async def verify_endpoint(

    req: TurnstileVerifyRequest,

    request: Request,

):

    client_ip = get_client_ip(
        request
    )


    verified = await verify_turnstile_token(

        token=req.token,

        remote_ip=client_ip,

        required=True,

    )


    return {

        "status":
            "CAPTCHA_VERIFIED"
            if verified
            else
            "CAPTCHA_FAILED",

        "verified":
            verified,

        "provider":
            "Cloudflare Turnstile",

    }


# ============================================================
# INTERNAL HELPER FOR OTHER MODULES
# ============================================================

async def require_turnstile(
    token: Optional[str],
    request: Optional[Request] = None,
) -> bool:
    """
    Convenience helper for users.py or other services.

    Example:

        await require_turnstile(
            token=req.captcha_token,
            request=request,
        )
    """

    remote_ip = None


    if request:

        remote_ip = get_client_ip(
            request
        )


    return await verify_turnstile_token(

        token=token,

        remote_ip=remote_ip,

        required=True,

    )


# ============================================================
# DIAGNOSTIC
# ============================================================

if __name__ == "__main__":

    print()
    print(
        "=========================================================="
    )

    print(
        " ODISHA FLOOD EWS — TURNSTILE CAPTCHA"
    )

    print(
        "=========================================================="
    )

    print(
        "Provider:",
        "Cloudflare Turnstile",
    )

    print(
        "Site Key:",
        (
            "CONFIGURED"
            if TURNSTILE_SITE_KEY
            else
            "NOT CONFIGURED"
        ),
    )

    print(
        "Secret Key:",
        (
            "CONFIGURED"
            if TURNSTILE_SECRET_KEY
            else
            "NOT CONFIGURED"
        ),
    )

    print(
        "Fully configured:",
        turnstile_fully_configured(),
    )

    print(
        "Development mode:",
        DEV_MODE,
    )

    print(
        "=========================================================="
    )

    print()