from analyzer import Imovel, analisar, montar_regioes, regiao_de, chave_grupo

REGIOES = montar_regioes([
    {"nome": "Morumbi", "cidade": "São Paulo", "bairros": ["Real Parque", "Jardim Guedala"],
     "prefixos": ["Morumbi"]},
    {"nome": "Alphaville", "cidades": ["Barueri", "Santana de Parnaíba"], "prefixos": ["Alphaville"]},
])


def _casa(i, bairro, preco, cidade="São Paulo", tipo="casa", area=300.0):
    return Imovel(url=f"https://x/{bairro}/{i}", titulo=f"Casa {i}", bairro=bairro,
                  cidade=cidade, tipo=tipo, preco=preco, area=area, quartos=4)


def test_regiao_por_bairro_prefixo_e_varias_cidades():
    assert regiao_de("São Paulo", "Jd. Guedala", REGIOES) == "Morumbi"
    assert regiao_de("São Paulo", "Morumbi Sul", REGIOES) == "Morumbi"
    assert regiao_de("Santana de Parnaíba", "Alphaville 12", REGIOES) == "Alphaville"
    assert regiao_de("Barueri", "Alphaville 01", REGIOES) == "Alphaville"
    assert regiao_de("São Paulo", "Moema", REGIOES) == ""
    assert regiao_de("Cotia", "Alphaville", REGIOES) == ""


def test_sobrado_e_casa_sao_comparados_juntos():
    a = _casa(1, "Centro", 1, tipo="sobrado")
    b = _casa(2, "Centro", 1, tipo="casa")
    assert chave_grupo(a) == chave_grupo(b)


def _vizinhos():
    # 12 casas de mercado espalhadas pela região, nenhum bairro com 10 sozinho
    bairros = ["Morumbi", "Real Parque", "Jardim Guedala"]
    return [_casa(i, bairros[i % 3], 3_000_000 + i * 10_000) for i in range(12)]


def test_bairro_pequeno_usa_regiao_com_limiar_maior():
    alvo = _casa(99, "Real Parque", 1_300_000)       # ~57% abaixo
    ops = analisar(_vizinhos() + [alvo], min_amostra=10, limiar_desconto=0.4,
                   regioes=REGIOES, limiar_desconto_regiao=0.5)
    achado = [o for o in ops if o.url == alvo.url]
    assert achado and achado[0].base_regiao and "região Morumbi" in achado[0].criterio


def test_na_regiao_desconto_moderado_nao_basta():
    alvo = _casa(99, "Real Parque", 1_650_000)       # ~46%: passaria no bairro, não na região
    ops = analisar(_vizinhos() + [alvo], min_amostra=10, limiar_desconto=0.4,
                   regioes=REGIOES, limiar_desconto_regiao=0.5)
    assert alvo.url not in {o.url for o in ops}


def test_sem_regiao_nao_compara():
    alvo = _casa(99, "Real Parque", 1_300_000)
    ops = analisar(_vizinhos() + [alvo], min_amostra=10, limiar_desconto=0.4)
    assert alvo.url not in {o.url for o in ops}


def _raspar(html, monkeypatch, **cfg_extra):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from scraper import raspar_site
    sess = Mock(headers={})
    resp = SimpleNamespace(text=html, encoding="utf-8", raise_for_status=lambda: None)
    sess.get.return_value = resp
    monkeypatch.setattr("scraper.time.sleep", lambda _: None)
    cfg = dict(nome="t", base_url="https://x", listagem_url="https://x/v", cidade="São Paulo",
               seletores=dict(card="div.c", link="a"), **cfg_extra)
    return raspar_site(cfg, session=sess, respeitar_robots=False), resp


def test_bairro_pela_url_e_filtro_de_cidade_na_url(monkeypatch):
    html = """<div class='c'><a href='/imovel/R1/venda-casa-3-quartos-sao-paulo-parque-sao-domingos'>x</a>
    R$ 800.000 150 m²</div>
    <div class='c'><a href='/imovel/R2/venda-casa-2-quartos-osasco-centro'>x</a> R$ 500.000 90 m²</div>"""
    ims, _ = _raspar(html, monkeypatch, bairro_url_regex="sao-paulo-([a-z-]+)$",
                     url_deve_conter="sao-paulo")
    assert [im.bairro for im in ims] == ["parque sao domingos"]
    assert regiao_de("São Paulo", ims[0].bairro, montar_regioes([
        {"nome": "Pirituba", "cidade": "São Paulo", "prefixos": ["Parque São Domingos"]}])) == "Pirituba"


def test_encoding_forcado(monkeypatch):
    _, resp = _raspar("<div class='c'><a href='/1'>x</a></div>", monkeypatch, encoding="windows-1252")
    assert resp.encoding == "windows-1252"


def test_desconto_absurdo_vira_erro_de_cadastro():
    vizinhos = [_casa(i, "Morumbi", 3_000_000 + i * 10_000) for i in range(12)]
    alvo = _casa(99, "Morumbi", 400_000)        # ~87% abaixo: área de terreno, preço truncado...
    ops = analisar(vizinhos + [alvo], min_amostra=10, limiar_desconto=0.4, desconto_maximo=0.75)
    assert alvo.url not in {o.url for o in ops}
    ops = analisar(vizinhos + [alvo], min_amostra=10, limiar_desconto=0.4)
    assert alvo.url in {o.url for o in ops}
