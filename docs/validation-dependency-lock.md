# Validation dependency lock

`requirements-validation.in` is the human-maintained list of direct
dependencies. `requirements-validation.txt` is the generated, hash-locked
closure used by CI, Pages validation and scheduled drift checks.

The lock targets CPython 3.12 on Linux x86-64 with a manylinux 2.28 baseline.
It was generated with `uv 0.11.8` and excludes releases uploaded after
2026-07-27T00:00:00Z, with narrow security exceptions for urllib3 through
2 November 2026 and certifi through 3 November 2026. The direct input pins
urllib3 2.8.0 to fix unbounded chunk-size lines and deflate streaming, and
certifi 2026.10.19 to remove the compromised emSign ECC Root CA - G3 trust root.
The certifi update changes only that package version; the other 51 remain frozen.
It retains complete hash enforcement with 1,159 artefact hashes across the
52-package closure, with nine
direct requirements and 43 transitive packages.

The [upstream advisory](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2)
declares 2026.10.18 patched, while the
[Python security guidance](https://discuss.python.org/t/information-for-python-users-regarding-emudhra-emsign-ca-certificate-security-incident/109576)
recommends 2026.10.19 to preserve unaffected emSign roots. The installed-store
regression rejects the compromised root by DER fingerprint and subject name,
retains the three unaffected emSign roots and keeps TLS verification enabled.
It fails against 2026.7.22 and passes against 2026.10.19. This verifies the
repository's validation environment; workstation stores, pip's vendored store
and deployed images retain their separate update and verification boundaries.

Regenerate the governed lock with:

```sh
uv pip compile requirements-validation.in \
  --output-file requirements-validation.txt \
  --python-version 3.12 \
  --python-platform x86_64-manylinux_2_28 \
  --generate-hashes \
  --only-binary :all: \
  --exclude-newer 2026-07-27T00:00:00Z \
  --exclude-newer-package urllib3=2026-11-02T00:00:00Z \
  --exclude-newer-package certifi=2026-11-03T00:00:00Z \
  --no-sources
```

Install the governed closure with hash enforcement:

```sh
python3 -m pip install \
  --disable-pip-version-check \
  --require-hashes \
  --requirement requirements-validation.txt
```

Regenerate only after changing the direct input or deliberately refreshing
the closure. Review both version and hash changes. The lock's resolution scope
matches the Linux x86-64 GitHub runners; another operating system,
architecture or Python minor version requires a separately generated and
reviewed lock. Release-reproduction parsing and full installed-environment
attestation are separate closure steps and must be completed before candidate
freeze.
