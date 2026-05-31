# Imagen ligera para servir la SPA en desarrollo / preview.
# Sustituye por nginx + build estático cuando vayas a producción.
FROM node:20-alpine

WORKDIR /app
COPY package.json ./
RUN npm install --no-audit --no-fund

COPY . .

EXPOSE 3000
CMD ["npm", "run", "dev"]
