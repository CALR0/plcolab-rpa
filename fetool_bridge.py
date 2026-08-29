"""
Puente hacia fe-tool: reutiliza su lógica MASIVA (la de "Generar XML vía Excel")
sin reimplementar nada. Toma los datos de facture (Content3), los mete en un
DataFrame con las MISMAS columnas de `datos_rg`, y de ahí en adelante todo es
fe-tool:

    df (datos_rg)  →  lib_excel.parsear  →  consultar_radicado_remesa
                   →  core.xml_generator.generar_xml  →  lib_rndc86.enviar_factura_rndc

Espejo de webapp/app.py::modulo_generar_excel + modulo_cargar_rndc.
"""
import pandas as pd

import settings as config  # agrega fe-tool al sys.path al importarse

# --- Imports de fe-tool (disponibles gracias a config.FE_TOOL_PATH) ---
from webapp import lib_excel, lib_rndc86                       # noqa: E402
from webapp.lib_extraer import (                               # noqa: E402
    COLUMNAS_EXPORT, _perfil_por_consecutivo, _nit_con_dv,
)
from core.xml_generator import generar_xml                     # noqa: E402
from services.rndc_service import consultar_radicado_remesa    # noqa: E402

import facture_client                                          # noqa: E402

PERFILES = config.cargar_perfiles()


# ─────────────────────────────────────────────────────────────────────────────
# 1) Content3 → filas datos_rg (una fila por remesa)
# ─────────────────────────────────────────────────────────────────────────────
def construir_datos_rg(facturas):
    """`facturas` = lista de dicts {item, content3} (item del listado + su Content3).
    Devuelve un DataFrame con exactamente las columnas de datos_rg."""
    filas = []
    for f in facturas:
        item = f["item"]
        c3 = f["content3"]
        numero = str(item.get("number", "")).strip()
        fecha = str(item.get("issueDate", ""))[:10]      # YYYY-MM-DD
        cufe = c3.get("UUID", "")
        nit_base, nombre_cli = facture_client.datos_cliente(c3)
        nit = _nit_con_dv(nit_base)                       # NIT + dígito (igual que el PDF)
        val_total = item.get("amount", 0) or 0

        lineas = c3.get("InvoiceLines", []) or []
        n_rem = len(lineas)
        for ln in lineas:
            consec_raw = facture_client.consecutivo_de_linea(ln)   # propiedad "02"
            perfil_det, consec = _perfil_por_consecutivo(consec_raw)
            desc = (ln.get("Item", {}) or {}).get("Description", "") or "Servicio de transporte"
            try:
                valor_unit = float(ln.get("PriceAmount") or 0)
            except Exception:
                valor_unit = 0.0
            filas.append({
                "numero_factura": numero,
                "fecha_generacion": fecha,
                "cufe": cufe,
                "nit": nit,
                "nombre_cliente": nombre_cli,
                "descripcion": desc,
                "consecutivo_remesa": consec,
                "radicado": "",                # se consulta luego
                "valor_unitario": valor_unit,
                "valor_total_factura": val_total,
                "cantidad_remesas_rg": n_rem,
                "perfil": perfil_det,          # tsp / elogia / "" (por el "02")
            })
    return pd.DataFrame(filas, columns=COLUMNAS_EXPORT)


# ─────────────────────────────────────────────────────────────────────────────
# 2) DataFrame → facturas (lógica de fe-tool: agrupar, expandir, split perfil)
# ─────────────────────────────────────────────────────────────────────────────
def parsear(df):
    """Reutiliza lib_excel.auto_mapear + parsear (sin filtro)."""
    mapping = lib_excel.auto_mapear(df)
    facturas = lib_excel.parsear(df, mapping, "Todas (sin filtro)", {})
    return facturas


def perfil_de_factura(d):
    """(perfil_dict, nombre) según la columna 'perfil' de la factura.
    Estricto: si no es tsp/elogia, devuelve (None, "") → se marca para revisión."""
    nom = (d.get("perfil") or "").strip().lower()
    if nom == "tsp":
        return PERFILES["ut_tsp"], "tsp"
    if nom == "elogia":
        return PERFILES["ut_elogia"], "elogia"
    return None, ""


# ─────────────────────────────────────────────────────────────────────────────
# 3) Radicados (con el perfil de CADA factura) — espejo de modulo_generar_excel
# ─────────────────────────────────────────────────────────────────────────────
def completar_radicados(facturas):
    for d in facturas:
        pf, _nom = perfil_de_factura(d)
        if pf is None:
            continue
        for rem in d["remesas"]:
            consec = (rem.get("consecutivo") or "").strip()
            rad = (rem.get("radicado") or "").strip()
            if consec and rad.lower() in ("", "nan", "none", "0"):
                try:
                    ok, res = consultar_radicado_remesa(consec, pf)
                    rem["radicado"] = res.get("radicado", "0") if ok else "0"
                except Exception:
                    rem["radicado"] = "0"
            elif not rad or rad.lower() in ("nan", "none"):
                rem["radicado"] = "0"


# ─────────────────────────────────────────────────────────────────────────────
# 4) Generar XML + enviar al RNDC (proceso 86), agrupado por perfil
# ─────────────────────────────────────────────────────────────────────────────
def generar_xml_factura(d, pf):
    """Devuelve el XML (bytes) de una factura."""
    xml = generar_xml(d, perfil=pf)
    return xml.encode("utf-8")


def enviar_al_rndc(xml_bytes, pf):
    """enviar_factura_rndc con las credenciales del perfil. (ok, mensaje)."""
    endpoint = lib_rndc86.ENDPOINTS.get(config.RNDC_ENDPOINT_NOMBRE)
    return lib_rndc86.enviar_factura_rndc(
        xml_bytes,
        pf.get("rndc_usuario", ""),
        pf.get("rndc_password", ""),
        pf.get("nit_socio", ""),
        endpoint=endpoint,
    )
