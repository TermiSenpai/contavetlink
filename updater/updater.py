"""Auto-updater contra GitHub Releases.

Flujo (Sección 11 del plan):
    Arranque
        ├─ Sin conexión ──────────────────► continuar (silencioso)
        ├─ Versión == última ─────────────► continuar normal
        └─ Versión nueva
               ├─ SHA-256 falla → descartar, avisar
               └─ SHA-256 OK   → banner "Actualización disponible"
                                 (descarga + reemplazo manual)

El SQLite del usuario vive en %APPDATA% — nunca se toca en una actualización.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

GITHUB_REPO = "xkoi-studio/gesdai-exporter"  # privado — token requerido
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
TIMEOUT_SEGUNDOS = 5


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    download_url: str
    sha256: str
    notes: str


class UpdateError(Exception):
    """Fallo al comprobar/descargar/verificar una actualización."""


def check_for_updates() -> UpdateInfo | None:
    """Comprueba si hay una versión nueva disponible.

    Devuelve `UpdateInfo` si hay actualización, `None` si ya está al día
    o si no hay conexión. Nunca lanza excepción al caller — los errores
    se loguean y se devuelve None.
    """
    raise NotImplementedError("Pendiente de implementar en Fase 6")


def download_update(info: UpdateInfo, destino: Path) -> Path:
    """Descarga el .exe nuevo y verifica su SHA-256.

    Lanza UpdateError si el hash no coincide.
    """
    raise NotImplementedError("Pendiente de implementar en Fase 6")


def _verify_sha256(ruta: Path, esperado: str) -> bool:
    h = hashlib.sha256()
    with ruta.open('rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest().lower() == esperado.lower()
