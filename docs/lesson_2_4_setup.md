# MethaneScope AI — Lesson 2.4 Quick Start (Windows Git Bash)

Prerequisite: complete Lesson 2.3 and retain `outputs/emit_batch/emit_accepted_for_ingestion.csv` plus the original files referenced in that CSV.

1. Install and start Docker Desktop (Linux containers).
2. Extract this ZIP into your MethaneScope project root. The supplied `config/postgis.env.example` is a starter file, not a real secret.
3. In Git Bash, from MethaneScope root:

```bash
cp config/postgis.env.example .env
# Edit .env and choose a unique local development password before launching
printf '\n.env\n' >> .gitignore  # ONLY if .gitignore exists or create it intentionally

docker compose -f docker-compose.postgis.yml up -d
docker compose -f docker-compose.postgis.yml ps
```

4. In JupyterLab open `06_postgis_satellite_database.ipynb` and run all cells in order. The first installs psycopg and python-dotenv.
5. If no accepted granules are available, rerun Lesson 2.3. Use `MODE="demo"` there to verify the database workflow before attempting real NASA data.
6. See notebook output for PostGIS version, inserted rows and idempotency check.

**Never commit `.env` or NASA credentials.** The sample Compose database role is privileged and **not designed for deployment**. Only port 5433 on 127.0.0.1 is published. Do not expose the database to the Internet. For production use separate roles, TLS, secret storage, backups and managed migrations.

To stop without deleting the volume: `docker compose -f docker-compose.postgis.yml down`.
Do not run `docker compose ... down -v` unless you intentionally want to delete the database volume.
