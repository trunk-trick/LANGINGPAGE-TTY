#!/usr/bin/env bash
# Install the LANGINGPAGE-TTY terminal boot screen for the current user.
# Idempotent: running it again never duplicates the ~/.bashrc block.
# No root required.
set -euo pipefail

SRC="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/tools/asciiplay"
RC="$HOME/.bashrc"
MARK_BEGIN='# >>> ascii earth intro >>>'
MARK_END='# <<< ascii earth intro <<<'
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/asciiplay"

usage() {
    cat <<EOF
Usage: ./install.sh [--uninstall]

Install for the current user:
  $DEST
  ~/.local/bin/asciiplay       (symlink)
  ~/.local/bin/earth-intro     (symlink)
  a marked block at the end of ~/.bashrc

Options:
  --uninstall   remove the ~/.bashrc block and both symlinks
  -h, --help    show this help
EOF
}

error() { printf 'install: %s\n' "$*" >&2; exit 1; }

UNINSTALL=0
case "${1:-}" in
    --uninstall) UNINSTALL=1 ;;
    -h|--help) usage; exit 0 ;;
    "") ;;
    *) usage >&2; exit 2 ;;
esac

if [ "$UNINSTALL" = 1 ]; then
    if [ -f "$RC" ] && grep -qxF "$MARK_BEGIN" "$RC"; then
        backup="$RC.bak-ascii-earth.$(date +%s)"
        cp -a "$RC" "$backup"
        tmp="$(mktemp)"
        awk -v b="$MARK_BEGIN" -v e="$MARK_END" '
            $0 == b { skip = 1; next }
            $0 == e { skip = 0; next }
            !skip    { print }
        ' "$RC" > "$tmp"
        # drop blank lines that are now at the end of the file
        awk '
            { lines[n++] = $0 }
            END {
                while (n > 0 && lines[n - 1] == "") n--
                for (i = 0; i < n; i++) print lines[i]
            }
        ' "$tmp" > "$RC"
        rm -f "$tmp"
        if ! bash -n "$RC"; then
            cp -a "$backup" "$RC"
            error "restored $RC after a syntax check failure"
        fi
        echo "Removed the boot screen block from $RC (backup: $backup)"
    else
        echo "No boot screen block found in $RC"
    fi
    rm -f "$HOME/.local/bin/asciiplay" "$HOME/.local/bin/earth-intro"
    echo "Removed the symlinks."
    echo "Files are still in $DEST (delete manually if you want)."
    echo "Cooldown state is in $STATE (delete manually if you want)."
    exit 0
fi

# --- preflight ---------------------------------------------------------------
command -v python3 >/dev/null 2>&1 || error "python3 is required"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)' \
    || error "python3 >= 3.7 is required"

for f in asciiplay.py earth_intro.py assets/earth.ansi bashrc-snippet.sh; do
    [ -f "$SRC/$f" ] || error "missing $f — run this script from the repository root"
done

# --- files -------------------------------------------------------------------
mkdir -p "$DEST/assets" "$HOME/.local/bin"
install -m 755 "$SRC/asciiplay.py"   "$DEST/asciiplay.py"
install -m 755 "$SRC/earth_intro.py" "$DEST/earth_intro.py"
install -m 644 "$SRC/assets/earth.ansi" "$DEST/assets/earth.ansi"
ln -sfn "$DEST/asciiplay.py"    "$HOME/.local/bin/asciiplay"
ln -sfn "$DEST/earth_intro.py"  "$HOME/.local/bin/earth-intro"

# --- ~/.bashrc hook ----------------------------------------------------------
touch "$RC"
if grep -qxF "$MARK_BEGIN" "$RC"; then
    echo "Boot screen block already present in $RC; left untouched."
else
    backup="$RC.bak-ascii-earth.$(date +%s)"
    cp -a "$RC" "$backup"
    {
        printf '\n'
        cat "$SRC/bashrc-snippet.sh"
    } >> "$RC"
    if ! bash -n "$RC"; then
        cp -a "$backup" "$RC"
        error "bash syntax check failed; restored $backup"
    fi
    echo "Added the boot screen block to $RC (backup: $backup)"
fi

command -v flock >/dev/null 2>&1 || \
    echo "note: flock not found; cooldown updates are not atomic (only a rare race)"

echo
echo "Installed. Open a new terminal, or run:  earth-intro"
echo "Disable:  export EARTH_INTRO=0   (before the marked block in ~/.bashrc)"
echo "Cooldown: EARTH_INTRO_COOLDOWN=7200   (seconds; default 2 hours)"
echo "Reset:    rm \"$STATE/last-open\""
