# plcolab-rpa

Este es el bot con el que automaticé el cargue diario de facturas electrónicas de
transporte al **RNDC**. Antes lo hacía a mano todos los días con la herramienta
FE-Tool: entrar a facture.co, descargar las facturas emitidas, extraer sus datos,
generar los XML y subirlos uno por uno. Todo ese proceso ahora corre solo, una vez
al día, y me llega un correo con el resultado.

No es una aplicación con pantalla ni un servidor prendido todo el tiempo. Es un
proceso desatendido: se despierta a una hora fija, hace el trabajo, notifica y se
apaga.

## Qué hace, en orden

1. Inicia sesión en facture.co y obtiene un token de acceso.
2. Lista todas las facturas **emitidas** en la fecha objetivo (por defecto, ayer).
3. Por cada factura descarga su contenido UBL en formato JSON.
4. Arma la información de cada remesa y la agrupa por factura.
5. Consulta en el RNDC el radicado de cada remesa.
6. Genera el XML de cada factura y lo sube al RNDC (proceso 86), usando las
   credenciales del perfil al que pertenece cada una.
7. Deja un reporte en Excel, un ZIP con los XML y un archivo de auditoría, y me
   los manda por correo.

Si un día no hay facturas emitidas, no hace nada y me avisa por correo igual.

## Dónde se conecta

El bot habla con tres cosas:

- **facture.co (PLColab)** — de donde salen las facturas. Tiene una API REST
  (`api.facture.co`) que uso para listar las facturas y traer su contenido. El
  login sí va por navegador (ver más abajo).
- **fe-tool** — mi propia herramienta. No reescribí su lógica: la reutilizo tal
  cual para armar y generar los XML. Entra como submódulo de git.
- **RNDC (mintransporte)** — el destino. Consulto radicados de remesa y subo las
  facturas por su WebService SOAP (proceso 86).

## Cómo mapea los datos

Este es el corazón del asunto. En vez de descargar y parsear PDFs (que es lo que
hacía a mano), tomo el contenido estructurado de cada factura desde la API de
facture (endpoint `Content3`) y de ahí armo, en memoria, exactamente la misma tabla
que produce el módulo "Extraer Datos RG" de fe-tool. Con esa tabla alimento el
mismo flujo de "Generar facturas vía Excel", sin archivos de por medio.

El mapeo de campos, por remesa:

| Dato en el XML | De dónde lo saco (Content3) |
|---|---|
| Consecutivo de remesa | propiedad `"02"` de la línea (no `CodigoItem`, que a veces trae el radicado) |
| CUFE | `UUID` |
| NIT del cliente | `AccountingCustomerParty.PartyIdentification_ID` (le calculo el dígito de verificación) |
| Nombre del cliente | `AccountingCustomerParty.Party_Name` |
| Descripción | `Item.Description` |
| Valor | `PriceAmount` |
| Número de factura y fecha | del listado (`number`, `issueDate`) |
| Radicado de remesa | lo consulto aparte al RNDC por el consecutivo |

El perfil (TSP o Elogia) lo deduzco del formato del consecutivo: los que empiezan
por `300`/`120` son TSP y los que empiezan por `101`/`0101` son Elogia. Cada
factura se genera y se sube con las credenciales de su propio perfil, así que si en
la misma corrida hay facturas de los dos perfiles, cada una va con las suyas.

## Reutilización de fe-tool

No dupliqué código. El bot importa directamente las funciones de fe-tool que ya
tenía probadas:

- `webapp.lib_excel.parsear` — agrupa las remesas por factura y aplica el split de
  perfil.
- `services.rndc_service.consultar_radicado_remesa` — trae el radicado de cada
  remesa.
- `core.xml_generator.generar_xml` — arma el XML UBL.
- `webapp.lib_rndc86.enviar_factura_rndc` — lo sube al RNDC.

fe-tool entra como **submódulo de git**, apuntando a un commit fijo. Eso significa
que si más adelante cambio cualquier módulo de fe-tool, el bot no se ve afectado:
sigue usando la versión congelada. Solo hereda cambios cuando actualizo el puntero
del submódulo a propósito.

En la ejecución, fe-tool necesita su archivo de credenciales (`config/perfiles.py`),
que no está en ningún repositorio. En la nube lo reconstruyo desde un secret antes
de correr; en local uso mi copia de fe-tool.

## Cómo se ejecuta

