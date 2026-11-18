# >>> ascii earth sleep >>>
# Idle screensaver: after EARTH_SLEEP_SECONDS without keyboard input at the
# shell prompt, show the earth with "Emmm... the world is sleeping".
# Any key wakes it. Set EARTH_SLEEP_ENABLE=1 to turn the feature on.
EARTH_SLEEP_ENABLE=0        # 1 = enable, 0 = disable
EARTH_SLEEP_SECONDS=300     # idle seconds

# Preview the screensaver on demand:
alias earth-sleep='$HOME/tools/asciiplay/earth_intro.py --sleep'

if [[ $- == *i* && -t 0 && -t 1 && -z ${EARTH_SHELL_WRAPPED:-} \
      && $EARTH_SLEEP_ENABLE != 0 && ${TERM:-dumb} != dumb && -z ${CI:-} \
      && -x $HOME/tools/asciiplay/earth_shell.py ]]; then
    if [[ $EARTH_SLEEP_SECONDS =~ ^[0-9]+$ ]] && (( EARTH_SLEEP_SECONDS > 0 )); then
        export EARTH_SHELL_WRAPPED=1
        exec "$HOME/tools/asciiplay/earth_shell.py" --idle "$EARTH_SLEEP_SECONDS"
    fi
fi
# <<< ascii earth sleep <<<
