#!/bin/sh
set -e

apk add --no-cache openssl >/dev/null 2>&1

# Certbot issues one SAN cert stored under AUTHORITY_DOMAIN.
# Generate a self-signed placeholder there so nginx can start before
# the real cert has been issued.
cert_dir="/etc/letsencrypt/live/$AUTHORITY_DOMAIN"
if [ ! -f "$cert_dir/fullchain.pem" ]; then
    mkdir -p "$cert_dir"
    openssl req -x509 -nodes -days 1 -newkey rsa:2048 \
        -keyout "$cert_dir/privkey.pem" \
        -out "$cert_dir/fullchain.pem" \
        -subj "/CN=$AUTHORITY_DOMAIN" 2>/dev/null
    echo "Placeholder cert created for $AUTHORITY_DOMAIN"
fi

# Process nginx config template (only substitute the four domain vars)
envsubst '$AUTHORITY_DOMAIN $DASHBOARD_DOMAIN $PACKAGES_DOMAIN $NPM_DOMAIN' \
    < /etc/nginx/nginx.conf.template \
    > /etc/nginx/conf.d/default.conf

exec nginx -g 'daemon off;'
