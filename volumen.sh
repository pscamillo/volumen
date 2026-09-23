#!/usr/bin/env bash
# volumen.sh — start Volumen. Works from a .desktop shortcut too: a
# non-interactive shell does not read ~/.bashrc, so uv is put on PATH here.
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$HERE/volumen.log"

say() {
  if command -v zenity >/dev/null; then zenity --error --width=700 --title="Volumen" --text="$1"
  elif command -v xmessage >/dev/null; then xmessage -center "$1"
  else echo "$1" >&2; fi
}

cd "$HERE" || { say "Folder not found: $HERE"; exit 1; }
UV="$(command -v uv)"
[ -z "$UV" ] && { say "uv was not found on PATH.

Install it from https://docs.astral.sh/uv/ and run again."; exit 1; }

echo "=== $(date '+%F %T')" >>"$LOG"
"$UV" run app.py >>"$LOG" 2>&1
rc=$?
echo "--- exit $rc" >>"$LOG"
[ "$rc" -ne 0 ] && say "Volumen exited with error $rc.

Last lines of $LOG:

$(tail -n 25 "$LOG")"
exit "$rc"
