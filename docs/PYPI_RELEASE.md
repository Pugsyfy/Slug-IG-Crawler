# Publishing `slug-ig-crawler` to PyPI

Canonical project links (PyPI metadata and this doc) use:

**https://github.com/Pugsyfy/Slug-IG-Crawler**

Releases and Trusted Publishing must run from that repository (or your PyPI "pending publisher" must match the **exact** GitHub repo you use—see below).

---

## Prerequisites

1. **PyPI account** with **2FA** enabled.
2. **Project** `slug-ig-crawler` on PyPI (created automatically on first successful upload, or create it empty first).
3. **Version** in [`pyproject.toml`](../pyproject.toml) `[project].version` matches the release you intend to ship (and ideally matches the Git tag, e.g. `v2.0.2` ↔ `2.0.2`).

---

## One-time: Trusted Publishing (recommended)

Avoid long-lived API tokens on your laptop by letting GitHub Actions authenticate to PyPI via OIDC.

1. On **PyPI**: [Account settings → Publishing](https://pypi.org/manage/account/publishing/) → **Add a new pending publisher**.
2. Choose **GitHub** as the provider and set:
   - **Owner:** `Pugsyfy`
   - **Repository name:** `Slug-IG-Crawler`
   - **Workflow name:** `publish-pypi.yml`
   - **Environment name:** leave **empty** (unless you configure a named environment on both PyPI and GitHub—see optional hardening below).
3. Save. PyPI will show the publisher as **pending** until the first successful upload from that workflow.

Official reference: [PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/).

### Optional: GitHub Environment `pypi`

You can require a GitHub [environment](https://docs.github.com/en/actions/deployment/targeting-different-environments/using-environments-for-deployment) (e.g. `pypi`) and add the same name on PyPI’s trusted publisher form. Then add to the workflow job:

```yaml
environment:
  name: pypi
  url: https://pypi.org/p/slug-ig-crawler/
```

---

## Dry run: TestPyPI (optional but recommended)

TestPyPI is a separate index; register a **second** trusted publisher (or API token) at [test.pypi.org](https://test.pypi.org) if you want automated uploads there. For a quick manual check:

```bash
python -m pip install --upgrade pip build twine
python -m build
python -m twine check dist/*
python -m twine upload --repository testpypi dist/*
```

Then in a **clean** venv:

```bash
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ "slug-ig-crawler==<version>"
```

(`--extra-index-url` pulls normal dependencies from PyPI.)

---

## Release steps (production)

1. **Merge** your changes to the default branch on **`Pugsyfy/Slug-IG-Crawler`** (or ensure the release tag points at the commit you want).
2. **Bump** `[project].version` in `pyproject.toml` if needed; commit and push.
3. **Create a GitHub Release** (not just a tag) and publish it.  
   The workflow `.github/workflows/publish-pypi.yml` runs on `release: published` and uploads `dist/*` to PyPI.
4. Wait for the **Publish to PyPI** workflow to finish green.

---

## Manual upload (fallback)

If you cannot use Trusted Publishing:

```bash
python -m pip install --upgrade pip build twine
python -m build
python -m twine check dist/*
python -m twine upload dist/*
```

Use a [PyPI API token](https://pypi.org/manage/account/token/) scoped to the project (or whole account), set `TWINE_USERNAME=__token__` and `TWINE_PASSWORD=<token>`.

---

## After publish

- Verify: [https://pypi.org/project/slug-ig-crawler/](https://pypi.org/project/slug-ig-crawler/)
- Smoke test:

```bash
pip install "slug-ig-crawler==<version>"
Slug-Ig-Crawler --help
python -c "import igscraper; print(igscraper.__version__)"
```

---

## Troubleshooting

| Symptom | Likely cause |
|--------|----------------|
| Trusted publisher fails / OIDC error | Wrong Owner / Repository / workflow filename on PyPI; or release published from a **fork**—publisher must match the repo that runs the workflow. |
| `403` or `invalid token` | Not using Trusted Publishing + token; or token expired. |
| Version already exists | PyPI is immutable; bump `version` in `pyproject.toml` and release again. |
| `twine check` fails | README/metadata issue; fix `pyproject.toml` or `README.md`. |

---

## Fork vs upstream

If you develop on a fork but want PyPI metadata to stay **Pugsyfy**, keep `[project.urls]` as-is. **Trusted Publishing** must still be registered for the **repository that runs** `publish-pypi.yml` when you cut the release (usually the upstream org repo after you merge).
