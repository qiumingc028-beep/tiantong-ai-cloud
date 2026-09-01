FROM node:20-bookworm-slim
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --omit=dev=false && npx playwright install --with-deps chromium
COPY server.mjs ./
EXPOSE 8787
CMD ["node","server.mjs"]
