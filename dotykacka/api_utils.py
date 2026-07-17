"""Deprecated Dotykačka API adapters backed by ``pos_dotykacka``."""

import requests
from django.core.exceptions import ImproperlyConfigured

from pos_dotykacka.services import DotykackaAdapter, get_connection


def get_dotykacka_connection(tenant):
    try:
        return get_connection(tenant)
    except Exception as exc:
        raise ImproperlyConfigured(str(exc)) from exc


def get_access_token(connection):
    return DotykackaAdapter(connection, session=requests).fetch_access_token(
        legacy_cache=True
    )


def get_valid_access_token(connection):
    return DotykackaAdapter(connection, session=requests).valid_access_token(
        legacy_cache=True
    )


def register_dotykacka_customer(
    tenant, barcode, first_name, last_name, email, phone
):
    from customers.models import Customer

    customer = Customer(
        tenant=tenant,
        klient_id=barcode,
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
    )
    connection = get_dotykacka_connection(tenant)
    return DotykackaAdapter(connection, session=requests)._legacy_upsert(
        customer,
        access_token=get_valid_access_token(connection),
    )


def get_all_customers(tenant):
    connection = get_dotykacka_connection(tenant)
    return DotykackaAdapter(connection, session=requests).list_customers(
        legacy_cache=True,
        access_token=get_valid_access_token(connection),
    )


__all__ = [
    "get_access_token",
    "get_all_customers",
    "get_dotykacka_connection",
    "get_valid_access_token",
    "register_dotykacka_customer",
]
