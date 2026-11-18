#!/usr/bin/env python3
"""earth_shell.py — run the shell behind a small PTY proxy that can sleep.

After `--idle` seconds without keyboard input (and only while the shell is
sitting at its prompt), the proxy shows the earth screensaver:

    Emmm...
    the world is sleeping

Any key wakes it and returns to the shell.  The key is consumed by the
screensaver, not passed to the shell.

This has to sit between the real terminal and the shell: a plain shell cannot
see every keystroke at the prompt, which is what "idle" has to mean here.
The wrapper is started from ~/.bashrc and re-execs the user's shell inside a
PTY; EARTH_SHELL_WRAPPED stops it from wrapping itself again.
"""

from __future__ import annotations

import argparse
import fcntl
import os
import pty
import select
import shutil
import signal
import struct
import subprocess
import sys
import termios
import time
import tty

HERE = os.path.dirname(os.path.abspath(__file__))
INTRO = os.path.join(HERE, "earth_intro.py")
ASSET = os.path.join(HERE, "assets", "earth.ansi")


def set_size(fd: int, rows: int, cols: int) -> None:
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ,
                    struct.pack("HHHH", rows, cols, 0, 0))
    except OSError:
        pass


def at_prompt(master: int, shell_pgrp: int) -> bool:
    """True when the shell itself (not a foreground child) owns the terminal."""
    try:
        return os.tcgetpgrp(master) == shell_pgrp
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run the shell behind an idle-sleeping earth screensaver.")
    ap.add_argument("--idle", type=float, default=300.0,
                    help="seconds without input+output before sleeping (default 300)")
    ap.add_argument("--shell", default=os.environ.get("SHELL", "/bin/bash"))
    ap.add_argument("--asset", default=ASSET)
    args = ap.parse_args(argv)

    if args.idle <= 0:
        ap.error("--idle must be > 0")
    if not os.path.exists(INTRO):
        print(f"earth_shell: missing {INTRO}", file=sys.stderr)
        return 2

    # No PTY (scripts, pipes, CI): just run the shell normally.
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        os.execvp(args.shell, [args.shell, "-i"])

    try:
        cols, rows = os.get_terminal_size(0)
    except OSError:
        cols, rows = shutil.get_terminal_size((80, 24))

    old_term = termios.tcgetattr(0)
    tty.setraw(0)

    pid, master = pty.fork()
    if pid == 0:
        # Child: a fresh login+interactive shell inside the PTY.  The wrapper
        # hook at the top of ~/.bashrc sees EARTH_SHELL_WRAPPED and skips
        # itself, so the rest of the startup files run exactly once here.
        os.environ["EARTH_SHELL_WRAPPED"] = "1"
        try:
            os.execvp(args.shell, [args.shell, "-l", "-i"])
        finally:
            os._exit(127)

    set_size(master, rows, cols)
    shell_pgrp = os.getpgid(pid)

    def on_winch(signum, frame):  # noqa: ARG001
        try:
            c, r = os.get_terminal_size(0)
        except OSError:
            return
        set_size(master, r, c)
        try:
            os.killpg(os.tcgetpgrp(master), signal.SIGWINCH)
        except OSError:
            pass

    signal.signal(signal.SIGWINCH, on_winch)

    def on_term(signum, frame):  # noqa: ARG001
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            pass

    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, on_term)

    last_activity = time.monotonic()
    status = 0

    try:
        while True:
            try:
                readable, _, _ = select.select([0, master], [], [], 0.2)
            except InterruptedError:
                continue

            if 0 in readable:
                try:
                    data = os.read(0, 65536)
                except OSError:
                    break
                if not data:
                    break
                last_activity = time.monotonic()
                try:
                    os.write(master, data)
                except OSError:
                    break

            if master in readable:
                try:
                    data = os.read(master, 65536)
                except OSError:
                    data = b""
                if not data:
                    break
                last_activity = time.monotonic()
                try:
                    os.write(1, data)
                except OSError:
                    break

            if (time.monotonic() - last_activity >= args.idle
                    and at_prompt(master, shell_pgrp)):
                # The screensaver takes over the real terminal and consumes the
                # wake key itself; the shell stays untouched underneath.
                try:
                    subprocess.call(
                        [sys.executable, INTRO, "--sleep", "--asset", args.asset],
                        stdin=0, stdout=1, stderr=2,
                    )
                except OSError:
                    pass
                last_activity = time.monotonic()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            termios.tcsetattr(0, termios.TCSADRAIN, old_term)
        except Exception:  # noqa: BLE001
            pass
        try:
            os.close(master)
        except OSError:
            pass
        try:
            _, status = os.waitpid(pid, 0)
        except OSError:
            status = 0

    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
