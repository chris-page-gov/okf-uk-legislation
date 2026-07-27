# Validation dependency lock

`requirements-validation.in` is the human-maintained list of direct
dependencies. `requirements-validation.txt` is the generated, hash-locked
closure used by CI, Pages validation and scheduled drift checks.

The lock targets CPython 3.12 on Linux x86-64 with a manylinux 2.28 baseline.
It was generated with `uv 0.11.8` and excludes releases uploaded after
2026-07-27T00:00:00Z:

```sh
uv pip compile requirements-validation.in \
  --output-file requirements-validation.txt \
  --python-version 3.12 \
  --python-platform x86_64-manylinux_2_28 \
  --generate-hashes \
  --only-binary :all: \
  --exclude-newer 2026-07-27T00:00:00Z \
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
