# Dockerfile-postgres
FROM postgres:15

# Copy initialization and backup scripts
COPY postgres/start-scripts/ /opt/entry/start-scripts/
COPY postgres/admin-scripts/ /opt/entry/admin-scripts/
COPY postgres/init-scripts/ /docker-entrypoint-initdb.d/


# Copy the universal entrypoint script
COPY scripts/universal-entrypoint.sh /opt/entry/start-scripts/universal-entrypoint.sh

# Copy backup script to /usr/local/bin for easy access
COPY postgres/admin-scripts/backup.sh /usr/local/bin/backup.sh

# Make scripts executable
RUN chmod +x /docker-entrypoint-initdb.d/*.sh && \
    chmod +x /usr/local/bin/*.sh && \
    chmod +x /opt/entry/admin-scripts/*.sh && \
    chmod +x /opt/entry/start-scripts/*.sh

RUN chown -R 999:999 /opt/entry && chmod -R 755 /opt/entry
# keep using your universal-entrypoint via CMD/ENTRYPOINT in compose
