from cryptography.fernet import Fernet
from django.test import SimpleTestCase, override_settings

from dotykacka.tenant_secrets import decrypt_credentials, encrypt_credentials


class TenantSecretEncryptionTests(SimpleTestCase):
    def test_secret_is_encrypted_at_rest(self):
        key = Fernet.generate_key().decode("ascii")
        with override_settings(TENANT_SECRETS_ENCRYPTION_KEYS=[key]):
            encrypted = encrypt_credentials({"api_key": "tenant-secret"})

            self.assertTrue(encrypted.startswith("fernet:v1:"))
            self.assertNotIn("tenant-secret", encrypted)
            self.assertEqual(
                decrypt_credentials(encrypted),
                {"api_key": "tenant-secret"},
            )

    def test_old_key_can_decrypt_during_key_rotation(self):
        old_key = Fernet.generate_key().decode("ascii")
        new_key = Fernet.generate_key().decode("ascii")
        with override_settings(TENANT_SECRETS_ENCRYPTION_KEYS=[old_key]):
            encrypted = encrypt_credentials({"token": "old-secret"})

        with override_settings(TENANT_SECRETS_ENCRYPTION_KEYS=[new_key, old_key]):
            self.assertEqual(
                decrypt_credentials(encrypted),
                {"token": "old-secret"},
            )
