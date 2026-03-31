#!/bin/bash
# First-time SSL certificate setup
# Usage: ./init-letsencrypt.sh <domain> <email>
# Run from the backend/ directory.

set -e

DOMAIN=$1
EMAIL=$2

if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
  echo "Usage: ./init-letsencrypt.sh <domain> <email>"
  exit 1
fi

echo "--- Requesting SSL certificate for $DOMAIN ---"

# Stop any running services
docker compose -f docker-compose.prod.yml down

# Create a temporary compose override that starts nginx in HTTP-only mode
cat > docker-compose.init-ssl.yml << 'EOF'
services:
  nginx:
    command: >
      sh -c "echo 'server { listen 80; location /.well-known/acme-challenge/ { root /var/www/certbot; } location / { return 200 ok; } }' > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"
EOF

# Start nginx in HTTP-only mode (override disables SSL config)
docker compose -f docker-compose.prod.yml -f docker-compose.init-ssl.yml up -d nginx

echo "Waiting for nginx to be ready..."
sleep 3

# Request certificate
docker compose -f docker-compose.prod.yml run --rm certbot certonly \
  --webroot \
  --webroot-path=/var/www/certbot \
  --email "$EMAIL" \
  --agree-tos \
  --no-eff-email \
  -d "$DOMAIN"

# Clean up
docker compose -f docker-compose.prod.yml down
rm docker-compose.init-ssl.yml

# Start all services normally (certs now exist)
docker compose -f docker-compose.prod.yml up -d

echo "--- SSL setup complete for $DOMAIN ---"
