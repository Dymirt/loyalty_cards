"""Deprecated registration-workflow adapters.

No background thread is started. Existing callers create idempotent database
jobs which a supervised ``run_integration_worker`` process can recover.
"""

from enrollment.jobs import enqueue_registration_followups


def start_registration_followups(klient_pk):
    return enqueue_registration_followups(klient_pk)


def run_registration_followups(klient_pk):
    return enqueue_registration_followups(klient_pk)


__all__ = ["run_registration_followups", "start_registration_followups"]
