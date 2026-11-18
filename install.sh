#!/usr/bin/env bash
# Install the LANGINGPAGE-TTY terminal boot screen for the current user.
# Idempotent: running it again never duplicates a ~/.bashrc block.
# No root required.
set -euo pipefail

SRC="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/tools/asciiplay"
RC="$HOME/.bashrc"
INTRO_BEGIN='# >>> ascii earth intro >>>'
INTRO_END='# <<< ascii earth intro <<<'
SLEEP_BEGIN='# >>> ascii earth sleep >>>'
SLEEP_END='# <<< ascii earth sleep <<<'
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/asciiplay"

usage() {
    cat <<EOF
Usage: ./install.sh [--uninstall]

Install for the current user:
  $DEST
  ~/.local/bin/asciiplay       (symlink)
  ~/.local/bin/earth-intro     (symlink)
  an intro block at the end of ~/.bashrc
  an idle-sleep block at the top of ~/.bashrc (disabled by default)

Options:
  --uninstall   remove both ~/.bashrc blocks and the symlinks
  -h, --help    show this help
EOF
}

error() { printf 'install: %s\n' "$*" >&2; exit 1; }

remove_block() {
    local begin="$1" end="$2" file="$3"
    local tmp
    tmp="$(mktemp)"
    awk -v b="$begin" -v e="$end" '
        $0 == b { skip = 1; next }
        $0 == e { skip = 0; next }
        !skip    { print }
    ' "$file" > "$tmp"
    cat "$tmp" > "$file"
    rm -f "$tmp"
}

trim_trailing_blanks() {
    local file="$1" tmp
    tmp="$(mktemp)"
    awk '
        { lines[n++] = $0 }
        END {
            while (n > 0 && lines[n - 1] == "") n--
            for (i = 0; i < n; i++) print lines[i]
        }
    ' "$file" > "$tmp"
    cat "$tmp" > "$file"
    rm -f "$tmp"
}

UNINSTALL=0
case "${1:-}" in
    --uninstall) UNINSTALL=1 ;;
    -h|--help) usage; exit 0 ;;
    "") ;;
    *) usage >&2; exit 2 ;;
esac

if [ "$UNINSTALL" = 1 ]; then
    if [ -f "$RC" ] && { grep -qxF "$INTRO_BEGIN" "$RC" || grep -qxF "$SLEEP_BEGIN" "$RC"; }; then
        backup="$RC.bak-ascii-earth.$(date +%s)"
        cp -a "$RC" "$backup"
        remove_block "$SLEEP_BEGIN" "$SLEEP_END" "$RC"
        remove_block "$INTRO_BEGIN" "$INTRO_END" "$RC"
        trim_trailing_blanks "$RC"
        if ! bash -n "$RC"; then
            cp -a "$backup" "$RC"
            error "restored $RC after a syntax check failure"
        fi
        echo "Removed the boot screen blocks from $RC (backup: $backup)"
    else
        echo "No boot screen blocks found in $RC"
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

for f in asciiplay.py earth_intro.py earth_shell.py \
         assets/earth.ansi bashrc-snippet.sh bashrc-sleep-snippet.sh; do
    [ -f "$SRC/$f" ] || error "missing $f — run this script from the repository root"
done

# --- files -------------------------------------------------------------------
mkdir -p "$DEST/assets" "$HOME/.local/bin"
install -m 755 "$SRC/asciiplay.py"   "$DEST/asciiplay.py"
install -m 755 "$SRC/earth_intro.py" "$DEST/earth_intro.py"
install -m 755 "$SRC/earth_shell.py" "$DEST/earth_shell.py"
install -m 644 "$SRC/assets/earth.ansi" "$DEST/assets/earth.ansi"
ln -sfn "$DEST/asciiplay.py"    "$HOME/.local/bin/asciiplay"
ln -sfn "$DEST/earth_intro.py"  "$HOME/.local/bin/earth-intro"

# --- ~/.bashrc hooks ---------------------------------------------------------
touch "$RC"
need_sleep=0
need_intro=0
grep -qxF "$SLEEP_BEGIN" "$RC" || need_sleep=1
grep -qxF "$INTRO_BEGIN" "$RC" || need_intro=1

if [ "$need_sleep" = 0 ]; then
    echo "Idle-sleep block already present in $RC; left untouched."
fi
if [ "$need_intro" = 0 ]; then
    echo "Boot screen block already present in $RC; left untouched."
fi

if [ "$need_sleep" = 1 ] || [ "$need_intro" = 1 ]; then
    backup="$RC.bak-ascii-earth.$(date +%s)"
    cp -a "$RC" "$backup"

    if [ "$need_sleep" = 1 ]; then
        tmp="$(mktemp)"
        {
            cat "$SRC/bashrc-sleep-snippet.sh"
            printf '\n'
            cat "$RC"
        } > "$tmp"
        cat "$tmp" > "$RC"
        rm -f "$tmp"
        echo "Added the idle-sleep block to the top of $RC"
    fi

    if [ "$need_intro" = 1 ]; then
        {
            printf '\n'
            cat "$SRC/bashrc-snippet.sh"
        } >> "$RC"
        echo "Added the boot screen block to the end of $RC"
    fi

    if ! bash -n "$RC"; then
        cp -a "$backup" "$RC"
        error "bash syntax check failed; restored $backup"
    fi
    echo "Backup: $backup"
fi

command -v flock >/dev/null 2>&1 || \
    echo "note: flock not found; cooldown updates are not atomic (only a rare race)"

echo
echo "Installed. Open a new terminal, or run:  earth-intro"
echo "Disable boot screen:  export EARTH_INTRO=0"
echo "Cooldown:             EARTH_INTRO_COOLDOWN=7200   (seconds; default 2 hours)"
echo "Reset cooldown:       rm \"$STATE/last-open\""
echo "Idle screensaver:      EARTH_SLEEP_ENABLE=1 and EARTH_SLEEP_SECONDS=300"
echo "                       (both live in the sleep block at the top of ~/.bashrc)"
echo "Preview screensaver:   earth-sleep"
