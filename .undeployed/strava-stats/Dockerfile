FROM robiningelbrecht/strava-statistics:latest AS base

# Setup document root
WORKDIR /var/www

USER root

# Make sure files/folders needed by the processes are accessable when they run under the nobody user
RUN chown -R 1000:1000 /var/www /run /var/lib/nginx /var/log/nginx

# Switch to use a non-root user from here on
USER 1000

# Add application
COPY --chown=1000:1000 . /var/www/
#RUN touch /var/www/.env

# Expose the port nginx is reachable on
EXPOSE 8080

# Let supervisord start services
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]

# Configure a healthcheck to validate that everything is up&running
HEALTHCHECK --timeout=10s CMD curl --silent --fail http://127.0.0.1:8080/fpm-ping || exit 1
