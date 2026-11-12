# Live browser: Chromium on a virtual display, viewable/controllable from your phone via noVNC,
# drivable by Codex over the Chrome DevTools Protocol (CDP).
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium xvfb x11vnc fluxbox novnc websockify socat fonts-liberation ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m browser
COPY start.sh /usr/local/bin/start.sh
RUN chmod +x /usr/local/bin/start.sh
USER browser
ENV DISPLAY=:99
EXPOSE 6080 9222
CMD ["/usr/local/bin/start.sh"]
