# LANGINGPAGE-TTY

An ASCII-art boot screen for your terminal: a looping earth animation on the
left, and a greeting that types itself out on the right.

```
Hello <you>,
And today you are also
going to change the world?

[Enter] start  [h] help
```

Press **Enter** to start your shell, **h** for the help page, or **Ctrl-C** to
quit. The splash only appears if you have not opened a terminal in the last
two hours, so opening a dozen tabs does not replay it a dozen times.

Made by **Trunk Trick** · Feedback: **2451421621@qq.com**

## Features

- 121-frame seamless earth loop (from `ascii.live/earth`), rendered at its
  native 70 ms per frame (about 14.3 fps)
- Character-by-character greeting, about 50 chars/s, with small pauses at
  punctuation and line breaks
- English help page (`h`) with interval, commands and feedback details
- Two-hour cooldown based on the last interactive terminal open
- Manual replays (`earth-intro`) never touch the cooldown timer
- Scales the earth to fit the window instead of clipping it; stacks the text
  below the earth on very narrow terminals
- Fully restores the terminal on exit (alternate screen, cursor, line wrapping)
- No root, no background daemons, no network access at runtime

## Requirements

- Linux or macOS, with `bash`
- `python3` >= 3.7
- A terminal that understands ANSI escape sequences
- Optional: `flock` (Linux) for atomic cooldown updates; without it the rare
  simultaneous-terminal race is tolerated
- `rsync` on both ends only if you use `deploy.sh`

## Install locally

```bash
git clone https://github.com/trunk-trick/LANGINGPAGE-TTY.git
cd LANGINGPAGE-TTY
./install.sh
```

Open a **new terminal** to see the splash.

The installer:

- copies the player and assets to `~/tools/asciiplay/`
- creates `~/.local/bin/asciiplay` and `~/.local/bin/earth-intro`
- appends a marked block to `~/.bashrc`, after making a timestamped backup
- verifies the result with `bash -n` and restores the backup if it fails
- is idempotent: running it again does not duplicate the block

It does not need `sudo` and does not modify anything outside your home
directory.

## Run it manually

```bash
earth-intro
```

Equivalent commands:

```bash
~/.local/bin/earth-intro
python3 ~/tools/asciiplay/earth_intro.py
```

Manual runs are independent of the cooldown and **never** update the
last-open timestamp, so you can replay the splash as often as you like.

## Controls

| Key | Action |
| --- | --- |
| `h` | Open the English help page |
| `Enter` | Close the splash and start the shell |
| Any other key (in help) | Return to the boot screen |
| `Ctrl-C` | Quit the splash immediately |

## Cooldown

Every interactive terminal open records an epoch timestamp in:

```
~/.local/state/asciiplay/last-open
```

The splash plays only when at least `EARTH_INTRO_COOLDOWN` seconds have
passed since that timestamp. The default is `7200` (2 hours).

Open terminals more often than every two hours and you will not see it again
until you take a two-hour break. This is intentional.

### Change the interval

Edit `~/.bashrc`, find the block `# >>> ascii earth intro >>>`, and change the
default in:

```bash
_earth_cooldown=${EARTH_INTRO_COOLDOWN:-7200}
```

Or set the environment variable before that block in `~/.bashrc`:

```bash
export EARTH_INTRO_COOLDOWN=3600     # seconds
```

For one session only:

```bash
EARTH_INTRO_COOLDOWN=600 bash
```

### Disable the splash

```bash
export EARTH_INTRO=0
```

Add that line before the marked block in `~/.bashrc` (or export it in your
environment). The timestamp is still recorded.

### Play it again now

```bash
rm ~/.local/state/asciiplay/last-open
```

Or simply run `earth-intro`, which does not touch the timer.

## Deploy to a remote host

From your local clone:

```bash
./deploy.sh FA
./deploy.sh faron@testok.top -p 2222
./deploy.sh user@192.168.1.10
```

`<ssh-target>` can be anything `ssh` understands, including an alias from
`~/.ssh/config`. `deploy.sh`:

1. creates `~/tools/asciiplay-src` on the remote host,
2. copies this repository there with `rsync`,
3. runs `install.sh` on the remote host.

Then connect normally:

```bash
ssh FA
```

The splash appears on the remote side, provided the SSH session allocates a
PTY and the remote login shell sources `~/.bashrc`.

Notes:

- `ssh host command` and `ssh -T host` do **not** allocate a PTY and will not
  show the splash.
- If `~/.bash_profile` or `~/.bash_login` exists, make sure it sources
  `~/.bashrc`; otherwise the login shell never reads the hook.
- `TERM=dumb` is skipped on purpose.

## Uninstall

Local:

```bash
./install.sh --uninstall
```

This removes the marked block from `~/.bashrc` (after a backup) and deletes
the two symlinks. The files in `~/tools/asciiplay` and the cooldown state are
left behind; remove them manually if you want:

```bash
rm -rf ~/tools/asciiplay ~/.local/state/asciiplay
```

Remote:

```bash
./deploy.sh FA --uninstall
```

## Repository layout

```
asciiplay.py        generic ascii.live stream / file player (--fit, --center, ...)
earth_intro.py      the boot screen: earth + typed greeting + help page
assets/earth.ansi   121-frame earth loop, frame markers included
bashrc-snippet.sh   the exact ~/.bashrc block appended by the installer
install.sh          local installer / uninstaller
deploy.sh           remote deployment helper
```

## Troubleshooting

**No splash when I open a terminal**

- Check that the session is interactive and has a PTY (`tty` should print a
  device).
- Check `echo $TERM`; `dumb` is skipped.
- Check the cooldown state: `cat ~/.local/state/asciiplay/last-open`.
- Make sure the block is in the file your shell actually reads. Bash login
  shells read `~/.bash_profile`, `~/.bash_login` or `~/.profile` — not
  `~/.bashrc` directly. If you have a custom `.bash_profile`, source
  `~/.bashrc` from it.

**`earth-intro: command not found`**

Use the full path:

```bash
python3 ~/tools/asciiplay/earth_intro.py
```

and check that `~/.local/bin` is in `PATH`.

**The splash is too big / clipped**

It scales the earth to fit the window (and stacks the text below the earth on
narrow terminals). If your window is extremely small, enlarge it; ANSI text
cannot shrink beyond the smallest usable size.

**`earth-intro` works but the cooldown seems wrong**

Manual runs do not update the timestamp. Only interactive terminal opens do.
Reset with `rm ~/.local/state/asciiplay/last-open`.

## Credits and license

- Earth animation frames: [ascii.live](https://github.com/hugomd/ascii-live)
  by HugoMD, licensed under GPL-3.0.
- Player, boot screen, installers: Trunk Trick.
- This repository is distributed under GPL-3.0; see [LICENSE](LICENSE).

Feedback or questions: **2451421621@qq.com**
