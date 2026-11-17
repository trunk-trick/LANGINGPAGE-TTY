#!/usr/bin/env bash
# Deploy the boot screen to a remote host over SSH.
set -euo pipefail

SRC="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat <<EOF
Usage: ./deploy.sh <ssh-target> [-p PORT] [--uninstall]

  <ssh-target>   anything ssh understands: a host alias (e.g. FA),
                 user@host, or user@host.domain
  -p, --port N   SSH port (default: 22 or whatever ~/.ssh/config says)
  --uninstall    remove the boot screen on the remote host

Examples:
  ./deploy.sh FA
  ./deploy.sh faron@testok.top -p 2222
  ./deploy.sh user@192.168.1.10
  ./deploy.sh user@host --uninstall
EOF
}

command -v rsync >/dev/null 2>&1 || {
    echo "deploy: rsync is required on this machine" >&2
    exit 1
}

TARGET="${1:-}"
case "$TARGET" in
    ""|-h|--help) usage >&2; exit 2 ;;
esac
shift

PORT=""
UNINSTALL=0
while [ $# -gt 0 ]; do
    case "$1" in
        -p|--port)
            PORT="${2:-}"
            [ -n "$PORT" ] || { usage >&2; exit 2; }
            shift 2
            ;;
        --uninstall) UNINSTALL=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "deploy: unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

SSH=(ssh)
RSYNC_SSH="ssh"
if [ -n "$PORT" ]; then
    SSH+=(-p "$PORT")
    RSYNC_SSH="ssh -p $PORT"
fi

STAGE='~/tools/asciiplay-src'

echo "==> staging files on $TARGET"
"${SSH[@]}" "$TARGET" "mkdir -p $STAGE"
rsync -az --delete \
    --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
    -e "$RSYNC_SSH" "$SRC/" "$TARGET:$STAGE/"

echo "==> running installer on $TARGET"
if [ "$UNINSTALL" = 1 ]; then
    "${SSH[@]}" "$TARGET" "bash $STAGE/install.sh --uninstall"
else
    "${SSH[@]}" "$TARGET" "bash $STAGE/install.sh"
fi

echo
if [ -n "$PORT" ]; then
    echo "Done. Connect with:  ssh -p $PORT $TARGET"
else
    echo "Done. Connect with:  ssh $TARGET"
fi
