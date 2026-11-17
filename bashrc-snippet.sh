# >>> ascii earth intro >>>
# Boot screen: looping earth on the left, greeting types itself on the right.
# Press Enter to start the shell (Ctrl-C also quits).
#   EARTH_INTRO=0                 disable the boot screen
#   EARTH_INTRO_COOLDOWN=7200     only play if the last terminal open was at
#                                 least this many seconds ago (default 2 h)
#   earth                         replay the looping earth (Ctrl-C quits)
#   earth-intro                   replay the boot screen
alias earth='$HOME/.local/bin/asciiplay -q --fit --center -f $HOME/tools/asciiplay/assets/earth.ansi --loop --fps 14.29'
alias earth-intro='$HOME/tools/asciiplay/earth_intro.py'
if [[ $- == *i* && -t 0 && -t 1 && -z ${EARTH_INTRO_DONE:-} \
      && ${TERM:-dumb} != dumb && -z ${CI:-} \
      && -x $HOME/tools/asciiplay/earth_intro.py ]]; then
    export EARTH_INTRO_DONE=1
    # --- last-open timestamp (record every interactive terminal open) ---
    _earth_cooldown=${EARTH_INTRO_COOLDOWN:-7200}
    [[ $_earth_cooldown =~ ^[0-9]+$ ]] || _earth_cooldown=7200
    _earth_state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/asciiplay"
    _earth_stamp="$_earth_state_dir/last-open"
    _earth_show=1
    if mkdir -p "$_earth_state_dir" 2>/dev/null; then
        _earth_show=$(
            if command -v flock >/dev/null 2>&1; then
                exec 9>"$_earth_stamp.lock" 2>/dev/null && flock 9
            fi
            _earth_last=$(cat "$_earth_stamp" 2>/dev/null || echo 0)
            [[ $_earth_last =~ ^[0-9]+$ ]] || _earth_last=0
            _earth_now=$(date +%s)
            if (( _earth_now - _earth_last >= _earth_cooldown )); then
                echo 1
            else
                echo 0
            fi
            { printf '%s\n' "$_earth_now" > "$_earth_stamp"; } 2>/dev/null
            command -v flock >/dev/null 2>&1 && exec 9>&-
        )
    fi
    if [[ $_earth_show == 1 && ${EARTH_INTRO:-1} != 0 ]]; then
        "$HOME/tools/asciiplay/earth_intro.py"
    fi
    unset _earth_cooldown _earth_state_dir _earth_stamp _earth_show
fi
# <<< ascii earth intro <<<
