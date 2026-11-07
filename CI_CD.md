# CI/CD for Clankr

## Continuous integration

The GitHub Actions workflow at `.github/workflows/ci.yml` runs on:

- Every pull request targeting `main`.
- Every push to `main`.
- Manual dispatch from the GitHub Actions tab.

It uses GitHub-hosted Ubuntu runners and Python 3.14. From `pyggie/`, it runs:

1. `python manage.py check`
2. `python manage.py makemigrations --check --dry-run`
3. `python manage.py test home --verbosity 2`

Pip caching is enabled. Workflow permissions are read-only, and outdated concurrent runs are cancelled.

## Automatic server deployment (cron + systemd)

The server-side deployment script is `scripts/deploy.sh`. It polls `origin/main` and deploys only when the remote commit is ahead of the local checkout.

### What the script does

1. Takes a non-blocking `flock` lock to prevent overlapping deployments.
2. Confirms the configured directory is a Git checkout on the configured branch.
3. Refuses to deploy over tracked local modifications or divergent Git history.
4. Fetches the configured remote branch and exits if there is no new commit.
5. Fast-forwards the checkout to the fetched commit.
6. Installs `requirements.txt` into the configured virtualenv.
7. Runs `manage.py check`.
8. Creates a consistent SQLite backup (when the configured database file exists).
9. Runs `manage.py migrate --noinput`.
10. Restarts the configured systemd service and checks that it is active.

It does not run `git clean`, delete runtime files, or automatically roll back code after a failed deployment. Database backups are retained; arrange a separate backup-retention policy. A failed deployment stops before the systemd restart whenever possible, but code may already have been updated on disk. Review logs and repair manually if a step fails.

### One-time server setup

Run these steps as an administrator, adapting paths and account names.

1. Clone the repository into a stable deployment directory and check out `main`. The deployment account must be able to fetch `origin` non-interactively (for a public repository HTTPS is sufficient; for a private repository configure a read-only deploy key).
2. Create a Python virtualenv and install dependencies. Example:

   ```bash
   cd /opt/clankr
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   ```

3. Create `/etc/clankr-deploy.conf`, substituting the actual paths and service name:

   ```bash
   sudo install -o root -g root -m 0640 /dev/null /etc/clankr-deploy.conf
   sudoedit /etc/clankr-deploy.conf
   ```

   File contents:

   ```bash
   APP_DIR="/opt/clankr"
   VENV_DIR="/opt/clankr/.venv"
   SERVICE_NAME="clankr.service"
   BRANCH="main"
   DB_PATH="/opt/clankr/pyggie/db.sqlite3"
   BACKUP_DIR="/var/backups/clankr"
   ```

   Keep this file root-owned and not writable by the deployment account. The account running the script must be able to read it. Adjust `DB_PATH` if Django's SQLite database is stored elsewhere. Ensure that account can write to `BACKUP_DIR`; create it with suitable ownership before the first deployment.

4. Give the deployment account permission to restart and inspect only this service. Use `sudo visudo -f /etc/sudoers.d/clankr-deploy` and add (replace `clankr` and the service name):

   ```sudoers
   clankr ALL=(root) NOPASSWD: /usr/bin/systemctl restart clankr.service, /usr/bin/systemctl is-active --quiet clankr.service
   ```

   Confirm the systemctl path with `command -v systemctl`. Validate the sudoers file with `sudo visudo -cf /etc/sudoers.d/clankr-deploy`.

5. Install the script and make it executable:

   ```bash
   sudo install -o root -g root -m 0755 scripts/deploy.sh /opt/clankr/scripts/deploy.sh
   ```

   The deployment account must be able to read and execute it. Since the script is run from the checkout, future updates to the script itself arrive with the repository; ensure its executable bit is committed.

6. Test it manually as the same Unix account that will own the cron job:

   ```bash
   /bin/bash /opt/clankr/scripts/deploy.sh
   ```

   The first run should report that Clankr is up to date. Then inspect the output and verify the service. Do not schedule it until the paths, permissions, database backup, and systemd restart all work as expected.

### Cron entry

Install this in the crontab of the dedicated deployment account (not root):

```cron
*/5 * * * * /bin/bash /opt/clankr/scripts/deploy.sh >> /home/clankr/clankr-deploy.log 2>&1
```

Replace `/opt/clankr` and `/home/clankr` with your real paths. Edit that account's crontab with `crontab -e`. Cron will check every five minutes; when there are no new commits it exits without installing packages, migrating, or restarting the service.

### Important production notes

- Protect `main` with a required pull request and require the **Django checks and tests (Python 3.14)** status check before merge. The cron script deploys the tip of `main`; it does not independently verify GitHub Actions status. Without branch protection, a direct push can be deployed before CI finishes.
- The current Django settings in the repository are development settings (`DEBUG = True`, wildcard `ALLOWED_HOSTS`, and a hard-coded development secret). Do not expose this deployment to an untrusted network until production settings, secret management, allowed hosts, HTTPS/proxy settings, and static-file serving have been configured and reviewed.
- Confirm the systemd unit uses the same virtualenv and working directory as the deployment script.
- Keep SQLite, uploads, workspaces, and other runtime state out of destructive deployment operations. The script never calls `git clean`.
- The SQLite backup uses Python's SQLite online backup API and is written outside the checkout before migrations. Ensure backup storage has enough disk space and is itself backed up if the data matters.
- The service restart is the only operation granted through sudo. Do not run the cron job as root.
- Inspect `clankr-deploy.log` after the first scheduled run. You can also inspect service logs with `journalctl -u clankr.service`.

## Rules for contributors and coding agents

- Do not merge a pull request while CI is failing.
- Run the same three Django commands locally before requesting review.
- If a change intentionally alters models, include the generated migration in the same pull request.
- If dependencies change, update `requirements.txt`.
- Keep tests independent of a running Ollama server or external network services. Mock external model/API calls in tests.
- If the test command or supported Python version changes, update this document and the workflow together.

## Enabling merge protection

Configure GitHub branch protection or a repository ruleset for `main`:

- Require a pull request before merging.
- Require the **Django checks and tests (Python 3.14)** status check.
- Optionally require the branch to be up to date before merging.
- Block force pushes and deletion of `main`.
