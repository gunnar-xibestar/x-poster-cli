#!/usr/bin/env bash
# x-poster-cli installer (Linux). Usage: ./install.sh [--uninstall [--purge]]
# Never uses sudo. Safe to re-run.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
LAUNCHER="${BIN_DIR}/xbot"
CONFIG_DIR="${XBOT_CONFIG_DIR:-${HOME}/.config/xbot}"
STATE_DIR="${XBOT_STATE_DIR:-${HOME}/.local/state/xbot}"
PY="${PYTHON:-python3}"

say() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

if [[ "${1:-}" == "--uninstall" ]]; then
  rm -f "$LAUNCHER" && say "removed $LAUNCHER"
  rm -rf "${REPO_DIR}/.venv" && say "removed ${REPO_DIR}/.venv"
  if [[ "${2:-}" == "--purge" ]]; then
    rm -rf "$CONFIG_DIR" "$STATE_DIR" && say "removed $CONFIG_DIR and $STATE_DIR (keys and state)"
  else
    say "kept $CONFIG_DIR (your keys) and $STATE_DIR; use --uninstall --purge to delete them"
  fi
  exit 0
fi
[[ $# -eq 0 ]] || die "unknown option: $1 (use --uninstall [--purge])"

command -v "$PY" >/dev/null 2>&1 || die "python3 not found. Install Python 3.10+ (e.g. sudo apt install python3 python3-venv)"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || die "Python 3.10+ required, found $("$PY" -V 2>&1)"
"$PY" -c 'import venv, ensurepip' >/dev/null 2>&1 \
  || die "python venv module missing. Hint: sudo apt install python3-venv   (then re-run ./install.sh)"

if [[ ! -x "${REPO_DIR}/.venv/bin/python" ]]; then
  say "creating virtualenv in ${REPO_DIR}/.venv"
  "$PY" -m venv "${REPO_DIR}/.venv"
fi
say "installing dependencies"
"${REPO_DIR}/.venv/bin/python" -m pip install -q --upgrade pip
"${REPO_DIR}/.venv/bin/python" -m pip install -q -r "${REPO_DIR}/requirements.txt"

mkdir -p "$BIN_DIR"
cat > "$LAUNCHER" <<LAUNCH
#!/usr/bin/env bash
export XBOT_CWD="\$PWD"; cd "${REPO_DIR}" && exec "${REPO_DIR}/.venv/bin/python" -m xbot "\$@"
LAUNCH
chmod 755 "$LAUNCHER"
say "launcher: $LAUNCHER"

mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
if [[ ! -f "${CONFIG_DIR}/env" ]]; then
  cp "${REPO_DIR}/.env.example" "${CONFIG_DIR}/env"
  say "created ${CONFIG_DIR}/env from template (edit it to add your keys)"
else
  say "kept existing ${CONFIG_DIR}/env"
fi
chmod 600 "${CONFIG_DIR}/env"

case ":${PATH}:" in
  *":${BIN_DIR}:"*) ;;
  *) say "add ~/.local/bin to PATH:  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc && source ~/.bashrc" ;;
esac
say "done. Edit ${CONFIG_DIR}/env, then run: xbot   (dry-run by default)"
