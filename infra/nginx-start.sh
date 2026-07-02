#!/bin/sh
set -e

apk add --no-cache openssl >/dev/null 2>&1

# Generate a self-signed placeholder cert for each domain if the real one
# doesn't exist yet. This lets nginx start before certbot has run.
for domain in "$AUTHORITY_DOMAIN" "$DASHBOARD_DOMAIN" "$PACKAGES_DOMAIN" "$NPM_DOMAIN"; do
    cert_dir="/etc/letsencrypt/live/$domain"
    if [ ! -f "$cert_dir/fullchain.pem" ]; then
        mkdir -p "$cert_dir"
        openssl req -x509 -nodes -days 1 -newkey rsa:2048 \
            -keyout "$cert_dir/privkey.pem" \
            -out "$cert_dir/fullchain.pem" \
            -subj "/CN=$domain" 2>/dev/null
        echo "Placeholder cert created for $domain"
    fi
done

# Process nginx config template (only substitute the four domain vars)
envsubst '$AUTHORITY_DOMAIN $DASHBOARD_DOMAIN $PACKAGES_DOMAIN $NPM_DOMAIN' \
    < /etc/nginx/nginx.conf.template \
    > /etc/nginx/conf.d/default.conf

exec nginx -g 'daemon off;'
