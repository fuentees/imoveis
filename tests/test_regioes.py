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
