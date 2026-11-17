#!/usr/bin/env python3
"""asciiplay — play an ascii.live stream (or a saved capture) in place.

The server sends a *stream of complete frames*, each prefixed with
``ESC[2J ESC[H`` (clear screen + cursor home).  Fed straight to a terminal
that works, but it falls apart when the frame is wider/taller than the
window (line wrapping scrolls the screen), or when the output goes through
a file / pager / anything that shows the raw bytes.

This player fixes the geometry: it buffers a few frames, crops them to the
terminal, pins the drawing to a fixed origin, and replays them at a steady
frame rate on the alternate screen buffer (so the scrollback stays clean).

Usage:
    asciiplay                 # https://ascii.live/donut
    asciiplay rick            # https://ascii.live/rick
    asciiplay https://ascii.live/cat
    asciiplay --file donut.ansi --loop
    asciiplay --fps 15 --center

Ctrl-C to quit.
"""

from __future__ import annotations

import argparse
import atexit
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque

MARK = b"\x1b[2J\x1b[H"  # frame delimiter used by ascii.live
DEFAULT_URL = "https://ascii.live/donut"

ALT_ON = "\x1b[?1049h"   # enter alternate screen buffer
ALT_OFF = "\x1b[?1049l"  # back to the normal screen + scrollback
CUR_HIDE = "\x1b[?25l"
CUR_SHOW = "\x1b[?25h"
WRAP_OFF = "\x1b[?7l"    # don't let a too-wide line wrap and scroll
WRAP_ON = "\x1b[?7h"
HOME = "\x1b[H"
ERASE_BELOW = "\x1b[J"
CLEAR = "\x1b[2J"
SYNC_ON = "\x1b[?2026h"   # synchronized update: terminals that know it paint the
SYNC_OFF = "\x1b[?2026l"  # whole frame at once (no tearing); others ignore it


def term_size() -> tuple[int, int]:
    s = shutil.get_terminal_size(fallback=(80, 24))
    if s.columns <= 0 or s.lines <= 0:   # some ptys report 0x0 (e.g. ssh -tt with a pipe)
        return 80, 24
    return s.columns, s.lines


class FrameReader(threading.Thread):
    """Pull curl output, split it on the frame marker, push frames to a deque."""

    def __init__(self, cmd: list[str], queue: deque[bytes], maxlen: int = 1200):
        super().__init__(daemon=True)
        self.cmd = cmd
        self.queue = queue
        self.proc: subprocess.Popen[bytes] | None = None
        self.finished = threading.Event()
        self.error: str | None = None
        self._stop = threading.Event()

    def run(self) -> None:
        try:
            self.proc = subprocess.Popen(
                self.cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                bufsize=0,
            )
            buf = b""
            seen_first = False
            assert self.proc.stdout is not None
            while not self._stop.is_set():
                chunk = self.proc.stdout.read(4096)
                if not chunk:
                    break
                buf += chunk
                while True:
                    i = buf.find(MARK)
                    if i < 0:
                        # No complete marker yet: KEEP the whole buffer — it is
                        # the head of the next frame, not junk. (Trimming it to
                        # len(MARK)-1 bytes used to eat ~1.3 KB of every frame.)
                        if len(buf) > 1 << 20:  # pathological stream, bound memory
                            buf = buf[-65536:]
                        break
                    frame, buf = buf[:i], buf[i + len(MARK):]
                    if seen_first and frame.strip():
                        self.queue.append(frame)
                    seen_first = True
            if self.proc.wait() not in (0, None) and not self._stop.is_set():
                self.error = f"curl exited with {self.proc.returncode}"
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self.error = repr(exc)
        finally:
            self.finished.set()

    def stop(self) -> None:
        self._stop.set()
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                pass


def read_file_frames(path: str) -> list[bytes]:
    with open(path, "rb") as fh:
        data = fh.read()
    parts = data.split(MARK)
    frames = [p.split(b"\x1b[2J")[0] for p in parts[1:]]
    # a capture that starts mid-frame still has its trailing part in parts[0]
    if parts[0].strip():
        head = parts[0].split(b"\x1b[2J")[-1]
        tail = head.split(b"\x1b[H", 1)[-1]
        if tail.strip():
            frames.insert(0, tail)
    return [f for f in frames if f.strip()]


def frame_lines(frame: bytes) -> list[str]:
    text = frame.decode("utf-8", "replace")
    lines = text.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return [line.rstrip("\r") for line in lines]


