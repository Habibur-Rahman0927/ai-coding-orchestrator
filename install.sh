#!/bin/sh
set -eu
if [ "$(uname -s)" != Linux ]; then
    echo "Linux is required" >&2
    exit 2
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3.8 or newer is required" >&2
    exit 2
fi
python_version=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])') || python_version=unknown
case "$python_version" in
    3.[89]|3.[1-9][0-9]*|[4-9].*) ;;
    *) echo "Python 3.8 or newer is required (found $python_version)" >&2; exit 2 ;;
esac
if ! command -v git >/dev/null 2>&1; then
    echo "git is required" >&2
    exit 2
fi
for tool in claude codex gh ssh-keygen; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "Warning: $tool NOT FOUND" >&2
    fi
done
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 -I "$script_dir/engine/lib/ccx_install.py" install "$@"
