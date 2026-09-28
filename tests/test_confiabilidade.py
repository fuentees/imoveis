from collections import Counter
from types import SimpleNamespace

import scraper
from main import _selecionar_diverso, validar_config, verificar_saude_fontes
from scraper import _rotacionar_plataformas, raspar_todos
from storage import Storage


def _site(nome, plataforma=None, paginas=20):
    return dict(nome=nome, base_url="https://x", listagem_url=f"https://x/{nome}?p={{page}}",
                paginas=paginas, plataforma=plataforma, seletores={"card": "div"})


def _config(sites, cota=60):
    return {"scraper": {"delay_segundos": 0, "paginas_por_plataforma": {"praedium": cota}},
            "sites": sites}


def test_rodizio_muda_quem_vem_primeiro_na_plataforma():
    sites = [_site("a", "p"), _site("x"), _site("b", "p"), _site("c", "p")]
    nomes = lambda r: [s["nome"] for s in _rotacionar_plataformas(sites, r)]
    assert nomes(0) == ["a", "x", "b", "c"]
    assert nomes(1) == ["b", "x", "c", "a"]
    assert nomes(3) == nomes(0)


def test_cota_dividida_e_sobra_passa_para_os_proximos(monkeypatch):
    pedidos = {}

    def falso(site, max_paginas=None, diagnostico=None, **kw):
        usadas = 2 if site["nome"] == "curto" else (max_paginas or 20)
        pedidos[site["nome"]] = max_paginas
        diagnostico.update(status="ok", paginas=usadas, erros=[])
        return [SimpleNamespace(cidade="", preco=1, area=1)]

    monkeypatch.setattr(scraper, "raspar_site", falso)
    sites = [_site("curto", "praedium"), _site("b", "praedium"), _site("c", "praedium"), _site("livre")]
    raspar_todos(_config(sites, cota=30), rodada=0)
    # 30 páginas para 3 sites: 10 cada; "curto" usou só 2 e a sobra foi dividida
    assert pedidos == {"curto": 10, "b": 14, "c": 14, "livre": None}


def test_bloqueio_para_a_plataforma_e_registra_adiados(monkeypatch):
    chamados = []

    def falso(site, max_paginas=None, diagnostico=None, **kw):
        chamados.append(site["nome"])
        if site["nome"] == "b":
            diagnostico.update(status="erro_http", paginas=1,
                               erros=["405 Client Error: Method Not Allowed"])
        else:
            diagnostico.update(status="ok", paginas=1, erros=[])
        return [SimpleNamespace(cidade="", preco=1, area=1)]

    monkeypatch.setattr(scraper, "raspar_site", falso)
    sites = [_site("a", "praedium"), _site("b", "praedium"), _site("c", "praedium"), _site("livre")]
    rel = {}
    raspar_todos(_config(sites), relatorio=rel, rodada=0)
    assert chamados == ["a", "b", "livre"]
    status = {f["nome"]: f["status"] for f in rel["fontes"]}
    assert status["c"] == "adiado_bloqueio"


class TelegramFalso:
    def __init__(self):
        self.mensagens = []

    def enviar(self, texto):
        self.mensagens.append(texto)
        return True


def test_avisa_fonte_parada_uma_vez_e_quando_volta(tmp_path):
    st = Storage(str(tmp_path / "t.db"))
    tg = TelegramFalso()
    parada = {"nome": "Imperial", "status": "erro_http", "anuncios": 0, "erros": ["405 Client Error"]}
    viva = {"nome": "Angelo", "status": "ok", "anuncios": 20}
    for _ in range(2):
        verificar_saude_fontes([parada, viva], st, tg, minimo_falhas=3)
    assert tg.mensagens == []
    verificar_saude_fontes([parada, viva], st, tg, minimo_falhas=3)
    assert len(tg.mensagens) == 1 and "Imperial" in tg.mensagens[0] and "405" in tg.mensagens[0]
    assert "Angelo" not in tg.mensagens[0]
    verificar_saude_fontes([parada, viva], st, tg, minimo_falhas=3)
    assert len(tg.mensagens) == 1          # não repete o aviso
    verificar_saude_fontes([dict(parada, anuncios=5, status="ok"), viva], st, tg, minimo_falhas=3)
    assert len(tg.mensagens) == 2 and "Voltaram" in tg.mensagens[1]
    st.fechar()


def test_limite_diario_por_portal():
    ims = [SimpleNamespace(url=f"https://chavee.com.br/{i}", fonte="Chavee", cidade=f"c{i}")
           for i in range(3)]
    ims.append(SimpleNamespace(url="https://outra.com.br/1", fonte="Outra", cidade="z"))
    ja = Counter({"chavee.com.br": 3})
    fila = _selecionar_diverso(ims, 10, max_dominio=2, max_cidade=3,
                               max_dominio_dia=4, enviados_24h=ja)
    assert [im.url for im in fila] == ["https://chavee.com.br/0", "https://outra.com.br/1"]


def test_config_de_exemplo_valida_cotas():
    import yaml
    cfg = yaml.safe_load(open("config.example.yaml", encoding="utf-8"))
    validar_config(cfg)
    cfg["scraper"]["paginas_por_plataforma"] = {"praedium": 0}
    try:
        validar_config(cfg)
    except ValueError:
        return
    raise AssertionError("cota zero deveria ser rejeitada")


def _im(tipo, titulo, descricao=""):
    return SimpleNamespace(tipo=tipo, titulo=titulo, descricao=descricao)


def test_so_casas_prontas_geram_alerta():
    from main import _alertavel
    tipos = {"casa", "sobrado"}
    assert _alertavel(_im("casa", "Casa com 3 quartos", "Casa em terreno de 500 m²"), tipos)
    assert _alertavel(_im("sobrado", "Sobrado em condomínio"), tipos)
    assert not _alertavel(_im("apartamento", "Apartamento com 2 quartos"), tipos)
    # classificado errado como casa, mas o título entrega
    assert not _alertavel(_im("casa", "Terreno/Lote à Venda com 700m²"), tipos)
    assert not _alertavel(_im("casa", "Casa nova", "Casa na planta, entrega prevista em 2027"), tipos)
    assert not _alertavel(_im("casa", "Casa em construção no Jardim Acapulco"), tipos)


def test_tipo_vem_do_titulo_antes_do_card(monkeypatch):
    from unittest.mock import Mock
    html = """<div class='c'><a href='/1'><h2>Terreno/Lote à Venda com 700m²</h2></a>
    Ótimo para construir sua casa. R$ 300.000 700 m²</div>"""
    sess = Mock(headers={})
    sess.get.return_value = SimpleNamespace(text=html, encoding="utf-8", raise_for_status=lambda: None)
    cfg = dict(nome="t", base_url="https://x", listagem_url="https://x/v", cidade="Bertioga",
               seletores=dict(card="div.c", titulo="h2"))
    monkeypatch.setattr("scraper.time.sleep", lambda _: None)
    ims = scraper.raspar_site(cfg, session=sess, respeitar_robots=False)
    assert ims[0].tipo == "terreno"
