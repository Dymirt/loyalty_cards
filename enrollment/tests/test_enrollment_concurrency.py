from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections
from django.test import TransactionTestCase, override_settings, skipUnlessDBFeature

from dotykacka.tests.base import create_physical_card, create_tenant
from enrollment.models import Enrollment
from enrollment.services import register_customer_with_card

from .test_enrollment_services import cleaned_registration


class EnrollmentConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    @override_settings(
        APPLE_WALLET_PASS_TYPE_IDENTIFIER="",
        APPLE_WALLET_TEAM_IDENTIFIER="",
    )
    def test_two_submissions_cannot_claim_the_same_tenant_card(self):
        tenant = create_tenant(name="Parallel Café", slug="parallel-cafe", card_prefix="PCX")
        card = create_physical_card(tenant, number=9)

        def attempt():
            close_old_connections()
            local_tenant = type(tenant).objects.get(pk=tenant.pk)
            try:
                result = register_customer_with_card(
                    tenant=local_tenant,
                    cleaned_data=cleaned_registration(card.code),
                )
                return result.enrollment.pk
            except Exception:
                return None
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _value: attempt(), range(2)))

        self.assertEqual(sum(value is not None for value in results), 1)
        self.assertEqual(Enrollment.objects.filter(tenant=tenant).count(), 1)
