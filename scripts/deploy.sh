#!/usr/bin/env bash
#
# Deploy the latest main branch to this checkout.
# Run as the Unix account that owns APP_DIR and the Python virtualenv.
# Grant that account narrowly-scoped passwordless sudo access to restart and
# inspect SERVICE_NAME (see CI_CD.md).

set -Eeuo pipefail
umask 027

CONFIG_FILE="${CONFIG_FILE:-/etc/clankr-deploy.conf}"
if [[ ! -r "$CONFIG_FILE" ]]; then
  echo "ERROR: deployment config is missing or unreadable: $CONFIG_FILE" >&2
  exit 1
fi

# This file must be owned by root and not writable by the deployment user.
# shellcheck source=/dev/null
source "$CONFIG_FILE"

: "${APP_DIR:?Set APP_DIR in $CONFIG_FILE}"
: "${SERVICE_NAME:?Set SERVICE_NAME in $CONFIG_FILE}"

BRANCH="${BRANCH:-main}"
VENV_DIR="${VENV_DIR:-$APP_DIR/.venv}"
LOCK_FILE="${LOCK_FILE:-${HOME:?HOME must be set}/.cache/clankr-deploy.lock}"
DB_PATH="${DB_PATH:-$APP_DIR/pyggie/db.sqlite3}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/clankr}"
PYTHON="${VENV_DIR}/bin/python"
MANAGE_PY="${APP_DIR}/pyggie/manage.py"
REMOTE_REF="refs/remotes/origin/$BRANCH"

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

mkdir -p "$(dirname "$LOCK_FILE")"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Another Clankr deployment is already running; skipping."
  exit 0
fi

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ -d "$APP_DIR/.git" ]] || fail "APP_DIR is not a Git checkout: $APP_DIR"
[[ -x "$PYTHON" ]] || fail "Python virtualenv not found at $PYTHON"
[[ -f "$MANAGE_PY" ]] || fail "Django manage.py not found at $MANAGE_PY"
[[ "$BRANCH" =~ ^[A-Za-z0-9._/-]+$ ]] || fail "Invalid branch name: $BRANCH"

cd "$APP_DIR"

CURRENT_BRANCH="$(git branch --show-current)"
[[ "$CURRENT_BRANCH" == "$BRANCH" ]] || fail "Checkout is on '$CURRENT_BRANCH', expected '$BRANCH'."

# Never overwrite tracked local edits. Ignored runtime data (such as db.sqlite3)
# is left alone; this script deliberately does not run git clean.
if ! git diff --quiet || ! git diff --cached --quiet; then
  fail "Tracked local changes exist in $APP_DIR; refusing to deploy over them."
fi

echo "Checking origin/$BRANCH for updates..."
git fetch --quiet origin "+refs/heads/$BRANCH:$REMOTE_REF"

CURRENT_SHA="$(git rev-parse HEAD)"
TARGET_SHA="$(git rev-parse "$REMOTE_REF")"

if [[ "$CURRENT_SHA" == "$TARGET_SHA" ]]; then
  echo "Clankr is already up to date ($CURRENT_SHA)."
  exit 0
fi

# Only fast-forward deployments are allowed. Divergent history must be
# resolved manually rather than discarded automatically.
if ! git merge-base --is-ancestor HEAD "$REMOTE_REF"; then
  fail "Local checkout and origin/$BRANCH have diverged; refusing to reset."
fi

echo "Deploying $CURRENT_SHA -> $TARGET_SHA"
git reset --hard "$TARGET_SHA"

echo "Installing Python dependencies..."
"$PYTHON" -m pip install -r "$APP_DIR/requirements.txt"

echo "Running Django system checks..."
"$PYTHON" "$MANAGE_PY" check

# Take a consistent SQLite backup before applying migrations. The backup is
# kept outside the Git checkout and is never automatically deleted.
if [[ -f "$DB_PATH" ]]; then
  mkdir -p "$BACKUP_DIR"
  BACKUP_FILE="$BACKUP_DIR/db-$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
  echo "Backing up SQLite database to $BACKUP_FILE..."
  "$PYTHON" - "$DB_PATH" "$BACKUP_FILE" <<'PY'
import sqlite3
import sys

source_path, backup_path = sys.argv[1:3]
with sqlite3.connect(source_path) as source:
    with sqlite3.connect(backup_path) as backup:
        source.backup(backup)
PY
fi

echo "Applying database migrations..."
"$PYTHON" "$MANAGE_PY" migrate --noinput

echo "Restarting $SERVICE_NAME..."
sudo -n /usr/bin/systemctl restart "$SERVICE_NAME"

echo "Verifying systemd service..."
sudo -n /usr/bin/systemctl is-active --quiet "$SERVICE_NAME" \
  || fail "$SERVICE_NAME did not become active after restart."

echo "Deployment successful: $TARGET_SHA"
