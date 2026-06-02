# ShopWave demo store. OTel export stays off unless DT_INGEST_* env vars are set,
# so the hosted store runs without credentials.
FROM node:20-slim
WORKDIR /app
COPY package*.json ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8080
EXPOSE 8080
CMD ["node", "server.js"]
