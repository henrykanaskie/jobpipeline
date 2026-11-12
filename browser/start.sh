#!/usr/bin/env bash
set -euo pipefail
: "${VNC_PASSWORD:?set VNC_PASSWORD}"
mkdir -p ~/.vnc && x11vnc -storepasswd "$VNC_PASSWORD" ~/.vnc/passwd >/dev/null

Xvfb :99 -screen 0 1366x900x24 -nolisten tcp &
sleep 1
fluxbox >/dev/null 2>&1 &
# Chromium only binds CDP to 127.0.0.1, so socat republishes it on the container network.
chromium --user-data-dir=/profile --remote-debugging-port=9223 --remote-allow-origins='*' \
         --no-first-run --no-default-browser-check --start-maximized about:blank >/dev/null 2>&1 &
socat TCP-LISTEN:9222,fork,reuseaddr TCP:127.0.0.1:9223 &
x11vnc -display :99 -forever -shared -rfbauth ~/.vnc/passwd -rfbport 5900 -localhost -quiet &
exec websockify --web /usr/share/novnc 6080 localhost:5900
