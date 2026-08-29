# plcolab-rpa

Bot de automatización que consolida en **una sola pasada** el cargue diario de
facturas RG desde **facture.co (PLColab)** al **RNDC (proceso 86)** — sin digitar
factura por factura.

> **¿Es un RPA?** En rigor no: es ~95 % **integración por API (HTTP)** contra
> `api.facture.co` + un toque mínimo de navegador (**Playwright**) **solo para el
> login** (facture cifra la autenticación, no se puede replicar en HTTP puro).
> El resto es todo HTTP. Llámalo "bot de integración programado".

## Qué hace (1×/día, automático)

1. **Login** en facture con Playwright → obtiene el `JWT` (dura 24 h).
2. **Lista** las facturas emitidas de **ayer** (`GetDocumentsDescargaMasiva`).
   - Si no hay ninguna → **no hace nada** y termina.
3. Por cada factura pide su **UBL en JSON** (`Content3`) y arma filas con las
   **mismas columnas de `datos_rg`** (las de "Extraer Datos RG" de fe-tool).
4. Reutiliza la lógica **masiva** de fe-tool: `lib_excel.parsear` (agrupa por
   factura, expande remesas, split de perfil TSP/Elogia) →
   `consultar_radicado_remesa` (radicado por consecutivo) → `generar_xml`.
5. **Sube** todos los XML al RNDC (`enviar_factura_rndc`, proceso 86),
   **agrupando por perfil** (credenciales TSP para facturas TSP, Elogia para Elogia).
6. Guarda en `estado.json` qué facturas ya subió (**idempotencia**: si corre dos
   veces el mismo día no duplica) y deja un resumen.

## Arquitectura / separación de proyectos

- **fe-tool** (la webapp Streamlit, en `Desktop\testap`) **no se toca**: sigue
  siendo la herramienta manual. Este bot solo **importa** unas pocas funciones
  puras suyas (una sola fuente de verdad).
- El **cron** es de este repo: `.github/workflows/diario.yml` corre en la nube de
  **GitHub Actions** (gratis), no en el servidor de fe-tool ni en un PC.

### Cómo importa a fe-tool

El bot agrega `FE_TOOL_PATH` al `sys.path` e importa `core`, `services`, `webapp`,
`config` de fe-tool. Dos modos:

- **Local (ahora):** apunta `FE_TOOL_PATH` a `..\testap` (tu copia local).
- **Nube (cuando toque):** volver fe-tool un repo git y añadirlo aquí como
  **git submodule** en `./fe-tool`, luego `FE_TOOL_PATH=./fe-tool`. Ver
  `docs/DESPLIEGUE.md`.

## Uso local

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
copy .env.example .env   # y edita credenciales
python pipeline.py --fecha ayer          # corrida normal
python pipeline.py --fecha 2026-08-25    # una fecha puntual
python pipeline.py --fecha ayer --dry-run  # NO sube al RNDC (solo genera y reporta)
```

## Credenciales (nunca se commitean)

Van en `.env` (local) o en **GitHub Secrets** (nube):

- `FACTURE_USER`, `FACTURE_PASS` — login de facture.co.
- Las de RNDC (proceso 86) las toma de `config/perfiles.py` de fe-tool (`PERFILES`
  con `ut_tsp` / `ut_elogia`). En la nube se regeneran desde Secrets igual que
  `bootstrap_perfiles.py`.

## Estado

- ✅ API de facture verificada (listar + `Content3`), consecutivo desde propiedad `"02"`.
- ✅ Reutilización de fe-tool confirmada (usa los mismos módulos que `webapp/app.py`:
  `webapp/lib_excel`, `webapp/lib_rndc86`, `webapp/lib_extraer`, `core/xml_generator`,
  `services/rndc_service` — nada de `ui/`).
- ✅ **Login Playwright**: selectores REALES fijados y verificados
  (`usernameField` / `passwordField` / `button[type=submit]`).
- ✅ Prueba de humo OK (importa todo; perfiles `ut_tsp` / `ut_elogia` detectados).
- ⏳ **Falta probar una corrida real completa** (login + listar + subir) contra el RNDC.
- ⚠️ **Submodule fe-tool**: pendiente cuando se despliegue en la nube (hoy fe-tool
  aún no es repo git). Ver `docs/DESPLIEGUE.md`.
