"""Valida um snapshot SQLite antes de restaurar ou publicar o estado."""
import sqlite3
import sys
from pathlib import Path


def validar(caminho):
    path = Path(caminho).resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("Snapshot do banco ausente ou vazio.")
    con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        if con.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Snapshot SQLite corrompido.")
        for table, required in {
            "imoveis": {"url", "preco", "area", "preco_m2", "atualizado_em"},
            "alertas": {"url", "score", "alertado_em"},
        }.items():
            columns = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
            if not required <= columns:
                raise ValueError(f"Tabela incompatível: {table}")
    finally:
        con.close()


if __name__ == "__main__":
    validar(sys.argv[1])
