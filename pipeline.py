"""
Orquestador del bot plcolab-rpa. Todo en UNA pasada:

  login(Playwright) → listar facturas de AYER → (si hay) Content3 por factura
  → datos_rg → parsear (fe-tool) → radicados → generar_xml → subir al RNDC (p.86)

Idempotente: `estado.json` guarda las facturas ya subidas; si corre dos veces
el mismo día no duplica. Reporta un resumen al final.

Uso:
    python pipeline.py --fecha ayer
    python pipeline.py --fecha 2026-08-25
    python pipeline.py --fecha ayer --dry-run       # genera pero NO sube
    python pipeline.py --fecha ayer --debug-login    # inspecciona el login
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta

import settings as config
import facture_client
import fetool_bridge as fb
import reporte
import enviar

# La consola de Windows (cp1252) no encodea ✓/✗/⚠/·; forzamos UTF-8 en la salida.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ── Estado (idempotencia) ────────────────────────────────────────────────────
def cargar_estado():
    if config.ESTADO_PATH.exists():
        try:
            return json.loads(config.ESTADO_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"subidas": {}}


def guardar_estado(estado):
    config.ESTADO_PATH.write_text(
        json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Fechas ───────────────────────────────────────────────────────────────────
def resolver_fecha(arg):
    """'ayer' o 'YYYY-MM-DD' → objeto date."""
    if arg in (None, "", "ayer"):
        return date.today() - timedelta(days=1)
    if arg == "hoy":
        return date.today()
    return datetime.strptime(arg, "%Y-%m-%d").date()


def mmddyyyy(d):
    return d.strftime("%m/%d/%Y")


# ── Pipeline ─────────────────────────────────────────────────────────────────
def run(fecha_arg, dry_run=False, debug_login=False):
    fecha = resolver_fecha(fecha_arg)
    print(f"== plcolab-rpa == fecha objetivo: {fecha.isoformat()} "
          f"{'(DRY-RUN, no sube)' if dry_run else ''}")

    # 1) LOGIN
    print("[1/6] Login en facture (Playwright)…")
    jwt = facture_client.login(debug=debug_login)
    print("      JWT obtenido.")

    # 2) LISTAR facturas de la fecha
    print("[2/6] Listando facturas emitidas…")
    items, total = facture_client.listar_facturas(jwt, mmddyyyy(fecha), mmddyyyy(fecha))
    print(f"      {total} factura(s) en facture para {fecha.isoformat()}.")
    if not items:
        print("      No hay facturas → nada que hacer. Fin.")
        fstr = reporte.fecha_archivo(fecha)
        if config.correo_configurado():
            ok_mail, det = enviar.enviar_correo(
                f"Facturas PLCOLAB EMITIDAS {fstr} — Sin facturas",
                enviar.html_sin_facturas(fstr))
            print(f"      Correo (sin facturas): {'OK - ' if ok_mail else 'FALLO - '}{det}")
        return

    # Idempotencia: descartar las ya subidas
    estado = cargar_estado()
    ya = estado.get("subidas", {})
    pendientes = [it for it in items if str(it.get("number")) not in ya]
    print(f"      {len(pendientes)} pendiente(s) (ya subidas antes: {len(items) - len(pendientes)}).")
    if not pendientes:
        print("      Todo ya estaba subido. Fin.")
        return
    if config.MAX_FACTURAS:
        pendientes = pendientes[:config.MAX_FACTURAS]
        print(f"      Tope MAX_FACTURAS={config.MAX_FACTURAS} → {len(pendientes)}.")

    # 3) Content3 por factura
    print("[3/6] Descargando datos (Content3) de cada factura…")
    con_datos = []
    for it in pendientes:
        ldf = it.get("LDF")
        try:
            c3 = facture_client.get_content3(jwt, ldf)
            con_datos.append({"item": it, "content3": c3})
        except Exception as e:
            print(f"      ! {it.get('number')}: error Content3: {e}")

    # 4) datos_rg → parsear (fe-tool)
    print("[4/6] Armando datos_rg y parseando (lógica fe-tool)…")
    df = fb.construir_datos_rg(con_datos)
    # Auditoría: guardar el datos_rg físico (equivale al datos_rg.xlsx del flujo manual)
    ruta_datos_rg = reporte.guardar_datos_rg(df, fecha, str(config.SALIDAS_DIR))
    print(f"      datos_rg (auditoría): {ruta_datos_rg}")
    facturas = fb.parsear(df)
    print(f"      {len(facturas)} factura(s) armada(s), "
          f"{sum(len(d['remesas']) for d in facturas)} remesa(s).")

    # 5) Radicados
    print("[5/6] Consultando radicados en el RNDC…")
    fb.completar_radicados(facturas)

    # 6) Generar XML + subir (agrupado por perfil)
    print(f"[6/6] Generando XML y {'(DRY-RUN) ' if dry_run else ''}subiendo al RNDC (proceso 86)…")
    subidas, fallidas, revision = [], [], []
    reporte_rows, xmls_generados = [], []
    for d in facturas:
        nf = d.get("numero_factura", "?")
        cliente = d.get("nombre_cliente", "")
        remesas = [r.get("consecutivo", "") for r in d.get("remesas", [])]

        def _fila(exito, mensaje):
            reporte_rows.append({"cliente": cliente, "factura": nf, "remesas": remesas,
                                 "exito": exito, "ingresoid": "", "mensaje": mensaje})

        pf, nom = fb.perfil_de_factura(d)
        if pf is None:
            revision.append(nf)
            _fila(False, "Perfil no resuelto (revisar consecutivos).")
            print(f"      ⚠ {nf}: perfil no resuelto (revisar consecutivos) → NO se sube.")
            continue
        try:
            xml = fb.generar_xml_factura(d, pf)
        except Exception as e:
            fallidas.append((nf, f"gen XML: {e}"))
            _fila(False, f"Error generando XML: {e}")
            print(f"      ✗ {nf} [{nom}]: error generando XML: {e}")
            continue
        xmls_generados.append((f"FACTURA_{nf}.xml", xml))
        if dry_run:
            _fila(False, "(dry-run: no se envió al RNDC)")
            print(f"      · {nf} [{nom}]: XML generado (dry-run, no se sube).")
            continue
        try:
            ok, msg = fb.enviar_al_rndc(xml, pf)
        except Exception as e:
            ok, msg = False, str(e)
        _fila(ok, msg)
        if ok:
            subidas.append(nf)
            ya[str(nf)] = {"fecha": fecha.isoformat(), "perfil": nom,
                           "ts": datetime.now().isoformat(timespec="seconds"), "msg": msg}
            print(f"      ✓ {nf} [{nom}]: {msg}")
        else:
            fallidas.append((nf, msg))
            print(f"      ✗ {nf} [{nom}]: {msg}")

    if not dry_run:
        estado["subidas"] = ya
        guardar_estado(estado)

    # 7) Reporte final: Excel "Facturas PLCOLAB <fecha>.xlsx" + zip con los XML
    out_dir = str(config.SALIDAS_DIR)
    ruta_xlsx = reporte.generar_reporte_excel(reporte_rows, fecha, out_dir)
    ruta_zip = reporte.generar_zip_xmls(xmls_generados, fecha, out_dir) if xmls_generados else None
    print(f"\n  Reporte Excel : {ruta_xlsx}")
    if ruta_zip:
        print(f"  Zip de XML    : {ruta_zip}")

    # 8) Envío del reporte por correo (cuerpo HTML cordial + adjuntos)
    fstr = reporte.fecha_archivo(fecha)
    if config.correo_configurado():
        resumen = {
            "total_facturas": len(facturas),
            "total_remesas": sum(len(d.get("remesas", [])) for d in facturas),
            "subidas": len(subidas),
            "fallidas": len(fallidas),
            "revision": len(revision),
        }
        adjuntos = [ruta_xlsx] + ([ruta_zip] if ruta_zip else [])
        ok_mail, det = enviar.enviar_correo(
            f"Facturas PLCOLAB EMITIDAS {fstr}",
            enviar.html_con_facturas(fstr, resumen),
            adjuntos)
        print(f"  Correo        : {'OK - ' if ok_mail else 'FALLO - '}{det}")
    else:
        print("  Correo        : omitido (no configurado)")

    # Resumen
    print("\n== RESUMEN ==")
    print(f"  Subidas OK : {len(subidas)}")
    print(f"  Fallidas   : {len(fallidas)}")
    print(f"  A revisión : {len(revision)} (perfil no resuelto)")
    if fallidas:
        print("  Detalle fallidas:")
        for nf, m in fallidas:
            print(f"    - {nf}: {m}")
    if revision:
        print("  A revisión (consecutivos/ perfil):", ", ".join(map(str, revision)))
    return {"subidas": subidas, "fallidas": fallidas, "revision": revision,
            "reporte_xlsx": ruta_xlsx, "reporte_zip": ruta_zip}


def main():
    ap = argparse.ArgumentParser(description="Bot plcolab-rpa: facture → RNDC (proceso 86).")
    ap.add_argument("--fecha", default="ayer", help="'ayer' (default), 'hoy' o 'YYYY-MM-DD'.")
    ap.add_argument("--dry-run", action="store_true", help="Genera XML pero NO sube al RNDC.")
    ap.add_argument("--debug-login", action="store_true", help="Muestra info del login.")
    args = ap.parse_args()
    try:
        run(args.fecha, dry_run=args.dry_run, debug_login=args.debug_login)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
