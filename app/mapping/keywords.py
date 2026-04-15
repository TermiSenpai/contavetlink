"""Motor de keyword matching para resolución automática de artículos.

Coincide texto libre de líneas de factura contra una lista de keywords
(case-insensitive, substring) ordenadas por prioridad descendente. La primera
coincidencia gana — el orden de prioridad lo controla el operador desde la UI.

CRUD + matching viven juntos a propósito: el motor es trivial, separar en dos
módulos solo añadiría imports cruzados.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.mapping.store import validar_subcuenta_ingreso


@dataclass(frozen=True)
class Keyword:
    id: int
    keyword: str
    cuenta_a3: str
    prioridad: int
    activo: bool


# ─── Matching ──────────────────────────────────────────────────────────────


def match(texto: str, keywords: list[Keyword]) -> Keyword | None:
    """Devuelve la primera keyword que matchea `texto`.

    Reglas:
      - Case-insensitive, substring match (sin regex en v1.0)
      - Las keywords inactivas se ignoran
      - El orden de evaluación es el que se le pasa: el caller debe haber
        ordenado por prioridad DESC con `load_keywords()`. No re-ordena aquí
        para que match() siga siendo trivialmente testeable sin BD.
    """
    if not texto:
        return None
    texto_lower = texto.lower()
    for kw in keywords:
        if not kw.activo:
            continue
        if kw.keyword and kw.keyword.lower() in texto_lower:
            return kw
    return None


# ─── Persistencia ─────────────────────────────────────────────────────────


def load_keywords(conn: sqlite3.Connection, solo_activos: bool = True) -> list[Keyword]:
    """Carga keywords ordenadas por `prioridad DESC, id ASC` (orden estable)."""
    where = "WHERE activo = 1" if solo_activos else ""
    rows = conn.execute(
        f"""
        SELECT id, keyword, cuenta_a3, prioridad, activo
        FROM keywords_articulos
        {where}
        ORDER BY prioridad DESC, id ASC
        """
    ).fetchall()
    return [_row_to_keyword(r) for r in rows]


def add_keyword(
    conn: sqlite3.Connection,
    keyword: str,
    cuenta_a3: str,
    prioridad: int = 10,
    activo: bool = True,
) -> int:
    """Inserta una keyword. Lanza si la subcuenta no es válida o ya existe."""
    keyword_norm = (keyword or '').strip()
    if not keyword_norm:
        raise ValueError("La keyword no puede estar vacía")
    validar_subcuenta_ingreso(cuenta_a3)
    try:
        cur = conn.execute(
            """
            INSERT INTO keywords_articulos (keyword, cuenta_a3, prioridad, activo)
            VALUES (?, ?, ?, ?)
            """,
            (keyword_norm, cuenta_a3, int(prioridad), 1 if activo else 0),
        )
    except sqlite3.IntegrityError as e:
        raise ValueError(f"La keyword ya existe: {keyword_norm!r}") from e
    return int(cur.lastrowid)


def update_keyword(
    conn: sqlite3.Connection,
    keyword_id: int,
    *,
    keyword: str | None = None,
    cuenta_a3: str | None = None,
    prioridad: int | None = None,
    activo: bool | None = None,
) -> None:
    """Actualiza campos individuales. Solo los que llegan no-None se tocan."""
    if cuenta_a3 is not None:
        validar_subcuenta_ingreso(cuenta_a3)
    if keyword is not None and not keyword.strip():
        raise ValueError("La keyword no puede estar vacía")

    sets: list[str] = []
    valores: list[object] = []
    if keyword is not None:
        sets.append("keyword = ?")
        valores.append(keyword.strip())
    if cuenta_a3 is not None:
        sets.append("cuenta_a3 = ?")
        valores.append(cuenta_a3)
    if prioridad is not None:
        sets.append("prioridad = ?")
        valores.append(int(prioridad))
    if activo is not None:
        sets.append("activo = ?")
        valores.append(1 if activo else 0)

    if not sets:
        return

    valores.append(keyword_id)
    cur = conn.execute(
        f"UPDATE keywords_articulos SET {', '.join(sets)} WHERE id = ?",
        valores,
    )
    if cur.rowcount == 0:
        raise KeyError(f"Keyword no encontrada: id={keyword_id}")


def delete_keyword(conn: sqlite3.Connection, keyword_id: int) -> None:
    cur = conn.execute(
        "DELETE FROM keywords_articulos WHERE id = ?",
        (keyword_id,),
    )
    if cur.rowcount == 0:
        raise KeyError(f"Keyword no encontrada: id={keyword_id}")


def _row_to_keyword(row: sqlite3.Row) -> Keyword:
    return Keyword(
        id=int(row['id']),
        keyword=row['keyword'],
        cuenta_a3=row['cuenta_a3'],
        prioridad=int(row['prioridad']),
        activo=bool(row['activo']),
    )
