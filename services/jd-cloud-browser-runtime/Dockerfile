FROM node:20-bookworm-slim

ARG RELEASE_COMMIT=unknown
ARG BUILD_TIME=unknown
LABEL org.opencontainers.image.revision=$RELEASE_COMMIT \
      org.opencontainers.image.created=$BUILD_TIME

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOME=/tmp/runtime-home

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        novnc openbox tini websockify x11-utils x11vnc xvfb \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 runtime \
    && useradd --uid 10001 --gid runtime --no-create-home --shell /usr/sbin/nologin runtime \
    && mkdir -p /app/services/jd-cloud-browser-runtime /data/jd-session-archives /ms-playwright \
    && chown -R runtime:runtime /app /data/jd-session-archives /ms-playwright

WORKDIR /app/services/jd-cloud-browser-runtime
COPY services/jd-cloud-browser-runtime/package.json services/jd-cloud-browser-runtime/package-lock.json ./
RUN npm ci --omit=dev \
    && npx playwright install-deps chromium \
    && npx playwright install chromium \
    && npm cache clean --force

COPY services/jd-cloud-browser-runtime/ ./
COPY desktop/jd-workbench/readonly-collector.js /app/desktop/jd-workbench/readonly-collector.js
COPY desktop/jd-workbench/security-policy.js /app/desktop/jd-workbench/security-policy.js
RUN chmod 0555 start-runtime.sh && chown -R runtime:runtime /app

USER runtime
EXPOSE 8787 6080
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["./start-runtime.sh"]
