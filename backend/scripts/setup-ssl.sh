#!/bin/bash
# SSL setup for Krypton
# Usage: ./scripts/setup-ssl.sh <domain> <email>
# Run from /opt/krypton/backend

set -euo pipefail

DOMAIN=$1
EMAIL=$2

if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
  echo "Usage: ./scripts/setup-ssl.sh <domain> <email>"
  exit 1
fi

echo "--- Setting up SSL for $DOMAIN ---"

# Stop everything
echo "Stopping services..."
docker compose -f docker-compose.prod.yml down 2>/dev/null || true

# Restore original nginx config
git checkout nginx/nginx.conf 2>/dev/null || true

# Create temporary HTTP-only nginx config for ACME challenge
echo "Creating temporary nginx config..."
cp nginx/nginx.conf nginx/nginx.conf.bak

cat > nginx/nginx.conf << 'NGINX'
worker_processes auto;
events { worker_connections 1024; }
http {
    server {
        listen 80;
        server_name _;
        location /.well-known/acme-challenge/ {
            root /var/www/certbot;
        }
        location / {
            return 200 'ok';
        }
    }
}
NGINX

# Start just nginx
echo "Starting nginx for ACME challenge..."
docker compose -f docker-compose.prod.yml up -d nginx
sleep 3

# Request certificate
echo "Requesting SSL certificate..."
docker compose -f docker-compose.prod.yml run --rm certbot certonly \
  --webroot \
  --webroot-path=/var/www/certbot \
  --email "$EMAIL" \
  --agree-tos \
  --no-eff-email \
  --force-renewal \
  -d "$DOMAIN"

# Restore real nginx config with domain
echo "Configuring nginx with SSL..."
cp nginx/nginx.conf.bak nginx/nginx.conf
rm nginx/nginx.conf.bak
sed -i "s/\${DOMAIN}/$DOMAIN/g" nginx/nginx.conf

# Restart everything
echo "Restarting all services..."
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d

echo ""
echo "--- SSL setup complete! ---"
echo "Your API is now available at https://$DOMAIN"
