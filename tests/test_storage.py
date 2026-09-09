import sqlite3

import pytest

from storage import Storage
from analyzer import Imovel


def mk(url="http://x/1", **kw):
    d = dict(titulo="Casa", bairro="Jardim Acapulco", cidade="Guaruja", tipo="casa",
             preco=2_000_000.0, area=250.0, quartos=4, vagas=2, fonte="teste",
             preco_m2=8000.0)
    d.update(kw)
    im = Imovel(url=url, **{k: d[k] for k in ("titulo", "bairro", "cidade", "tipo",
                                             "preco", "area", "quartos", "vagas", "fonte")})
    im.preco_m2 = d["preco_m2"]
    return im


def test_upsert_e_carregar_comparaveis(tmp_path):
    st = Storage(str(tmp_path / "t.db"))
    st.upsert_imovel(mk(url="http://x/a"))
    st.upsert_imovel(mk(url="http://x/b", preco_m2=None))   # não deve aparecer
    rows = st.carregar_comparaveis()
    st.fechar()
    assert len(rows) == 1
    url, cidade, bairro, tipo, area, quartos, preco_m2 = rows[0]
    assert (url, cidade, bairro, tipo, preco_m2) == (
        "http://x/a", "Guaruja", "Jardim Acapulco", "casa", 8000.0)


def test_alerta_guarda_preco_e_score(tmp_path):
    st = Storage(str(tmp_path / "t.db"))
    assert st.ja_alertado("http://x/a") is False
    st.marcar_alertado("http://x/a", score=42.0, preco=1_800_000.0)
    assert st.ja_alertado("http://x/a") is True
    assert st.info_alerta("http://x/a") == (1_800_000.0, 42.0)
    st.fechar()


def test_migracao_adiciona_coluna_preco(tmp_path):
    p = str(tmp_path / "old.db")
    con = sqlite3.connect(p)
    con.executescript("""
        CREATE TABLE alertas (url TEXT PRIMARY KEY, score REAL, alertado_em REAL);
        INSERT INTO alertas VALUES ('http://x/old', 10.0, 123.0);
    """)
    con.commit()
    con.close()

    st = Storage(p)                       # _migrar() deve rodar sem erro
    assert st.info_alerta("http://x/old") == (None, 10.0)
    st.marcar_alertado("http://x/new", 5.0, 900_000.0)
    assert st.info_alerta("http://x/new") == (900_000.0, 5.0)
    st.fechar()
