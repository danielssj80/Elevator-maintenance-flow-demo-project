# Step 10 Report — Production Verification

- Date: 2026-06-12
- Change: deploy-aws-https
- URL: https://elevator.dsaavedra.dev

## Results

| Check | Command | Result |
|---|---|---|
| 10.1 HTTP→HTTPS redirect | `curl -s -o /dev/null -w "%{http_code} %{redirect_url}" http://elevator.dsaavedra.dev/` | 301 → https://elevator.dsaavedra.dev/ ✓ |
| 10.2 Health over HTTPS | `curl -s https://elevator.dsaavedra.dev/health` | `{"status":"ok"}` ✓ |
| 10.3 TLS certificate | `curl -sv https://elevator.dsaavedra.dev/health` | Issuer: Let's Encrypt CN=YE2, wildcard `*.dsaavedra.dev`, expires 2026-09-10 ✓ |
| 10.4 API returns 100 elevators | `curl -s https://elevator.dsaavedra.dev/api/elevators` | 100 ✓ |
| 10.5 POST report persists | `POST /api/elevators/ELV-001/report` | 200, row id=1 verified in DB, deleted ✓ |
| 10.6 Certbot renewal dry-run | `certbot renew --dry-run` (on EC2) | All simulated renewals succeeded ✓ |

## Bugs found and fixed during deployment

- **`alembic/env.py`**: leía `DATABASE_URL` directamente del entorno. En producción solo existen `POSTGRES_*`, así que alembic conectaba a `localhost`. Fix: usar `settings.database_url` que sabe construir la URL desde los componentes.
- **`docker-compose.prod.yml` healthcheck**: `${POSTGRES_USER}` era interpolado por docker-compose desde el entorno del host (vacío). Fix: escapar como `$$POSTGRES_USER` para que lo expanda el shell dentro del contenedor.
- **buildx no instalado**: Amazon Linux 2023 no incluye el plugin buildx. Fix: descargar desde GitHub releases con versión obtenida via API.
- **cronie no instalado**: Amazon Linux 2023 no incluye cron por defecto. Fix: `dnf install -y cronie && systemctl enable --now crond`.

## Outcome

PASS — stack de producción operativo en https://elevator.dsaavedra.dev
