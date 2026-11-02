#!/usr/bin/env sh

FOUND_PYTHON=""

test_valid_python() {
    cmd="$1"
    if [ -x "$cmd" ]; then
        if "$cmd" -c "import sys; sys.exit(0)" >/dev/null 2>&1; then
            return 0
        fi
    fi
    return 1
}

# 1. Try PATH for python3 or python
if command -v python3 >/dev/null 2>&1 && test_valid_python "$(command -v python3)"; then
    FOUND_PYTHON=$(command -v python3)
elif command -v python >/dev/null 2>&1 && test_valid_python "$(command -v python)"; then
    FOUND_PYTHON=$(command -v python)
else
    # 2. Fallbacks
    FALLBACKS="/usr/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3 /opt/homebrew/bin/python /usr/local/bin/python"
    for p in $FALLBACKS; do
        if test_valid_python "$p"; then
            FOUND_PYTHON="$p"
            break
        fi
    done
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

# 3. Check bootstrapped Python in repo or fallback directories
if [ -z "$FOUND_PYTHON" ]; then
    if test_valid_python "$SCRIPT_DIR/.bootstrapped_python/bin/python"; then
        FOUND_PYTHON="$SCRIPT_DIR/.bootstrapped_python/bin/python"
    elif test_valid_python "$HOME/.local/share/auraseed/base_python/bin/python"; then
        FOUND_PYTHON="$HOME/.local/share/auraseed/base_python/bin/python"
    elif test_valid_python "$HOME/Library/Application Support/auraseed/base_python/bin/python"; then
        FOUND_PYTHON="$HOME/Library/Application Support/auraseed/base_python/bin/python"
    fi
fi

# 4. If still not found, bootstrap using bootstrap.json
CONFIG_FILE="${AURASEED_BOOTSTRAP_CONFIG:-$SCRIPT_DIR/bootstrap.json}"
if [ -z "$FOUND_PYTHON" ] && [ -f "$CONFIG_FILE" ]; then
    echo "[AuraSeed Bootstrapper] No base Python installation found on host."
    echo "[AuraSeed Bootstrapper] Initiating zero-privilege bootstrap from $CONFIG_FILE..."

    OS_NAME=$(uname -s | tr '[:upper:]' '[:lower:]')
    ARCH_NAME=$(uname -m)
    if [ "$ARCH_NAME" = "x86_64" ] || [ "$ARCH_NAME" = "amd64" ]; then
        NORM_ARCH="x86_64"
    elif [ "$ARCH_NAME" = "arm64" ] || [ "$ARCH_NAME" = "aarch64" ]; then
        NORM_ARCH="arm64"
    else
        NORM_ARCH="$ARCH_NAME"
    fi

    PLATFORM_KEY="${OS_NAME}-${NORM_ARCH}"

    # Extract URL and python subpath using grep/sed/awk
    DOWNLOAD_URL=$(grep -A 10 "\"$PLATFORM_KEY\"" "$CONFIG_FILE" | grep '"url"' | head -n 1 | sed 's/.*"url": *"\([^"]*\)".*/\1/')
    PYTHON_SUBPATH=$(grep -A 10 "\"$PLATFORM_KEY\"" "$CONFIG_FILE" | grep '"python_subpath"' | head -n 1 | sed 's/.*"python_subpath": *"\([^"]*\)".*/\1/')
    if [ -z "$PYTHON_SUBPATH" ]; then
        PYTHON_SUBPATH="bin/python"
    fi

    if [ -n "$DOWNLOAD_URL" ]; then
        # Check permissions for repo directory
        INSTALL_DIR="$SCRIPT_DIR/.bootstrapped_python"
        CAN_WRITE=0
        mkdir -p "$INSTALL_DIR" 2>/dev/null && touch "$INSTALL_DIR/.perm_check" 2>/dev/null && rm -f "$INSTALL_DIR/.perm_check" 2>/dev/null && CAN_WRITE=1

        if [ "$CAN_WRITE" -ne 1 ]; then
            if [ "$OS_NAME" = "darwin" ]; then
                INSTALL_DIR="$HOME/Library/Application Support/auraseed/base_python"
            else
                INSTALL_DIR="$HOME/.local/share/auraseed/base_python"
            fi
            echo "[AuraSeed Bootstrapper] Falling back to user directory: $INSTALL_DIR"
            mkdir -p "$INSTALL_DIR"
        fi

        TEMP_INSTALLER="/tmp/auraseed_installer_$(basename "$DOWNLOAD_URL")"
        echo "[AuraSeed Bootstrapper] Downloading from $DOWNLOAD_URL..."
        if command -v curl >/dev/null 2>&1; then
            curl -fL -o "$TEMP_INSTALLER" "$DOWNLOAD_URL"
        elif command -v wget >/dev/null 2>&1; then
            wget -O "$TEMP_INSTALLER" "$DOWNLOAD_URL"
        fi

        if [ -f "$TEMP_INSTALLER" ]; then
            echo "[AuraSeed Bootstrapper] Installing to $INSTALL_DIR (non-admin, silent)..."
            sh "$TEMP_INSTALLER" -b -p "$INSTALL_DIR" -u
            rm -f "$TEMP_INSTALLER"

            INSTALLED_EXE="$INSTALL_DIR/$PYTHON_SUBPATH"
            if test_valid_python "$INSTALLED_EXE"; then
                FOUND_PYTHON="$INSTALLED_EXE"
                echo "[AuraSeed Bootstrapper] Successfully provisioned base Python at: $FOUND_PYTHON"

                # Register in ~/.config/auraseed/environments.json or macOS equivalent
                REG_DIR="$HOME/.config/auraseed"
                if [ "$OS_NAME" = "darwin" ]; then
                    REG_DIR="$HOME/Library/Application Support/auraseed"
                fi
                mkdir -p "$REG_DIR"
                MANIFEST_FILE="$REG_DIR/environments.json"
                # Write / update JSON manifest with minimal python call
                "$FOUND_PYTHON" -c "
import json, os
p = '$MANIFEST_FILE'
data = {'version': '1.0', 'environments': {}}
if os.path.exists(p):
    try:
        with open(p, 'r') as f:
            data = json.load(f)
    except Exception:
        pass
data.setdefault('environments', {})['base_bootstrapped'] = {
    'name': 'base_bootstrapped',
    'executable': '$FOUND_PYTHON',
    'install_dir': '$INSTALL_DIR',
    'distribution': 'miniconda',
    'bootstrapped': True
}
with open(p, 'w') as f:
    json.dump(data, f, indent=2)
" 2>/dev/null
                echo "[AuraSeed Bootstrapper] Registered bootstrapped Python in $MANIFEST_FILE."
            fi
        fi
    fi
fi

if [ -z "$FOUND_PYTHON" ]; then
    echo "[AuraSeed Bootstrapper] Error: Could not locate or bootstrap a base Python executable." >&2
    exit 1
fi

# Execute the auraseed module
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"
exec "$FOUND_PYTHON" -m auraseed "$@"
