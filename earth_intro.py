#!/usr/bin/env python3
"""earth_intro.py — terminal boot screen: looping earth + typed greeting.

Layout: the earth animation runs on the left, the greeting types itself out
on the right.  Press 'h' for an English help page; Enter starts the shell,
any other key leaves the help page.  Ctrl-C also exits.

Run it directly at any time:

    earth-intro
    python3 ~/tools/asciiplay/earth_intro.py

Manual runs never touch the last-open timestamp — that bookkeeping lives
only in the ~/.bashrc hook, so the cooldown is unaffected by replays.
"""

from __future__ import annotations

import argparse
import bisect
import getpass
import os
import select
import shutil
import signal
import sys
import termios
import time
import tty
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import asciiplay as A  # noqa: E402

FPS = 14.2857          # the source animation's own rate (70 ms/frame)
TYPE_CPS = 50.0        # characters per second — fast, but still one by one
HINT = "[Enter] start  [h] help"
HINT_BLINK = 0.55      # seconds per half-cycle


def greeting(user: str) -> list[str]:
    return [
        f"Hello {user},",
        "",
        "And today you are also",
        "going to change the world?",
    ]


def wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        if not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= width:
            cur += " " + word
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    return lines


def help_content(width: int) -> list[str]:
    out: list[str] = []

    def add(text: str) -> None:
        out.extend(wrap(text, width))

    add("EARTH BOOT SCREEN  -  Made by Trunk Trick")
    out.append("")
    add('Interval - the splash plays only if the last terminal open was at '
        'least 2 hours ago (7200 seconds). To change it, edit ~/.bashrc, '
        'find the block "# >>> ascii earth intro >>>" and change the 7200 in:')
    out.append("    _earth_cooldown=${EARTH_INTRO_COOLDOWN:-7200}")
    add("Or set it before that block in ~/.bashrc:")
    out.append("    export EARTH_INTRO_COOLDOWN=3600")
    add("For a single session only:")
    out.append("    EARTH_INTRO_COOLDOWN=600 bash")
    out.append("")
    out.append("Run directly from any terminal:")
    out.append("    earth-intro")
    out.append("    python3 ~/tools/asciiplay/earth_intro.py")
    out.append("Manual runs do not update the last-open timestamp.")
    out.append("")
    out.append("Commands:")
    out.append("    EARTH_INTRO=0      disable the splash")
    out.append("    earth              looping earth only")
    out.append("    rm ~/.local/state/asciiplay/last-open    reset the timer")
    out.append("")
    out.append("Feedback: 2451421621@qq.com")
    out.append("[ Enter ] start the shell      [ any key ] back")
    return out


def build_sequence(lines: list[str], cps: float):
    """Flatten the text into typed chars with per-char timestamps."""
    seq: list[tuple[int, str]] = []
    times: list[float] = []
    t = 0.0
    for i, line in enumerate(lines):
        for ch in line:
            t += 1.0 / cps
            if ch in ",.?!;:":
                t += 0.08
            seq.append((i, ch))
            times.append(t)
        if i < len(lines) - 1:
            t += 0.22
            seq.append((i + 1, "\n"))
            times.append(t)
    return seq, times, t


def revealed(seq, n: int, nlines: int) -> list[str]:
    out = [""] * nlines
    for line_idx, ch in seq[:n]:
        if ch != "\n":
            out[line_idx] += ch
    return out


