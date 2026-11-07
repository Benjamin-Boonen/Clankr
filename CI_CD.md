# CI/CD for Clankr

## Current pipeline

The GitHub Actions workflow at `.github/workflows/ci.yml` is the required first stage of Clankr's delivery process.

It runs on:

- Every pull request targeting `main`.
- Every push to `main`.
- Manual dispatch from the GitHub Actions tab.

The workflow uses GitHub-hosted Ubuntu runners and Python 3.14, matching the current development runtime. It installs the repository's existing `requirements.txt` and runs, from the `pyggie/` Django project directory:

1. `python manage.py check`
2. `python manage.py makemigrations --check --dry-run`
3. `python manage.py test home --verbosity 2`

Pip caching is enabled. Workflow permissions are read-only, and concurrent outdated runs for the same ref are cancelled.

## Rules for contributors and coding agents

- Do not merge a pull request while the CI workflow is failing.
- Run the same three Django commands locally before requesting review.
- If a change intentionally alters models, include the generated migration in the same pull request.
- If dependencies change, update `requirements.txt`; the workflow cache is keyed from this file.
- Do not add production credentials, API keys, database files, or local environment files to the repository.
- Keep tests independent of a running Ollama server or external network services. Mock external model/API calls in tests.
- If the test command or supported Python version changes, update this document and the workflow together.

## Current CD boundary

This change deliberately establishes continuous integration first; it does **not** deploy to a server yet.

The repository currently has no Dockerfile or Compose configuration, and the production host/deployment target has not been specified. Automatically deploying from `main` before those details are known could overwrite a live instance or mishandle its SQLite database and local model connection.

Recommended next CD increment:

1. Confirm the production host and how Clankr is currently started.
2. Choose direct deployment or Docker Compose.
3. Define persistent storage for the SQLite database, uploaded files, and agent workspaces.
4. Add a health endpoint/check and a tested backup/rollback procedure.
5. Configure deployment credentials as GitHub Actions secrets or, preferably, use a restricted self-hosted deployment runner.
6. Add a separate, environment-protected deployment workflow. Keep deployment approval separate from pull-request CI.

Do not put secrets in workflow YAML. Do not expose a self-hosted runner that has production access to untrusted pull-request jobs.

## Enabling merge protection

After the first successful workflow run, configure GitHub branch protection or a repository ruleset for `main`:

- Require a pull request before merging.
- Require the **Django checks and tests (Python 3.14)** status check.
- Require the branch to be up to date before merging (optional; enable if the team prefers stricter integration).
- Block force pushes and deletion of `main`.

The required check name is the job name shown in the Actions UI: `Django checks and tests (Python 3.14)`.
