# Nightly DECSI backup runner (Postgres client + midnight loop).
# Uses the same postgres:16 image already pulled for the db service.
FROM postgres:16

RUN apt-get update \
    && apt-get install -y --no-install-recommends tar gzip tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY run_backup.sh /scripts/run_backup.sh
COPY entrypoint.sh /scripts/entrypoint.sh
RUN chmod +x /scripts/run_backup.sh /scripts/entrypoint.sh

ENV TZ=Africa/Addis_Ababa \
    BACKUP_DIR=/backups \
    BACKUP_RETENTION_DAYS=14 \
    MEDIA_PATH=/app/media \
    DB_HOST=db \
    DB_PORT=5432

VOLUME ["/backups"]

CMD ["/scripts/entrypoint.sh"]
