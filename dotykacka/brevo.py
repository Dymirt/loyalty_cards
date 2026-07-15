import logging

import sib_api_v3_sdk
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from sib_api_v3_sdk import UpdateContact
from sib_api_v3_sdk.rest import ApiException


logger = logging.getLogger(__name__)


def _contacts_api():
    if not settings.BREVO_API_KEY:
        raise ImproperlyConfigured("BREVO_API_KEY is not configured")

    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = settings.BREVO_API_KEY
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
        logger.exception("Could not update an existing Brevo contact")
        raise


def send_contact_to_brevo(klient):
    if not klient.email or not klient.phone:
        return False

    phone = klient.phone
    if not phone.startswith("+"):
        phone = f"{settings.DEFAULT_PHONE_COUNTRY_CODE}{phone}"

    api_instance = _contacts_api()
    create_contact = sib_api_v3_sdk.CreateContact(
        email=klient.email,
        attributes={
            "SMS": phone,
            "FNAME": klient.first_name or "",
            "LNAME": klient.last_name or "",
        },
        list_ids=[settings.BREVO_LIST_ID],
        email_blacklisted=False,
        sms_blacklisted=False,
        update_enabled=True,
    )

    try:
        api_instance.create_contact(create_contact)
    except ApiException as exc:
        if "duplicate_parameter" not in str(exc):
            logger.exception("Could not create a Brevo contact")
            raise
        add_contact_to_list(klient.email, settings.BREVO_LIST_ID, api_instance)

    return True