El proceso vive como un workflow en **GitHub Actions**, pero **no lo dispara el cron
propio de GitHub** (su `schedule` es impreciso: se retrasa horas o no dispara). En
su lugar uso un programador externo puntual, **cron-job.org**: todos los días a las
8:15 (hora Colombia) le pega a la API de GitHub para lanzar el workflow, y GitHub lo
corre casi al instante. Con eso consigo una hora fija y confiable, sin montar ni
mantener un servidor. El disparo es un simple POST a:

```
POST https://api.github.com/repos/CALR0/plcolab-rpa/actions/workflows/diario.yml/dispatches
body: {"ref":"main"}
```

que equivale a apretar "Run workflow". El workflow arranca la máquina temporal, corre
el pipeline y se apaga. Con `fecha` en `ayer`, procesa el día anterior (hoy 30
procesa el 29).

El login usa **Playwright** en modo headless (facture cifra la autenticación, así que
no se puede replicar solo con HTTP); una vez tengo el token, todo lo demás —listar,
traer contenido, consultar radicados, subir— es HTTP puro, sin navegador.

No hay frontend. El seguimiento lo hago por dos vías: el correo con el reporte, y la
página de Actions en GitHub (historial de corridas, logs y los archivos generados
como artefacto).

## El reporte y el correo

Al terminar genero, en `salidas/`:

- `Facturas PLCOLAB <fecha>.xlsx` — el reporte, con una fila por factura: cliente,
  número, cantidad de remesas, remesas asociadas, si subió o no al RNDC, y la
  novedad (el radicado si subió, o el motivo del rechazo). Al final lleva los
  totales.
- `Facturas PLCOLAB <fecha>.zip` — todos los XML generados.
- `datos_rg PLCOLAB <fecha>.xlsx` — la tabla que alimentó la generación, para
  auditoría.

El correo va con un cuerpo HTML: si hubo facturas, muestra cuántas se encontraron y
el detalle de envío, con el Excel y el ZIP adjuntos; si no hubo, avisa que no se
encontró información para ese día. `MAIL_TO` admite varios destinatarios separados
por coma.

## Estructura del proyecto

```
plcolab-rpa/
  pipeline.py          Orquestador: encadena todo el proceso.
  facture_client.py    Login (Playwright) y llamadas a la API de facture.
  fetool_bridge.py     Puente hacia fe-tool: Content3 -> datos_rg -> parsear -> XML.
  reporte.py           Genera el Excel, el ZIP y el datos_rg de auditoría.
  enviar.py            Arma y envía el correo (HTML + adjuntos).
  settings.py          Configuración desde variables de entorno / .env.
  requirements.txt
  .github/workflows/
    diario.yml         Los pasos de la corrida en la nube. Se dispara por API
                       (cron-job.org), no por el schedule de GitHub.
  docs/
    DESPLIEGUE.md       Cómo montarlo (submódulo, secrets, etc.).
  fe-tool/             Submódulo: mi herramienta FE-Tool (código reutilizado).
```

## Configuración

Todo lo sensible va por variables de entorno. En local, en un archivo `.env`
(ver `.env.example`); en la nube, como secrets de GitHub Actions.

| Variable | Para qué |
|---|---|
| `FACTURE_USER`, `FACTURE_PASS` | Login de facture.co |
| `FE_TOOL_PERFILES` | Contenido de `config/perfiles.py` de fe-tool (credenciales RNDC de cada perfil). Solo en la nube |
| `FE_TOOL_PATH` | Ruta a fe-tool (local: mi copia; nube: `./fe-tool`) |
| `SMTP_USER`, `SMTP_PASS`, `MAIL_TO` | Envío del reporte por correo |
| `MAX_FACTURAS` | Tope opcional de facturas por corrida (0 = sin tope) |

Nada de esto se sube al repositorio.

## Ejecución local

```
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
copy .env.example .env      (y completo mis datos)

python pipeline.py --fecha ayer
python pipeline.py --fecha 2026-08-25
python pipeline.py --fecha ayer --dry-run     (genera pero no sube)
```

## Notas técnicas que fui aprendiendo

- El listado de facturas viene paginado. Si un día se emiten más de 100, hay que
  recorrer todas las páginas; el bot ya lo hace y deduplica.
- El RNDC responde de forma inconsistente: a veces manda el error completo con el
  detalle por remesa, y a veces solo el código. Cuando manda el detalle, lo mapeo a
  cada remesa; cuando no, dejo el motivo a nivel factura.
- El consecutivo hay que leerlo de la propiedad `"02"`, no de `CodigoItem`: este
  último a veces trae el radicado en vez del consecutivo.
- El error `FAC038` es factura duplicada (ya reportada); `FAC080` es una remesa sin
  cumplir. El primero es de la factura entera, el segundo de una remesa puntual.
