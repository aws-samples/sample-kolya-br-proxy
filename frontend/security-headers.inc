# Included by nginx.conf. style-src needs 'unsafe-inline' for Quasar's
# inline style attributes; scripts are same-origin modules only.
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; font-src 'self' data:; connect-src 'self' __API_ORIGIN__; object-src 'none'; base-uri 'self'; frame-ancestors 'none'" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
# HTTPS only. The ALB terminates TLS and redirects port 80 itself, so every
# response nginx serves reaches the browser over HTTPS, where HSTS applies.
add_header Strict-Transport-Security "max-age=31536000" always;
