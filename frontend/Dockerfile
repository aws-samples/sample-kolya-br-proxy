# Build stage
FROM --platform=linux/arm64 node:20-alpine as builder

WORKDIR /app

# Copy all source code first (needed for quasar prepare in postinstall)
COPY . .

# Install dependencies
RUN npm ci

# Build the application with production environment variables
ARG VITE_API_BASE_URL=https://api.kbp.kolya.fun
ARG VITE_MICROSOFT_REDIRECT_URI=https://kbp.kolya.fun/auth/microsoft/callback
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_MICROSOFT_REDIRECT_URI=${VITE_MICROSOFT_REDIRECT_URI}
RUN npm run build

# Runtime stage
FROM --platform=linux/arm64 nginx:alpine

WORKDIR /app

# Copy built application from builder
COPY --from=builder /app/dist/spa /usr/share/nginx/html

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost:3000/ || exit 1
