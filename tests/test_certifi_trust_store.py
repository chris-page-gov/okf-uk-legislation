"""Check the installed TLS trust boundary for GHSA-6q48-6c7w-9gw2."""

from __future__ import annotations

import hashlib
import ssl
import unittest

import certifi


# DER SHA-256 identities from the original certifi 2026.7.22 CA bundle.
COMPROMISED_ROOT = (
    "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b"
)
UNAFFECTED_EMSIGN_ROOTS = {
    "40f6af0346a99aa1cd1d555a4e9cce62c7f9634603ee406615833dc8c8d00367",
    "125609aa301da0a249b97a8239cb6a34216f44dcac9f3954b14292f2e8c8608f",
    "bc4d809b15189d78db3e1d8cf4f9726a795da1643ca5f1358e1ddb0edc0d7eb3",
}


class CertifiTrustStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        cls.context.load_verify_locations(cafile=certifi.where())
        cls.fingerprints = {
            hashlib.sha256(der).hexdigest()
            for der in cls.context.get_ca_certs(binary_form=True)
        }

    def test_compromised_emsign_g3_root_is_not_trusted(self) -> None:
        self.assertFalse(
            COMPROMISED_ROOT in self.fingerprints,
            "the installed CA store still trusts compromised emSign G3",
        )
        common_names = {
            value
            for certificate in self.context.get_ca_certs()
            for rdn in certificate["subject"]
            for key, value in rdn
            if key == "commonName"
        }
        self.assertNotIn("emSign ECC Root CA - G3", common_names)

    def test_unaffected_emsign_roots_remain_trusted(self) -> None:
        self.assertTrue(UNAFFECTED_EMSIGN_ROOTS <= self.fingerprints)

    def test_tls_verification_and_legitimate_ca_store_remain_available(self) -> None:
        self.assertEqual(self.context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(self.context.check_hostname)
        self.assertGreater(self.context.cert_store_stats()["x509_ca"], 100)


if __name__ == "__main__":
    unittest.main()
