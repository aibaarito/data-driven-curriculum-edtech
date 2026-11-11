FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:24-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build /app ./
USER node
EXPOSE 3010
# 0.0.0.0 inside the container; docker-compose publishes it on 127.0.0.1 only. API_URL/API_TOKEN are runtime env.
CMD ["npx", "next", "start", "-p", "3010", "-H", "0.0.0.0"]