def compute_layout(cols: int, rows: int, text_lines: list[str]) -> dict:
    need = max(len(line) for line in text_lines)
    gap = 3
    block_h = len(text_lines) + 2          # text + blank + hint
    if cols - need - gap >= 30:
        ew = cols - need - gap
        return {
            "ew": ew, "eh": rows, "text_x": ew + gap,
            "text_top": max(1, (rows - block_h) // 2),
        }
    # too narrow for a side panel: put the text under the earth
    eh = max(1, rows - block_h - 1)
    return {
        "ew": cols, "eh": eh,
        "text_x": max(0, (cols - need) // 2),
        "text_top": eh,
    }


def prepare_earth(frames: list[bytes], ew: int, eh: int) -> list[list[str]]:
    """Pre-fit every frame into an ew x eh box, centred, aspect preserved."""
    cw, ch = A.canvas_size(frames)
    blocks: list[list[str]] = []
    for fr in frames:
        out, ow, oh = A.fit_lines(A.frame_lines(fr), cw, ch, ew, eh)
        top = (eh - oh) // 2
        left = (ew - ow) // 2
        block = ([" " * ew] * top
                 + [" " * left + row + " " * (ew - left - ow) for row in out]
                 + [" " * ew] * (eh - top - oh))
        blocks.append(block)
    return blocks


def compose(block, disp, layout, cols, rows, hint_on, cursor_line, cursor) -> list[str]:
    grid = [[" "] * cols for _ in range(rows)]

    for y, row in enumerate(block[:rows]):
        for x, ch in enumerate(row[:cols]):
            grid[y][x] = ch

    tx = layout["text_x"]
    ty0 = layout["text_top"]
    for i, line in enumerate(disp):
        y = ty0 + i
        if 0 <= y < rows:
            for x, ch in enumerate(line):
                if 0 <= tx + x < cols:
                    grid[y][tx + x] = ch

    if cursor and cursor_line is not None and 0 <= tx + len(disp[cursor_line]) < cols:
        y = ty0 + cursor_line
        if 0 <= y < rows:
            grid[y][tx + len(disp[cursor_line])] = "_"

    if hint_on:
        y = ty0 + len(disp) + 1
        if 0 <= y < rows:
            for x, ch in enumerate(HINT):
                if 0 <= tx + x < cols:
                    grid[y][tx + x] = ch

    return ["".join(row) for row in grid]


def compose_help(cols: int, rows: int) -> list[str]:
    width = max(20, min(cols - 2, 72))
    lines = help_content(width)
    if len(lines) > rows:                       # very short window: drop blanks
        lines = [line for line in lines if line.strip()]
    if len(lines) > rows:
        lines = lines[:rows]
    top = max(0, (rows - len(lines)) // 2)

    block_w = min(cols, max((len(line) for line in lines), default=0))
    left = max(0, (cols - block_w) // 2)
    nonempty = [i for i, line in enumerate(lines) if line.strip()]
    centered = {nonempty[0], nonempty[-1]} if nonempty else set()

    grid = [[" "] * cols for _ in range(rows)]
    for i, line in enumerate(lines):
        y = top + i
        if y >= rows:
            break
        line = line[:block_w]
        if i in centered:                       # title and footer
            x = left + max(0, (block_w - len(line)) // 2)
        else:
            x = left
        for j, ch in enumerate(line):
            if x + j < cols:
                grid[y][x + j] = ch
    return ["".join(row) for row in grid]


def read_key(fd: int, timeout: float):
    r, _, _ = select.select([fd], [], [], timeout)
    if not r:
        return None
    try:
        return os.read(fd, 1)
    except OSError:
        return b""


def term_size() -> tuple[int, int]:
    s = shutil.get_terminal_size((80, 24))
    if s.columns <= 0 or s.lines <= 0:   # ssh -tt with a piped stdin gives 0x0
        return 80, 24
    return s.columns, s.lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Earth boot screen with typed greeting.")
    ap.add_argument("--asset", default=str(HERE / "assets" / "earth.ansi"))
    ap.add_argument("--user", default=os.environ.get("USER") or getpass.getuser())
    ap.add_argument("--cps", type=float, default=TYPE_CPS, help="typing speed")
    ap.add_argument("--no-wait", action="store_true",
                    help="exit once the text is typed (for testing)")
    args = ap.parse_args(argv)

    if args.cps <= 0:
        ap.error("--cps must be > 0")

    try:
        frames = A.read_file_frames(args.asset)
    except OSError as exc:
        print(f"earth_intro: cannot read {args.asset}: {exc}", file=sys.stderr)
        return 2
    if not frames:
        print(f"earth_intro: no frames in {args.asset}", file=sys.stderr)
        return 2

    lines = greeting(args.user)
    seq, times, total = build_sequence(lines, args.cps)

    tty_out = sys.stdout.isatty()
    interactive = tty_out and sys.stdin.isatty()
    fd = sys.stdin.fileno()

    old_term = None
    if interactive:
        try:
            old_term = termios.tcgetattr(fd)
            tty.setcbreak(fd)
        except termios.error:
            interactive = False

    def restore() -> None:
        if tty_out:
            try:
                sys.stdout.write(A.WRAP_ON + A.CUR_SHOW + A.ALT_OFF)
                sys.stdout.flush()
            except Exception:  # noqa: BLE001 - best effort on exit
                pass
        if old_term is not None:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_term)
            except Exception:  # noqa: BLE001
                pass

    def on_signal(signum, frame):  # noqa: ARG001
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, on_signal)
    old_int = signal.signal(signal.SIGINT, on_signal)

    if tty_out:
        sys.stdout.write(A.ALT_ON + A.WRAP_OFF + A.CUR_HIDE + A.HOME + A.CLEAR)
        sys.stdout.flush()

    try:
        cols, rows = term_size()
        layout = compute_layout(cols, rows, lines)
        blocks = prepare_earth(frames, layout["ew"], layout["eh"])
        last_size = (cols, rows)
        last_state = None
        mode = "boot"
        start = time.monotonic()

        def draw(screen: list[str]) -> None:
            sys.stdout.write(A.SYNC_ON + A.HOME + "\r\n".join(screen)
                             + A.ERASE_BELOW + A.SYNC_OFF)
            sys.stdout.flush()

        while True:
            now = time.monotonic()
            elapsed = now - start

            cols, rows = term_size()
            if (cols, rows) != last_size:
                layout = compute_layout(cols, rows, lines)
                blocks = prepare_earth(frames, layout["ew"], layout["eh"])
                last_size = (cols, rows)
                last_state = None

            if mode == "help":
                state = ("help", cols, rows)
                if state != last_state:
                    draw(compose_help(cols, rows))
                    last_state = state
            else:
                n = min(len(seq), bisect.bisect_right(times, elapsed))
                done = n >= len(seq)
                frame_i = int(elapsed * FPS) % len(frames)
                hint_on = (not done) or (int((elapsed - total) / HINT_BLINK) % 2 == 0)
                cursor_line = seq[n][0] if n < len(seq) else None

                state = ("boot", n, frame_i, hint_on, cols, rows, done)
                if state != last_state:
                    disp = revealed(seq, n, len(lines))
                    draw(compose(blocks[frame_i], disp, layout, cols, rows,
                                 hint_on, cursor_line, not done))
                    last_state = state

            if interactive:
                key = read_key(fd, 0.004)
                if key:
                    enter = key in (b"\r", b"\n")
                    if mode == "help":
                        if enter:
                            break
                        mode = "boot"
                        last_state = None
                    else:
                        if enter:
                            break
                        if key in (b"h", b"H"):
                            mode = "help"
                            last_state = None
            else:
                if args.no_wait or elapsed > total + 0.5:
                    break
                time.sleep(0.004)
    except KeyboardInterrupt:
        pass
    finally:
        if interactive:
            try:
                termios.tcflush(fd, termios.TCIFLUSH)  # don't leak keys to bash
            except Exception:  # noqa: BLE001
                pass
        restore()
        signal.signal(signal.SIGINT, old_int)

    return 0


if __name__ == "__main__":
    sys.exit(main())
