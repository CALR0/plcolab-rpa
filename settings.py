"""
Configuración del bot (nombre `settings` a propósito: fe-tool ya usa el paquete
`config/`, así que NO podemos llamar a este módulo `config` sin colisión).

Carga variables de entorno (.env) y deja a fe-tool importable agregando
FE_TOOL_PATH al sys.path. Todo lo sensible (credenciales) viene de entorno.
"""
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass  # en GitHub Actions las vars vienen de Secrets, no de .env

# ── Rutas ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent

FE_TOOL_PATH = os.getenv("FE_TOOL_PATH", "../testap")
_fetool = (BASE_DIR / FE_TOOL_PATH).resolve() if not os.path.isabs(FE_TOOL_PATH) else Path(FE_TOOL_PATH)
if not _fetool.exists():
    raise RuntimeError(
        f"No encuentro fe-tool en FE_TOOL_PATH={_fetool}. "
        f"Ajusta FE_TOOL_PATH en .env (local: ../testap; nube: ./fe-tool submodule)."
    )
# Deja core/ services/ webapp/ config/ de fe-tool importables. Va en sys.path[0]
# para que `from config.perfiles import ...` resuelva al paquete config/ de fe-tool.
sys.path.insert(0, str(_fetool))
FE_TOOL_DIR = _fetool

# ── Facture (login) ──────────────────────────────────────────────────────────
FACTURE_USER = os.getenv("FACTURE_USER", "")
FACTURE_PASS = os.getenv("FACTURE_PASS", "")
FACTURE_LOGIN_URL = os.getenv(
    "FACTURE_LOGIN_URL", "https://plataforma.facture.co/plataforma/login"
)
FACTURE_API = "https://api.facture.co"

PLAYWRIGHT_HEADLESS = os.getenv("PLAYWRIGHT_HEADLESS", "1") not in ("0", "false", "False")

# ── RNDC ─────────────────────────────────────────────────────────────────────
RNDC_ENDPOINT_NOMBRE = os.getenv("RNDC_ENDPOINT", "Producción (rndcws)")

# ── Comportamiento ───────────────────────────────────────────────────────────
MAX_FACTURAS = int(os.getenv("MAX_FACTURAS", "0") or "0")  # 0 = sin tope
ESTADO_PATH = BASE_DIR / "estado.json"
SALIDAS_DIR = BASE_DIR / "salidas"

# ── Correo (envío del reporte) ───────────────────────────────────────────────
# Para Gmail: SMTP_HOST=smtp.gmail.com, SMTP_PORT=587, SMTP_USER=tu@gmail.com,
# SMTP_PASS=<contraseña de aplicación de 16 dígitos> (requiere 2FA en la cuenta).
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or "587")
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
MAIL_TO = os.getenv("MAIL_TO", "")           # destinatario(s), separados por coma
MAIL_FROM = os.getenv("MAIL_FROM", "")       # opcional; por defecto = SMTP_USER


def correo_configurado():
    return bool(SMTP_USER and SMTP_PASS and MAIL_TO)


def cargar_perfiles():
    """Devuelve el dict PERFILES de fe-tool (config/perfiles.py de fe-tool)."""
    try:
        from config.perfiles import PERFILES  # type: ignore  (paquete config/ de fe-tool)
        return PERFILES
    except Exception as e:
        raise RuntimeError(
            "No pude importar PERFILES desde fe-tool (config/perfiles.py). "
            "En local: asegúrate de que fe-tool tenga su config/perfiles.py. "
            f"Detalle: {e}"
        )
