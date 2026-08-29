"""Envío del reporte por correo (SMTP), con cuerpo HTML cordial.
Configuración en settings/.env/Secrets. Si el correo no está configurado, el
pipeline lo omite (los archivos quedan en salidas/ y como artefacto de GitHub)."""
import mimetypes
import os
import smtplib
import ssl
from email.message import EmailMessage

import settings

# Paleta moderna: carbón + esmeralda + crema (nada de azul corporativo).
_INK = "#16181d"        # header carbón
_ACCENT = "#10b981"     # esmeralda
_ACCENT_DK = "#0f9d70"
_MINT = "#e9fbf3"
_PAGE = "#f3f1ec"       # crema cálido
_TEXT = "#1c1f24"
_MUTED = "#8a8f98"
_RED = "#e5544b"
_FONT = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,"
         "sans-serif")


def _shell(etiqueta, cuerpo_interno):
    """Layout moderno del correo (tablas + estilos inline, compatible con clientes)."""
    return f"""\
<!DOCTYPE html><html><body style="margin:0;padding:0;background:{_PAGE};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_PAGE};padding:32px 12px;">
<tr><td align="center">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0"
         style="max-width:600px;background:#ffffff;border-radius:18px;overflow:hidden;
                font-family:{_FONT};color:{_TEXT};
                box-shadow:0 10px 30px rgba(20,22,28,.10);">
    <!-- header carbón -->
    <tr><td style="background:{_INK};padding:30px 34px 26px;">
      <div style="color:#ffffff;font-size:25px;font-weight:800;letter-spacing:-.4px;
                  line-height:1.15;">Facturas emitidas</div>
      <div style="display:inline-block;margin-top:12px;padding:5px 12px;
                  background:rgba(16,185,129,.16);border:1px solid rgba(16,185,129,.35);
                  border-radius:999px;color:{_ACCENT};font-size:12px;font-weight:700;
                  letter-spacing:.4px;">{etiqueta}</div>
    </td></tr>
    <tr><td style="padding:30px 34px 8px;">{cuerpo_interno}</td></tr>
    <tr><td style="padding:20px 34px 26px;color:{_MUTED};font-size:11px;
                   line-height:1.5;border-top:1px solid #f0efeb;">
      Generado automáticamente por <b style="color:{_TEXT};">plcolab-rpa</b> ·
      integración con facture.co. Correo informativo, no responder.
    </td></tr>
  </table>
</td></tr></table>
</body></html>"""


def html_sin_facturas(fecha_str):
    cuerpo = f"""
      <p style="font-size:15px;margin:0 0 18px;color:{_TEXT};">Cordial saludo,</p>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
             style="background:{_PAGE};border-radius:14px;">
        <tr><td style="padding:30px 24px;text-align:center;">
          <div style="font-size:34px;line-height:1;margin-bottom:10px;">📭</div>
          <div style="font-size:18px;font-weight:800;color:{_TEXT};">
            Sin facturas emitidas</div>
          <div style="font-size:14px;color:{_MUTED};margin-top:8px;line-height:1.5;">
            No se encontró información de facturas emitidas para el día
            <b style="color:{_TEXT};">{fecha_str}</b>.<br>No se realizó ningún cargue al RNDC.
          </div>
        </td></tr>
      </table>
      <p style="font-size:13px;color:{_MUTED};margin:20px 0 4px;text-align:center;">
        El proceso se ejecutará de nuevo en la próxima corrida programada.</p>"""
    return _shell(fecha_str, cuerpo)


def _stat(label, valor, color, width="25%"):
    return (f'<td width="{width}" style="padding:6px;">'
            f'<div style="background:#ffffff;border:1px solid #eef0f2;border-radius:12px;'
            f'padding:14px 10px;text-align:center;">'
            f'<div style="font-size:24px;font-weight:800;color:{color};line-height:1;">{valor}</div>'
            f'<div style="font-size:11px;color:{_MUTED};margin-top:6px;font-weight:600;'
            f'letter-spacing:.2px;">{label}</div></div></td>')


