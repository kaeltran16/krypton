#!/bin/sh
set -e

echo "Waiting for PostgreSQL..."
while ! pg_isready -h postgres -p 5432 -U krypton -q 2>/dev/null; do
  sleep 1
done
echo "PostgreSQL is ready."

echo "Waiting for Redis..."
while ! redis-cli -h redis ping 2>/dev/null | grep -q PONG; do
  sleep 1
done
echo "Redis is ready."

echo "Running migrations..."
alembic upgrade head
echo "Migrations complete."

exec "$@"
