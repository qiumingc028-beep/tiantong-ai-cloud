FROM mcr.microsoft.com/playwright:v1.62.1-noble@sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e

ARG RELEASE_COMMIT=unknown
ARG BUILD_TIME=unknown
LABEL org.opencontainers.image.revision=$RELEASE_COMMIT \
      org.opencontainers.image.created=$BUILD_TIME \
      org.opencontainers.image.base.digest=sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e \
      com.microsoft.playwright.version=1.62.1

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOME=/tmp/runtime-home

RUN rm -f /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        nginx=1.24.0-2ubuntu7.17 \
        novnc=1:1.3.0-2 \
        openbox=3.6.1-12build5 \
        tini=0.19.0-1 \
        websockify=0.10.0+dfsg1-5build2 \
        x11-utils=7.7+6build2 \
        x11vnc=0.9.16-10 \
        xvfb=2:21.1.12-1ubuntu1.6 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 runtime \
    && useradd --uid 10001 --gid runtime --no-create-home --shell /usr/sbin/nologin runtime \
    && mkdir -p /app/services/jd-cloud-browser-runtime /data/jd-session-archives /ms-playwright \
    && chown -R runtime:runtime /app /data/jd-session-archives /ms-playwright

WORKDIR /app/services/jd-cloud-browser-runtime
COPY services/jd-cloud-browser-runtime/package.json services/jd-cloud-browser-runtime/package-lock.json ./
RUN npm ci --omit=dev \
    && npm cache clean --force

COPY services/jd-cloud-browser-runtime/ ./
COPY desktop/jd-workbench/readonly-collector.js /app/desktop/jd-workbench/readonly-collector.js
COPY desktop/jd-workbench/security-policy.js /app/desktop/jd-workbench/security-policy.js
RUN chmod 0555 start-runtime.sh && chown -R runtime:runtime /app

USER runtime
EXPOSE 8787
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["./start-runtime.sh"]
