# Build stage
FROM node:20-alpine as builder

WORKDIR /app

# Copy all source code first (needed for quasar prepare in postinstall)
COPY . .

# Install dependencies
RUN npm ci

# Build the application with environment-specific variables
# These MUST be provided via --build-arg at build time
ARG VITE_API_BASE_URL
ARG VITE_MICROSOFT_REDIRECT_URI
ARG VITE_COGNITO_REDIRECT_URI
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_MICROSOFT_REDIRECT_URI=${VITE_MICROSOFT_REDIRECT_URI}
ENV VITE_COGNITO_REDIRECT_URI=${VITE_COGNITO_REDIRECT_URI}
RUN npm run build

# Runtime stage
FROM nginx:alpine

WORKDIR /app

# Copy built application from builder
COPY --from=builder /app/dist/spa /usr/share/nginx/html

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Run as non-root nginx user
RUN chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx /var/log/nginx /etc/nginx/conf.d && \
    touch /var/run/nginx.pid && chown nginx:nginx /var/run/nginx.pid
USER nginx

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost:3000/ || exit 1
