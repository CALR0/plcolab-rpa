# Despliegue en la nube (GitHub Actions, gratis)

El bot corre **1×/día** en GitHub Actions. fe-tool se enlaza como **git submodule**
para que el runner tenga su código, sin duplicarlo.

## 1. Convertir fe-tool en repo git (si aún no lo es)

Hoy `Desktop\testap` (fe-tool) **no es repo git**. Para usarlo como submodule hay
que versionarlo y subirlo (privado):

```bash
cd C:\Users\Lizarazo\Desktop\testap
git init
git add .
git commit -m "fe-tool"
# crear repo privado en GitHub (p.ej. fe-tool) y:
git remote add origin https://github.com/<tu-usuario>/fe-tool.git
git push -u origin main
```

> `config/perfiles.py` está en el `.gitignore` de fe-tool → NO se sube (bien).
> Las credenciales van por Secrets (paso 4).

## 2. Crear el repo del bot y añadir fe-tool como submodule

```bash
cd C:\Users\Lizarazo\Desktop\plcolab-rpa
git init && git add . && git commit -m "plcolab-rpa"
git submodule add https://github.com/<tu-usuario>/fe-tool.git fe-tool
git commit -m "fe-tool como submodule"
# crear repo privado plcolab-rpa en GitHub y push
git remote add origin https://github.com/<tu-usuario>/plcolab-rpa.git
git push -u origin main
```

Con esto `FE_TOOL_PATH=./fe-tool` (ya configurado en el workflow) apunta al submodule.

## 3. Secrets del repo del bot

En GitHub → repo `plcolab-rpa` → **Settings → Secrets and variables → Actions**:

| Secret | Contenido |
|---|---|
| `FACTURE_USER` | usuario del login de facture |
| `FACTURE_PASS` | clave del login de facture |
| `FE_TOOL_PERFILES` | el **contenido completo** de `config/perfiles.py` (el `PERFILES = {...}` con las credenciales RNDC de TSP y Elogia) |

El workflow escribe `FE_TOOL_PERFILES` en `fe-tool/config/perfiles.py` antes de correr.

## 4. Programación

`.github/workflows/diario.yml` ya trae:
- `cron: "0 13 * * *"` → 08:00 Colombia (13:00 UTC). Cámbialo si quieres otra hora.
- `workflow_dispatch` → botón para lanzarlo a mano (con `fecha` y `dry_run`).

## 5. Idempotencia (`estado.json`)

Hoy se guarda como **artefacto** de la corrida (no persiste entre días de forma
automática). Para que "no re-suba" entre corridas, opciones:
- **Commit del `estado.json`** a una rama del repo al final del job, o
- un almacenamiento externo (Gist, S3, etc.).

Mientras tanto, como el bot filtra por **fecha = ayer**, el riesgo de duplicar es
bajo (solo si se relanza el mismo día). Endurecer esto es un pendiente.

## Nota sobre la IP

El RNDC responde bien desde IP de EE.UU. Los runners de GitHub Actions
(`ubuntu-latest`) están en EE.UU. → OK. Si algún día bloquean por IP, mover a
un runner propio o VM.
