FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG API_URL=http://backend:8010
ENV API_URL=$API_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:24-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build /app ./
USER node
EXPOSE 3010
CMD ["npx", "next", "start", "-p", "3010", "-H", "0.0.0.0"]
