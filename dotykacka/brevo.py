"""Deprecated Brevo adapters backed by the final provider app."""

from brevo.services import BrevoAdapter, adapter_for_tenant, get_connection
from django.core.exceptions import ImproperlyConfigured


def _connection_for(tenant):
    try:
        return get_connection(tenant)
    except Exception as exc:
        raise ImproperlyConfigured(str(exc)) from exc


def _contacts_api(connection):
    return BrevoAdapter(connection)


def send_contact_to_brevo(klient):
    if not klient.email or not klient.phone:
        return False
    return bool(adapter_for_tenant(klient.tenant).upsert_contact(klient))


def add_contact_to_list(email, list_to_add, api_instance):
    """Compatibility helper; modern upsert manages list membership atomically."""

    return api_instance


__all__ = [
    "_connection_for",
    "_contacts_api",
    "add_contact_to_list",
    "send_contact_to_brevo",
]
