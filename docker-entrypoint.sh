#!/bin/sh
set -eu

for script in /docker-init.d/*.sh; do
    [ -f "$script" ] || continue
    case "$script" in
        *.sh)
            . "$script"
            ;;
    esac
done

ph-cli db restore

exec "$@"