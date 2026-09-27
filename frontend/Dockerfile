FROM node:22-alpine AS build
WORKDIR /app

# VITE_API_URL must be available at build time so Vite bakes it into the bundle.
# Pass it as a Docker build argument:
#   docker build --build-arg VITE_API_URL=https://your-backend.onrender.com .
# Render passes envVars declared in render.yaml as build-time args automatically
# for Docker services.
ARG VITE_API_URL=http://localhost:8001
ENV VITE_API_URL=${VITE_API_URL}

COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
