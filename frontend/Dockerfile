# Stage 1: Build React app
FROM node:20-alpine AS builder

WORKDIR /app

# Variables de build (Vite las hornea en `npm run build`). EasyPanel pasa las
# Environment del servicio como build-args; Docker solo expone las declaradas con ARG.
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL
# Panel 'Ticket Allianz Seguimiento' (API externa, fuera de Tomi prod).
ARG VITE_TICKETS_ALLIANZ_API
ENV VITE_TICKETS_ALLIANZ_API=$VITE_TICKETS_ALLIANZ_API
ARG VITE_TICKETS_ALLIANZ_TOKEN
ENV VITE_TICKETS_ALLIANZ_TOKEN=$VITE_TICKETS_ALLIANZ_TOKEN

COPY package*.json ./
RUN npm ci --legacy-peer-deps

COPY . .
RUN npm run build

# Stage 2: Serve with nginx
FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html

RUN printf 'server {\n    listen 80;\n    root /usr/share/nginx/html;\n    index index.html;\n    location / {\n        try_files $uri $uri/ /index.html;\n    }\n    location ~* \\.(js|css|png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|eot)$ {\n        expires 1y;\n        add_header Cache-Control "public, immutable";\n    }\n}\n' > /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
