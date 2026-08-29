"""
Cliente de facture.co (PLColab).

- login(): usa Playwright SOLO para autenticarse (facture cifra el login vía
  gateway, no se puede replicar en HTTP puro) y devuelve el JWT (dura 24 h).
- El resto es HTTP puro con `Authorization: Bearer <JWT>`:
    - listar_facturas(): GetDocumentsDescargaMasiva (verificado en vivo).
    - get_content3(): UBL de una factura en JSON (consecutivo, CUFE, cliente, líneas).

Endpoints verificados 2026-08-29 sobre la cuenta UT.
"""
import requests

import settings as config


# ─────────────────────────────────────────────────────────────────────────────
# LOGIN (Playwright) → JWT
# ─────────────────────────────────────────────────────────────────────────────
def login(usuario=None, password=None, headless=None, debug=False):
    """Inicia sesión en facture con Playwright y devuelve el JWT de localStorage.

    Los selectores del formulario están como *best-effort*; si cambian, corre con
    debug=True para inspeccionar. facture no tiene CAPTCHA, así que es estable.
    """
    from playwright.sync_api import sync_playwright

    usuario = usuario or config.FACTURE_USER
    password = password or config.FACTURE_PASS
    if not usuario or not password:
        raise RuntimeError("Faltan FACTURE_USER / FACTURE_PASS (revisa .env o Secrets).")
    headless = config.PLAYWRIGHT_HEADLESS if headless is None else headless

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(config.FACTURE_LOGIN_URL, wait_until="networkidle")

        # Selectores REALES del login de facture (verificados 2026-08-29):
        #   usuario  -> input[formcontrolname='usernameField']  (placeholder "Usuario")
        #   clave    -> input[formcontrolname='passwordField']  (placeholder "Contraseña")
        #   enviar   -> button[type='submit']                   (texto "Iniciar sesión")
        #   checkbox "Recordar" ya viene marcado y NO es obligatorio -> no se toca.

        # --- Usuario --- (fallbacks por si Angular renombra el formcontrolname)
        _fill_first(page, [
            "input[formcontrolname='usernameField']",
            "input[placeholder='Usuario']",
            "input[type='text']:visible",
        ], usuario)

        # --- Contraseña ---
        _fill_first(page, [
            "input[formcontrolname='passwordField']",
            "input[placeholder='Contraseña']",
            "input[type='password']:visible",
        ], password)

        if debug:
            print("[debug] Rellené usuario/clave. Botones visibles:")
            for b in page.query_selector_all("button"):
                print("   -", (b.inner_text() or "").strip()[:40])

        # --- Enviar ---
        _click_first(page, [
            "button[type='submit']",
            "button:has-text('Iniciar sesión')",
            "button:has-text('Iniciar')",
        ])

        # Esperar a que el login redirija a /home (dashboard).
        try:
            page.wait_for_url("**/home/**", timeout=30000)
        except Exception:
            page.wait_for_timeout(4000)  # fallback: dar tiempo al redirect

        jwt = page.evaluate("() => localStorage.getItem('JWT')")
        browser.close()

    if not jwt:
        raise RuntimeError(
            "Login sin JWT: revisa credenciales o los selectores del formulario "
            "(corre con --debug-login)."
        )
    return jwt


def _fill_first(page, selectores, valor):
    for sel in selectores:
        try:
            el = page.query_selector(sel)
            if el:
                el.fill(valor)
                return True
        except Exception:
            continue
    raise RuntimeError(f"No encontré el campo para: {selectores[0]} …")


def _click_first(page, selectores):
    for sel in selectores:
        try:
            el = page.query_selector(sel)
            if el:
                el.click()
                return True
        except Exception:
            continue
    raise RuntimeError(f"No encontré el botón de envío: {selectores}")


# ─────────────────────────────────────────────────────────────────────────────
# API HTTP (con el JWT)
# ─────────────────────────────────────────────────────────────────────────────
def _headers(jwt):
    return {"Content-Type": "application/json", "Authorization": "Bearer " + jwt}


def listar_facturas(jwt, fecha_ini_mmddyyyy, fecha_fin_mmddyyyy,
                    page_size=100, source="Outbound"):
    """GetDocumentsDescargaMasiva → TODAS las facturas emitidas (paginando).

    Fechas en formato MM/DD/YYYY. Devuelve (items, total_item_count). Recorre todas
    las páginas hasta juntar `totalItemCount` (antes se perdían las de la 2ª página+).
    Cada item: number, DocumentOnlyPrefix, LDF, issueDate, amount, receiver{...}, ...
    """
    body = {
        "issueDateBegin": fecha_ini_mmddyyyy,
        "issueDateEnd": fecha_fin_mmddyyyy,
        "documentTypeCodes": ["FACTURA-UBL"],
        "branches": [],
        "processes": [],
        "source": source,
        "isSoporteAdquisicion": False,
    }
    todos = []
    total = 0
    page = 1
    vistos = set()
    while page <= 1000:   # tope de seguridad (1000 páginas * page_size = 100k facturas)
        url = (config.FACTURE_API +
               "/PLColab.Documents/Documents/GetDocumentsDescargaMasiva"
               f"?pageIndex={page}&pageSize={page_size}&includeCreditNoteStatus=true")
        r = requests.post(url, json=body, headers=_headers(jwt), timeout=60)
        if not r.ok:
            raise RuntimeError(f"GetDocumentsDescargaMasiva {r.status_code}: {r.text[:400]}")
        j = r.json()
        items = j.get("items", []) or []
        total = j.get("totalItemCount", total) or total
        # Deduplicar por LDF/number por si el RNDC repite algo entre páginas.
        nuevos = 0
        for it in items:
            clave = it.get("LDF") or it.get("number") or id(it)
            if clave in vistos:
                continue
            vistos.add(clave)
            todos.append(it)
            nuevos += 1
        # Parada robusta (sin depender solo de totalItemCount):
        #  - página incompleta (vino con menos que page_size) → es la última;
        #  - o ya juntamos el total reportado;
        #  - o esta página no aportó nada nuevo (evita bucles).
        if len(items) < page_size or (total and len(todos) >= total) or nuevos == 0:
            break
        page += 1
    return todos, (total or len(todos))


def get_content3(jwt, document_ldf):
    """Content3 → UBL de la factura en JSON (parties + InvoiceLines)."""
    url = config.FACTURE_API + "/PLColab.Documents/Document/Content3"
    r = requests.post(url, json={"documentLdf": document_ldf},
                      headers=_headers(jwt), timeout=60)
    r.raise_for_status()
    return r.json()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de extracción sobre el JSON de Content3
# ─────────────────────────────────────────────────────────────────────────────
def _prop(linea, nombre):
    """Lee AdditionalItemProperty[Name==nombre].Value de una InvoiceLine."""
    for p in (linea.get("Item", {}) or {}).get("AdditionalItemProperty", []) or []:
        if p and p.get("Name") == nombre:
            return p.get("Value")
    return None


def consecutivo_de_linea(linea):
    """Consecutivo REAL de la remesa = propiedad '02' (NO 'CodigoItem', que a
    veces trae el radicado). Verificado en factura 411930."""
    return _prop(linea, "02") or _prop(linea, "CodigoItem")


def datos_cliente(content3):
    """(nit_base, nombre) del cliente desde AccountingCustomerParty."""
    cust = content3.get("AccountingCustomerParty", {}) or {}
    return cust.get("PartyIdentification_ID", ""), cust.get("Party_Name", "")
