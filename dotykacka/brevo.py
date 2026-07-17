"""Tenant-scoped Brevo contact synchronization."""

import logging

import sib_api_v3_sdk
from django.core.exceptions import ImproperlyConfigured
from sib_api_v3_sdk import UpdateContact
from sib_api_v3_sdk.rest import ApiException

from .models import IntegrationConnection


logger = logging.getLogger(__name__)


def _connection_for(tenant):
    try:
        connection = IntegrationConnection.objects.get(
            tenant=tenant,
            provider=IntegrationConnection.Provider.BREVO,
            enabled=True,
        )
    except IntegrationConnection.DoesNotExist as exc:
        raise ImproperlyConfigured("Brevo is not enabled for this tenant.") from exc
    if not connection.configuration.get("list_id") or not connection.has_secret("api_key"):
        raise ImproperlyConfigured("Brevo tenant configuration is incomplete.")
    return connection


def _contacts_api(connection):
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = connection.get_secret("api_key")
    return sib_api_v3_sdk.ContactsApi(sib_api_v3_sdk.ApiClient(configuration))


def add_contact_to_list(email, list_to_add, api_instance):
    try:
        contact_info = api_instance.get_contact_info(email)
        current_lists = contact_info.list_ids or []
        if list_to_add in current_lists:
            return
        api_instance.update_contact(
            email,
            UpdateContact(list_ids=current_lists + [list_to_add]),
        )
    except ApiException:
        logger.error("brevo_existing_contact_update_failed")
        raise


def send_contact_to_brevo(klient):
    if not klient.email or not klient.phone:
        return False

    connection = _connection_for(klient.tenant)
    country_code = connection.configuration.get("default_phone_country_code", "+48")
    phone = klient.phone
    if not phone.startswith("+"):
        phone = f"{country_code}{phone}"

    api_instance = _contacts_api(connection)
    list_id = connection.configuration["list_id"]
    create_contact = sib_api_v3_sdk.CreateContact(
        email=klient.email,
        attributes={
            "SMS": phone,
            "FNAME": klient.first_name or "",
            "LNAME": klient.last_name or "",
        },
        list_ids=[list_id],
        email_blacklisted=False,
        sms_blacklisted=False,
        update_enabled=True,
    )

    try:
        api_instance.create_contact(create_contact)
    except ApiException as exc:
        if "duplicate_parameter" not in str(exc):
            logger.error("brevo_contact_create_failed")
            raise
        add_contact_to_list(klient.email, list_id, api_instance)
    return True
