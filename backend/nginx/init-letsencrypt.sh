#!/bin/bash
# First-time SSL certificate setup
# Usage: ./init-letsencrypt.sh <domain> <email>

set -e

DOMAIN=$1
EMAIL=$2

if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
  echo "Usage: ./init-letsencrypt.sh <domain> <email>"
  exit 1
fi

echo "--- Requesting SSL certificate for $DOMAIN ---"

# Start nginx temporarily for ACME challenge
# First, create a temporary nginx config without SSL
cat > /tmp/nginx-temp.conf << 'NGINX'
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

# Copy temp config
cp nginx/nginx.conf nginx/nginx.conf.bak
cp /tmp/nginx-temp.conf nginx/nginx.conf

# Start just nginx
docker compose -f docker-compose.prod.yml up -d nginx

# Request certificate
docker compose -f docker-compose.prod.yml run --rm certbot certonly \
  --webroot \
  --webroot-path=/var/www/certbot \
  --email "$EMAIL" \
  --agree-tos \
  --no-eff-email \
  -d "$DOMAIN"

# Restore real nginx config
cp nginx/nginx.conf.bak nginx/nginx.conf
rm nginx/nginx.conf.bak

# Update nginx.conf with actual domain
sed -i "s/\${DOMAIN}/$DOMAIN/g" nginx/nginx.conf

# Restart everything
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d

echo "--- SSL setup complete for $DOMAIN ---"