def html_con_facturas(fecha_str, resumen):
    n = resumen.get("total_facturas", 0)
    rem = resumen.get("total_remesas", 0)
    si = resumen.get("subidas", 0)
    # "No subidos" incluye las rechazadas y las de perfil no resuelto (no se cargaron).
    no = resumen.get("fallidas", 0) + resumen.get("revision", 0)
    envio = _stat("Subidos", si, _ACCENT_DK, "50%") + _stat("No subidos", no, _RED, "50%")
    cuerpo = f"""
      <p style="font-size:15px;margin:0 0 6px;color:{_TEXT};">Cordial saludo,</p>
      <p style="font-size:15px;line-height:1.55;margin:0 0 20px;color:{_TEXT};">
        El día <b>{fecha_str}</b> se encontraron facturas emitidas y fueron procesadas
        para su cargue al RNDC.
      </p>
      <!-- cuadro verde: facturas y remesas encontradas -->
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
             style="background:{_MINT};border:1px solid #cdeede;border-radius:14px;margin:0 0 22px;">
        <tr>
          <td width="50%" style="padding:20px 24px;border-right:1px solid #cdeede;">
            <div style="font-size:11px;font-weight:700;letter-spacing:.5px;color:{_ACCENT_DK};
                        text-transform:uppercase;">Facturas encontradas</div>
            <div style="font-size:38px;font-weight:800;color:{_TEXT};line-height:1;margin-top:6px;">{n}</div>
          </td>
          <td width="50%" style="padding:20px 24px;">
            <div style="font-size:11px;font-weight:700;letter-spacing:.5px;color:{_ACCENT_DK};
                        text-transform:uppercase;">Remesas encontradas</div>
            <div style="font-size:38px;font-weight:800;color:{_TEXT};line-height:1;margin-top:6px;">{rem}</div>
          </td>
        </tr>
      </table>
      <!-- detalles de envío al RNDC -->
      <div style="font-size:13px;font-weight:800;color:{_TEXT};letter-spacing:.2px;margin:0 0 10px;">
        Detalles de envío al RNDC</div>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
             style="margin:0 -6px 4px;"><tr>{envio}</tr></table>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
             style="margin:20px 0 6px;">
        <tr><td style="background:{_PAGE};border-radius:12px;padding:16px 18px;
                       font-size:13px;line-height:1.55;color:#4b5058;">
          📎 Se adjuntan el <b style="color:{_TEXT};">reporte detallado (Excel)</b> y el
          <b style="color:{_TEXT};">.zip con los XML</b>. En el reporte, la columna
          <i>Novedad</i> muestra el resultado de cada factura (radicado si subió, o el
          motivo del rechazo).
        </td></tr>
      </table>"""
    return _shell(fecha_str, cuerpo)


def enviar_correo(asunto, html, adjuntos=None):
    """Envía un correo HTML con adjuntos (rutas). Retorna (ok, detalle)."""
    if not settings.correo_configurado():
        return False, "correo no configurado (faltan SMTP_USER/SMTP_PASS/MAIL_TO)"

    msg = EmailMessage()
    msg["From"] = settings.MAIL_FROM or settings.SMTP_USER
    msg["To"] = settings.MAIL_TO
    msg["Subject"] = asunto
    msg.set_content("Este correo requiere un cliente compatible con HTML.")
    msg.add_alternative(html, subtype="html")

    for ruta in (adjuntos or []):
        if not ruta or not os.path.exists(ruta):
            continue
        ctype, _ = mimetypes.guess_type(ruta)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        with open(ruta, "rb") as fh:
            msg.add_attachment(fh.read(), maintype=maintype, subtype=subtype,
                               filename=os.path.basename(ruta))
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(settings.SMTP_USER, settings.SMTP_PASS)
            s.send_message(msg)
        return True, f"enviado a {settings.MAIL_TO}"
    except Exception as e:
        return False, f"error enviando correo: {e}"
