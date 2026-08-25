# DECSI midnight backups

The `backup` Compose service sleeps until **00:00 Africa/Addis_Ababa**, then dumps the database and media into:

```text
./backups/decsi_backup_YYYYMMDD_HHMMSS.tar.gz
```

Contents of each archive:

- `database.dump` — Postgres custom format (`pg_restore`)
- `database.sql` — plain SQL (`psql`)
- `media.tar.gz` — uploaded documents / signatures / photos

## Enable

```bash
docker compose up -d --build backup
docker compose logs -f backup
```

## Manual run (without waiting for midnight)

```bash
docker compose run --rm backup /scripts/run_backup.sh
```

## Restore (outline)

```bash
mkdir -p /tmp/decsi_restore && tar -xzf backups/decsi_backup_….tar.gz -C /tmp/decsi_restore

# Restore DB (prefer empty target or --clean)
docker compose exec -T db pg_restore -U "$DB_USER" -d "$DB_NAME" --clean --if-exists \
  < /tmp/decsi_restore/database.dump

# Restore media into MEDIA_ROOT / media volume
tar -xzf /tmp/decsi_restore/media.tar.gz -C /path/to/media/parent
```

## Settings

| Env | Default | Meaning |
|-----|---------|---------|
| `BACKUP_RETENTION_DAYS` | `14` | Delete archives older than N days |
| `BACKUP_TZ` / `TZ` | `Africa/Addis_Ababa` | Midnight = DECSI local time |
| `BACKUP_DIR` | `/backups` → `./backups` | Archive directory on the host |
