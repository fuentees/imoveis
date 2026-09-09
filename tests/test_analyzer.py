import pytest

from analyzer import (Imovel, Comp, analisar, _dedupe, chave_grupo, canon_bairro,
                      comps_do_historico, detectar_keywords)


def mk(url="http://x/1", titulo="Apartamento", desc="", bairro="Jardim Acapulco",
       cidade="Guaruja", tipo="apartamento", preco=None, area=None, quartos=3):
    return Imovel(url=url, titulo=titulo, descricao=desc, bairro=bairro,
                  cidade=cidade, tipo=tipo, preco=preco, area=area, quartos=quartos)


# ------------------------------------------------ canon_bairro / chave_grupo
@pytest.mark.parametrize("entrada, saida", [
    ("Jd Acapulco", "jardim acapulco"),
    ("JARDIM ACAPULCO", "jardim acapulco"),
    ("Jd. Acapulco", "jardim acapulco"),
    ("Pq. Balneário dos Prazeres", "parque balneario dos prazeres"),
    ("Vl. Santa Rosa", "vila santa rosa"),
])
def test_canon_bairro(entrada, saida):
    assert canon_bairro(entrada) == saida


def test_chave_grupo_junta_abreviacoes():
    a = mk(bairro="Jd Acapulco", cidade="Guarujá", tipo="Casa")
    b = mk(bairro="Jardim Acapulco", cidade="guaruja", tipo="casa")
    assert chave_grupo(a) == chave_grupo(b)


# ------------------------------------------------ dedupe
def test_dedupe_url_repetida():
    ims = [mk(url="http://x/a"), mk(url="http://x/a/")]
    assert len(_dedupe(ims)) == 1


def test_dedupe_reanuncio_mesmo_titulo():
    ims = [
        mk(url="http://x/CA1", titulo="Casa espólio Jardim Acapulco", preco=2_000_000, area=300),
        mk(url="http://x/CA2", titulo="Casa espólio Jardim Acapulco", preco=2_000_000, area=300),
    ]
    assert len(_dedupe(ims)) == 1


def test_dedupe_nao_junta_unidades_distintas():
    # mesmo prédio, mesma metragem e preço, mas apartamentos diferentes
    ims = [
        mk(url="http://x/301", titulo="Apartamento 301 Edificio Sol", preco=800_000, area=90),
        mk(url="http://x/502", titulo="Apartamento 502 Edificio Sol", preco=800_000, area=90),
    ]
    assert len(_dedupe(ims)) == 2


# ------------------------------------------------ analisar
def _grupo_normal(preco_m2=8000.0):
    """5 apartamentos comparáveis, todos ~preco_m2, áreas em torno de 350 m²."""
    areas = [330, 345, 355, 360, 370]
    return [mk(url=f"http://x/n{i}", area=a, preco=a * preco_m2, quartos=3)
            for i, a in enumerate(areas)]


def test_analisar_pega_pechincha_sem_efeito_degrau():
    # a 352 m² cairia numa faixa fixa diferente das de 330-345 m²;
    # com janela relativa ela é comparada com o grupo todo.
    normais = _grupo_normal(8000.0)
    steal = mk(url="http://x/steal", area=352, preco=352 * 4800, quartos=3)
    ops = analisar(normais + [steal], min_amostra=4, limiar_desconto=0.30)
    urls = [o.url for o in ops]
    assert "http://x/steal" in urls
    assert not any(u.startswith("http://x/n") for u in urls)   # normais não alertam


def test_analisar_usa_historico_para_amostra():
    atuais = [
        mk(url="http://x/y1", area=100, preco=100 * 8000, quartos=2),
        mk(url="http://x/steal", area=100, preco=100 * 4000, quartos=2),
    ]
    g = chave_grupo(atuais[0])
    hist = [Comp(g, 100.0, 2, 8000.0) for _ in range(3)]

    sem = analisar(list(atuais), min_amostra=4, limiar_desconto=0.30)
    assert "http://x/steal" not in [o.url for o in sem]        # só 2 comparáveis

    com = analisar(list(atuais), min_amostra=4, limiar_desconto=0.30, historico=hist)
    assert "http://x/steal" in [o.url for o in com]            # 2 + 3 do histórico


def test_analisar_historico_nao_reconta_imovel_ja_na_raspagem():
    # áreas levemente distintas p/ o dedupe não colapsar (mesmo título/preço).
    atuais = [mk(url=f"http://x/n{i}", titulo=f"Apto {i}", area=a, preco=a * 8000, quartos=2)
              for i, a in enumerate([95, 98, 102, 105])]
    atuais.append(mk(url="http://x/steal", titulo="Apto Z", area=100, preco=100 * 4000, quartos=2))
    g = chave_grupo(atuais[0])
    # histórico traz os MESMOS imóveis (mesma url) com preço/m² defasado e absurdo;
    # se fossem recontabilizados, a mediana despencaria e a pechincha sumiria.
    hist = [Comp(g, 100.0, 2, 1000.0, im.url) for im in atuais]
    ops = analisar(list(atuais), min_amostra=4, limiar_desconto=0.30, historico=hist)
    op = next((o for o in ops if o.url == "http://x/steal"), None)
    assert op is not None
    assert op.mediana_grupo == 8000.0


def test_analisar_keyword_dispara_sem_ser_barato():
    im = mk(url="http://x/kw", desc="Vende-se por motivo de espólio, documentação ok",
            area=120, preco=120 * 8000, quartos=3)
    ops = analisar([im], min_amostra=4, limiar_desconto=0.30)
    assert [o.url for o in ops] == ["http://x/kw"]
    assert "espolio" in ops[0].keywords


def test_analisar_filtro_de_sanidade_descarta_preco_m2_absurdo():
    im = mk(url="http://x/bug", desc="espólio inventário urgente",
            area=50, preco=10_000_000, quartos=2)          # 200.000/m²
    ops = analisar([im], min_amostra=4, preco_m2_max=60_000)
    assert ops == []


def test_analisar_exigir_keyword():
    normais = _grupo_normal(8000.0)
    steal = mk(url="http://x/steal", area=352, preco=352 * 4800, quartos=3, desc="")
    ops = analisar(normais + [steal], min_amostra=4, limiar_desconto=0.30,
                   exigir_keyword=True)
    assert ops == []                                       # barato mas sem keyword


# ------------------------------------------------ histórico / keywords
def test_comps_do_historico():
    rows = [
        ("http://x/1", "Guaruja", "Jardim Acapulco", "casa", 400.0, 4, 9000.0),
        ("http://x/2", "x", None, None, None, None, None),  # descartada (sem área)
    ]
    comps = comps_do_historico(rows)
    assert len(comps) == 1
    assert comps[0].url == "http://x/1"
    assert comps[0].grupo == chave_grupo(mk(bairro="Jd Acapulco", cidade="Guaruja", tipo="casa"))


def test_detectar_keywords():
    im = mk(desc="Imóvel de INVENTÁRIO, aceito proposta")
    kws = detectar_keywords(im)
    assert "inventario" in kws and "aceito proposta" in kws
