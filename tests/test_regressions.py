from types import SimpleNamespace
from unittest.mock import Mock
import sqlite3
import pytest
import yaml

from analyzer import Imovel, _dedupe
from main import rodar_ciclo, validar_config
from notifier import Telegram
from scraper import raspar_site, raspar_todos, _monta_url_pagina, _robots_permite, _ROBOTS_CACHE, DEFAULT_UA
from storage import Storage
from tools.validar_db import validar


def test_dedupe_preserva_cidades_distintas():
    ims = [Imovel(url=f"https://x/{i}", titulo="Casa no Centro", cidade=c,
                  bairro="Centro", tipo="casa", preco=500000, area=100, quartos=2)
           for i, c in enumerate(["Guaruja", "Peruibe"])]
    assert len(_dedupe(ims)) == 2


def test_pagina_preserva_query_e_fragmento():
    assert _monta_url_pagina("https://x/busca?page={page}&tipo=casa#lista", 1, True) == "https://x/busca?tipo=casa#lista"


@pytest.fixture
def fake_site():
    return dict(nome="teste", base_url="https://x", listagem_url="https://x/lista",
                cidade="Guaruja", detalhe=True, seletores={"card": "article", "titulo": "h2"})


def test_robots_especifico_tem_prioridade():
    _ROBOTS_CACHE.clear()
    sess = Mock()
    sess.get.return_value = SimpleNamespace(status_code=200, text="User-agent: ImovelBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
    assert not _robots_permite(sess, "https://x/lista", DEFAULT_UA)
    _ROBOTS_CACHE.clear()


def test_coleta_card_sem_acessar_detalhe_proibido(fake_site, monkeypatch):
    _ROBOTS_CACHE.clear()
    monkeypatch.setattr("scraper.time.sleep", lambda _: None)
    html = '<article><a href="/privado/1"><h2>Casa Centro</h2></a>R$ 500.000 100 m2 2 quartos</article>'
    sess = Mock(headers={})
    robots = SimpleNamespace(status_code=200, text="User-agent: *\nDisallow: /privado/\n")
    pagina = SimpleNamespace(text=html, encoding="utf-8", raise_for_status=lambda: None)
    sess.get.side_effect = [robots, pagina]
    ims = raspar_site(fake_site, session=sess, delay=0)
    assert len(ims) == 1
    assert ims[0].preco == 500000 and ims[0].area == 100
    assert sess.get.call_count == 2
    _ROBOTS_CACHE.clear()


def test_coleta_vazia_sinaliza_falha(fake_site, monkeypatch):
    monkeypatch.setattr("scraper.raspar_site", lambda *a, **k: [])
    with pytest.raises(RuntimeError, match="Nenhum anúncio"):
        raspar_todos({"sites": [fake_site]})


@pytest.mark.parametrize("sucesso", [True, False])
def test_ciclo_so_marca_envio_confirmado(sucesso, monkeypatch):
    im = Imovel(url="https://x/1", descricao="espolio", preco=500000, area=100)
    monkeypatch.setattr("main.raspar_todos", lambda *a, **k: [im])
    monkeypatch.setattr("main.time.sleep", lambda _: None)
    st = Storage(":memory:")
    tg = Mock()
    tg.enviar.return_value = sucesso
    try:
        if sucesso:
            assert rodar_ciclo({}, st, tg) == 1
            assert st.info_alerta(im.url)[0] == 500000
            assert rodar_ciclo({}, st, tg) == 0
            assert tg.enviar.call_count == 1
        else:
            with pytest.raises(RuntimeError, match="Falha no envio"):
                rodar_ciclo({}, st, tg)
            assert not st.ja_alertado(im.url)
    finally:
        st.fechar()


def test_dry_run_nao_envia_nem_marca(monkeypatch):
    monkeypatch.setattr("main.raspar_todos", lambda *a, **k: [Imovel(url="https://x/1", descricao="espolio", preco=500000, area=100)])
    tg = Mock()
    st = Storage(":memory:")
    try:
        assert rodar_ciclo({}, st, tg, dry_run=True) == 1
        tg.enviar.assert_not_called()
        assert not st.ja_alertado("https://x/1")
    finally:
        st.fechar()


@pytest.mark.parametrize("status,body,esperado", [(200,{"ok":True},True),(200,{"ok":False},False),(429,{},False),(500,{},False)])
def test_telegram_verifica_resposta(monkeypatch, status, body, esperado):
    monkeypatch.setattr("notifier.requests.post", lambda *a, **k: SimpleNamespace(status_code=status, text="erro", json=lambda: body))
    assert Telegram("fake", "123").enviar("teste") is esperado


def test_telegram_nao_expoe_token(monkeypatch, caplog):
    def falha(*a, **k):
        raise RuntimeError("https://api.telegram.org/botSEGREDO/sendMessage")
    monkeypatch.setattr("notifier.requests.post", falha)
    assert not Telegram("SEGREDO", "123").enviar("teste")
    assert "SEGREDO" not in caplog.text


def test_telegram_aguarda_e_repete_apos_429(monkeypatch):
    respostas = iter([
        SimpleNamespace(status_code=429, text="limite", json=lambda: {
            "ok": False, "parameters": {"retry_after": 2}}),
        SimpleNamespace(status_code=200, text="ok", json=lambda: {"ok": True}),
    ])
    post = Mock(side_effect=lambda *a, **k: next(respostas))
    sleep = Mock()
    monkeypatch.setattr("notifier.requests.post", post)
    monkeypatch.setattr("notifier.time.sleep", sleep)
    assert Telegram("fake", "123").enviar("teste")
    assert post.call_count == 2
    sleep.assert_called_once_with(3)


def test_config_exemplo_valida():
    from pathlib import Path
    validar_config(yaml.safe_load(Path("config.example.yaml").read_text(encoding="utf-8")))


@pytest.mark.parametrize("cfg", [None, [], {}, {"sites": []}, {"sites": [None]}, {"telegram": None}])
def test_config_invalida(cfg):
    with pytest.raises(ValueError):
        validar_config(cfg)


def test_valida_snapshot(tmp_path):
    p = tmp_path / "estado.db"
    st = Storage(str(p)); st.fechar()
    validar(p)
    p.write_bytes(b"corrompido")
    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        validar(p)
    p.write_bytes(b"")
    with pytest.raises(ValueError):
        validar(p)


def test_cli_once_retorna_erro_e_fecha_banco(monkeypatch, tmp_path):
    import main
    config = {"sites": [], "db": ":memory:"}
    st = Mock()
    monkeypatch.setattr(main, "carregar_config", lambda _: config)
    monkeypatch.setattr(main, "Storage", lambda _: st)
    monkeypatch.setattr(main.log, "configurar", lambda **k: None)
    monkeypatch.setattr("sys.argv", ["main.py", "--once", "--dry-run", "--relatorio", str(tmp_path / "relatorio.json")])
    def falha(*a, **k):
        raise RuntimeError("falha simulada")
    monkeypatch.setattr(main, "rodar_ciclo", falha)
    assert main.main() == 1
    st.fechar.assert_called_once()


def test_loop_tenta_proximo_ciclo_apos_falha(monkeypatch, tmp_path):
    import main
    st = Mock()
    monkeypatch.setattr(main, "carregar_config", lambda _: {"db": ":memory:"})
    monkeypatch.setattr(main, "Storage", lambda _: st)
    monkeypatch.setattr(main.log, "configurar", lambda **k: None)
    monkeypatch.setattr("sys.argv", ["main.py", "--loop", "--dry-run", "--relatorio", str(tmp_path / "relatorio.json")])
    ciclo = Mock(side_effect=[RuntimeError("falha"), KeyboardInterrupt()])
    monkeypatch.setattr(main, "rodar_ciclo", ciclo)
    sleep = Mock()
    monkeypatch.setattr(main.time, "sleep", sleep)
    assert main.main() is None
    assert ciclo.call_count == 2
    sleep.assert_called_once_with(180 * 60)
    st.fechar.assert_called_once()


def test_area_apos_preco_sem_confundir_valor_por_metro():
    from parser import parse_area_construida
    assert parse_area_construida("Casa R$ 500.000 100 m2 2 quartos") == 100
    assert parse_area_construida("Valor do m2 R$ 3.250 m2") is None


def test_snapshot_incompativel_rejeitado(tmp_path):
    p = tmp_path / "outro.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE outra (id INTEGER)")
    con.close()
    with pytest.raises(ValueError, match="incompatível"):
        validar(p)
