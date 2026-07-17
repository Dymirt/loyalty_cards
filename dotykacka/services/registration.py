"""Registration follow-up workflow kept separate from the HTTP request."""

import logging
from threading import Thread

import dotykacka.api_utils as dotykacka_api
from dotykacka.models import Klient

from .notifications import send_pass_email
from .wallets import ensure_apple_wallet_pass, generate_google_wallet_for_klient


logger = logging.getLogger(__name__)


def _record_failure(step: str, klient_pk: int, exc: Exception) -> None:
    logger.error(
        "registration_followup_failed",
        extra={
            "step": step,
            "klient_pk": klient_pk,
            "error_type": type(exc).__name__,
        },
    )


def run_registration_followups(klient_pk: int) -> None:
    """Run independent side effects with redacted failures and explicit Wallet order."""

    try:
        klient = Klient.objects.get(pk=klient_pk)
    except Klient.DoesNotExist:
        logger.warning(
            "registration_followup_customer_missing",
            extra={"klient_pk": klient_pk},
        )
        return

    wallets_ready = True
    try:
        ensure_apple_wallet_pass(klient)
    except Exception as exc:  # external signing/filesystem boundary
        wallets_ready = False
        _record_failure("apple_wallet", klient.pk, exc)

    try:
        generate_google_wallet_for_klient(klient)
    except Exception as exc:  # external credential/signing boundary
        wallets_ready = False
        _record_failure("google_wallet", klient.pk, exc)

    try:
        dotykacka_api.register_dotykacka_customer(
            klient.klient_id,
            klient.first_name,
            klient.last_name,
            klient.email,
            klient.phone,
        )
    except Exception as exc:  # external POS boundary
        _record_failure("dotykacka", klient.pk, exc)

    if wallets_ready:
        try:
            klient.refresh_from_db(fields=["google_jwt_url"])
            send_pass_email(klient)
        except Exception as exc:  # email boundary
            _record_failure("email", klient.pk, exc)


def start_registration_followups(klient_pk: int) -> Thread:
    """Temporary Phase-0 launcher; a durable database job replaces this in Phase 5."""

    thread = Thread(
        target=run_registration_followups,
        args=(klient_pk,),
        name=f"registration-followup-{klient_pk}",
        daemon=True,
    )
    thread.start()
    return thread