def canvas_size(frames: list[bytes]) -> tuple[int, int]:
    w = h = 0
    for fr in frames:
        lines = frame_lines(fr)
        h = max(h, len(lines))
        for line in lines:
            w = max(w, len(line))
    return max(w, 1), max(h, 1)


# how "heavy" each glyph looks; used when shrinking art to fit the window
DENSITY = {
    " ": 0, ".": 1, ",": 1, "'": 1, "`": 1, ":": 2, ";": 2, "-": 2, "~": 2,
    "_": 2, "=": 3, "+": 3, "*": 3, "!": 3, "o": 4, "s": 4, "y": 4, "░": 2,
    "▒": 4, "▓": 6, "▚": 5, "▀": 4, "▄": 4, "▌": 4, "▐": 4, "█": 8, "h": 5,
    "d": 5, "N": 6, "@": 7, "#": 6, "%": 5, "$": 5, "&": 5, "8": 6,
}


def fit_lines(
    lines: list[str], canvas_w: int, canvas_h: int, cols: int, rows: int,
) -> tuple[list[str], int, int]:
    """Shrink (never enlarge) the canvas to fit the window, keeping aspect.

    Max-pooling over each source block keeps thin strokes alive, which matters
    for line art such as the earth.
    """
    lines = list(lines[:canvas_h])
    lines += [" " * canvas_w] * (canvas_h - len(lines))
    lines = [line.ljust(canvas_w)[:canvas_w] for line in lines]

    scale = min(cols / canvas_w, rows / canvas_h, 1.0)
    out_w = max(1, int(canvas_w * scale))
    out_h = max(1, int(canvas_h * scale))
    if out_w == canvas_w and out_h == canvas_h:
        return lines, canvas_w, canvas_h

    out = []
    for y in range(out_h):
        y0 = y * canvas_h // out_h
        y1 = min(canvas_h, max(y0 + 1, -(-(y + 1) * canvas_h // out_h)))
        row = []
        for x in range(out_w):
            x0 = x * canvas_w // out_w
            x1 = min(canvas_w, max(x0 + 1, -(-(x + 1) * canvas_w // out_w)))
            best, best_d = " ", -1
            for src in lines[y0:y1]:
                for ch in src[x0:x1]:
                    d = DENSITY.get(ch, 3)
                    if d > best_d:
                        best, best_d = ch, d
            row.append(best)
        out.append("".join(row))
    return out, out_w, out_h


def render(
    lines: list[str],
    canvas_w: int,
    canvas_h: int,
    cols: int,
    rows: int,
    center: bool,
    fit: bool,
) -> str:
    if fit:
        lines, canvas_w, _ = fit_lines(lines, canvas_w, canvas_h, cols, rows)

    if center:
        top = (rows - len(lines)) // 2
        left = (cols - canvas_w) // 2
    else:
        top = left = 0

    # negative top/left means the canvas is bigger than the window:
    # crop it from the centre rather than from the top-left corner
    if top < 0:
        lines = lines[-top:]
        top = 0
    if left < 0:
        lines = [line[-left:] for line in lines]
        left = 0

    lines = lines[: max(0, rows - top)]
    avail = max(0, cols - left)

    out = [SYNC_ON, HOME]
    if top:
        out.append("\r\n" * top)
    for i, line in enumerate(lines):
        if i:
            out.append("\r\n")
        if left:
            out.append(" " * left)
        line = line[:avail]
        out.append(line)
        if len(line) < avail:
            # pad the row so a longer previous frame leaves no debris behind
            out.append(" " * (avail - len(line)))
    out.append(ERASE_BELOW)
    out.append(SYNC_OFF)
    return "".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Play an ascii.live animation in place at a fixed position.",
    )
    ap.add_argument("target", nargs="?", default="donut",
                    help="donut, a name (ascii.live/<name>), or a full URL")
    ap.add_argument("--file", "-f", help="play a saved capture instead of a URL")
    ap.add_argument("--fps", type=float, default=14.5,
                    help="playback rate (default 14.5, matching the source)")
    ap.add_argument("--prefetch", type=int, default=12,
                    help="frames to buffer before starting (default 12)")
    ap.add_argument("--center", action="store_true", help="center the canvas in the window")
    ap.add_argument("--loop", action="store_true", help="loop a --file capture forever")
    ap.add_argument("--duration", type=float, default=0.0, help="stop after N seconds")
    ap.add_argument("--no-alt", action="store_true",
                    help="stay on the normal screen (debugging / redirecting output)")
    ap.add_argument("--no-wrap-off", action="store_true", help="do not disable line wrapping")
    ap.add_argument("--fit", action="store_true",
                    help="shrink the art to fit a small window instead of cropping it")
    ap.add_argument("--quiet", "-q", action="store_true",
                    help="do not warn when the window is smaller than the art")
    args = ap.parse_args(argv)

    if args.fps <= 0:
        ap.error("--fps must be > 0")
    if args.prefetch < 1:
        ap.error("--prefetch must be >= 1")

    # live streams get a bounded queue (stay near live); files hold all frames
    queue: deque[bytes] = deque(maxlen=None if args.file else 240)
    reader: FrameReader | None = None
    file_frames: list[bytes] = []

    if args.file:
        try:
            file_frames = read_file_frames(args.file)
        except OSError as exc:
            print(f"asciiplay: cannot read {args.file}: {exc}", file=sys.stderr)
            return 2
        if not file_frames:
            print(f"asciiplay: no frames found in {args.file}", file=sys.stderr)
            return 2
        queue.extend(file_frames)
    else:
        url = args.target
        if "://" not in url:
            url = f"https://ascii.live/{url.strip('/')}"
        reader = FrameReader(["curl", "-sN", url], queue)
        reader.start()

    started = time.monotonic()
    # ---- warm-up: wait for a small buffer so playback does not stutter ----
    if reader:
        deadline = started + 6.0
        while len(queue) < args.prefetch and time.monotonic() < deadline:
            if reader.finished.is_set():
                break
            time.sleep(0.02)
    if not queue:
        msg = reader.error if reader and reader.error else "no frames received"
        print(f"asciiplay: {msg}", file=sys.stderr)
        return 1

    # ---- terminal setup ----
    use_alt = not args.no_alt and sys.stdout.isatty()
    wrap_off = not args.no_wrap_off
    tty = sys.stdout.isatty()

    def restore() -> None:
        if tty:
            seq = ""
            if wrap_off:
                seq += WRAP_ON
            seq += CUR_SHOW
            if use_alt:
                seq += ALT_OFF
            try:
                sys.stdout.write(seq)
                sys.stdout.flush()
            except Exception:  # noqa: BLE001 - best effort on exit
                pass

    atexit.register(restore)

    def on_signal(signum, frame):  # noqa: ARG001
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, on_signal)

    if tty:
        setup = ""
        if use_alt:
            setup += ALT_ON
        if wrap_off:
            setup += WRAP_OFF
        setup += CUR_HIDE + HOME + CLEAR
        sys.stdout.write(setup)
        sys.stdout.flush()

    # The canvas is fixed once, so the drawing never drifts as frames rotate.
    canvas_source = file_frames if file_frames else list(queue)
    canvas_w, canvas_h = canvas_size(canvas_source)
    _cols, _rows = term_size()
    if (canvas_w > _cols or canvas_h > _rows) and not args.fit and not args.quiet:
        print(
            f"asciiplay: window {_cols}x{_rows} is smaller than the art "
            f"{canvas_w}x{canvas_h}; cropping to avoid scrolling "
            "(widen the window for the full drawing).",
            file=sys.stderr,
        )
    next_t = time.monotonic()
    play_t0 = next_t          # --duration counts playing time, not warm-up
    period = 1.0 / args.fps

    try:
        while True:
            now = time.monotonic()
            if args.duration and now - play_t0 >= args.duration:
                break

            if queue:
                frame = queue.popleft()
            elif reader and not reader.finished.is_set():
                time.sleep(0.005)
                continue
            elif file_frames:
                if args.loop:
                    for fr in file_frames:
                        queue.append(fr)
                    continue
                break
            else:
                break

            cols, rows = term_size()
            lines = frame_lines(frame)
            sys.stdout.write(render(lines, canvas_w, canvas_h, cols, rows,
                                    args.center, args.fit))
            sys.stdout.flush()

            next_t += period
            delay = next_t - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            elif delay < -0.25:          # badly behind: resync instead of spinning
                next_t = time.monotonic()
    except KeyboardInterrupt:
        pass
    finally:
        if reader:
            reader.stop()
        restore()
        atexit.unregister(restore)

    if reader and reader.error and not file_frames:
        print(f"asciiplay: {reader.error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
