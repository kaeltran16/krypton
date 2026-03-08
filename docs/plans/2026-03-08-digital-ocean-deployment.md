# Digital Ocean Deployment Design

## Overview

Deploy Krypton to a single Digital Ocean Droplet with Cloudflare Pages for the frontend. GitHub Actions auto-deploys the backend on push to main.

## Architecture

```
User (Vietnam)
  ├── PWA static files ← Cloudflare Pages CDN (global edge)
  └── API/WebSocket requests ← Nginx (SSL termination) ← Docker API container
                                   ↑ SGP1 Droplet ($12/mo)
```

## Infrastructure

- **Droplet**: $12/mo, 1 vCPU, 2GB RAM, Ubuntu 24.04, Singapore (SGP1)
- **Frontend**: Cloudflare Pages (free, global CDN)
- **SSL**: Let's Encrypt via Certbot + Nginx
- **CI/CD**: GitHub Actions (SSH deploy on push to main, backend/ path only)

## Droplet Services (docker-compose.prod.yml)

| Service  | Image              | Notes                                    |
|----------|--------------------|------------------------------------------|
| api      | Custom Dockerfile  | No --reload, no volume mount             |
| postgres | postgres:16-alpine | Persistent volume, healthcheck           |
| redis    | redis:7-alpine     | Healthcheck                              |
| nginx    | nginx:alpine       | SSL termination, reverse proxy, WS proxy |

## File Structure

```
backend/
├── docker-compose.yml           # local dev (unchanged)
├── docker-compose.prod.yml      # production
├── nginx/
│   ├── nginx.conf               # reverse proxy + SSL + WebSocket
│   └── init-letsencrypt.sh      # first-time cert setup
.github/
└── workflows/
    └── deploy.yml               # GitHub Actions SSH deploy
```

## Nginx Responsibilities

- SSL termination (Let's Encrypt certs)
- Reverse proxy all requests to API container on port 8000
- WebSocket upgrade headers for /ws/* paths
- Gzip compression
- Security headers (HSTS, X-Frame-Options, etc.)

## Firewall (UFW)

- Allow: 22 (SSH), 80 (HTTP redirect), 443 (HTTPS)
- Block: 8000, 5432, 6379

## GitHub Actions Workflow

- Trigger: push to main, paths: backend/**
- Steps: SSH → git pull → docker compose -f docker-compose.prod.yml up -d --build → prune old images
- Secrets: DROPLET_IP, SSH_PRIVATE_KEY
- Uses deploy user (not root)

## Cloudflare Pages

- Connect GitHub repo
- Build: `cd web && pnpm install && pnpm build`
- Output: `web/dist`
- Env vars: VITE_API_URL, VITE_WS_URL, VITE_API_KEY, VITE_VAPID_PUBLIC_KEY

## Initial Server Setup (one-time manual)

1. Create Droplet (Ubuntu 24.04, SGP1, $12/mo, SSH key)
2. Create `deploy` user with sudo + Docker access
3. Disable root SSH, set up UFW
4. Install Docker Engine + Compose plugin, Git
5. Clone repo to /opt/krypton
6. Create .env with secrets
7. Run certbot for SSL certs
8. Start services with docker-compose.prod.yml
9. Set up GitHub Actions secrets (SSH key + Droplet IP)

## Frontend Environment Variables

| Variable             | Value                                  |
|----------------------|----------------------------------------|
| VITE_API_URL         | https://<droplet-subdomain>            |
| VITE_WS_URL          | wss://<droplet-subdomain>              |
| VITE_API_KEY         | (same as backend KRYPTON_API_KEY)      |
| VITE_VAPID_PUBLIC_KEY| (VAPID public key)                     |
