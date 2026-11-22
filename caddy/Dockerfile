FROM caddy:builder AS builder

# build caddy with the specified plugins, caching go dependencies and build artifacts
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    xcaddy build \
    --with github.com/caddy-dns/cloudflare \
    --with github.com/greenpau/caddy-security

FROM caddy:alpine

COPY --from=builder /usr/bin/caddy /usr/bin/caddy

# validate install
RUN /usr/bin/caddy version \
    && /usr/bin/caddy list-modules | grep -qx 'dns.providers.cloudflare' \
    && /usr/bin/caddy list-modules | grep -qx 'security'
