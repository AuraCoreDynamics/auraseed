#!/usr/bin/env sh

FOUND_PYTHON=""

# Try PATH for python3 or python
if command -v python3 >/dev/null 2>&1; then
    FOUND_PYTHON=$(command -v python3)
elif command -v python >/dev/null 2>&1; then
    FOUND_PYTHON=$(command -v python)
else
    # Fallbacks
    FALLBACKS="/usr/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3 /opt/homebrew/bin/python /usr/local/bin/python"
    for p in $FALLBACKS; do
        if [ -x "$p" ]; then
            FOUND_PYTHON="$p"
            break
        fi
    done
fi

if [ -z "$FOUND_PYTHON" ]; then
    echo "[AuraSeed Bootstrapper] Error: Could not locate a base Python executable to bootstrap discovery." >&2
    exit 1
fi

# Execute the auraseed module
exec "$FOUND_PYTHON" -m auraseed "$@"
