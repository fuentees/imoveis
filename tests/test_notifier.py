from analyzer import Imovel
from notifier import formatar_alerta, _reais, _confianca, _faixa


def _im(**kw):
    d = dict(url="http://x/imovel-1", titulo="Casa boa", descricao="", bairro="Jardim Acapulco",
             cidade="Guarujá", tipo="casa", preco=1_600_000.0, area=320.0, quartos=5, vagas=4,
             fonte="7 Praias")
    d.update(kw)
    return Imovel(**d)


def test_reais_formato_br():
    assert _reais(1_600_000) == "R$ 1.600.000"
    assert _reais(5_000) == "R$ 5.000"
    assert _reais(0) == "—"
    assert _reais(None) == "—"


def test_faixa():
    assert _faixa(7_000, 9_500) == "R$ 7.000–9.500/m²"
    assert _faixa(None, 9_500) == ""


def test_confianca_por_amostra():
    assert "confiança boa" in _confianca(29)
    assert "razoável" in _confianca(10)
    assert "amostra pequena" in _confianca(4)
    assert "sem comparação" in _confianca(0)


def test_manchete_e_a_diferenca_de_valor():
    im = _im()
    im.preco_m2 = 5_000.0
    im.mediana_grupo = 8_000.0
    im.faixa_lo, im.faixa_hi = 7_000.0, 9_500.0
    im.pct_abaixo = 0.375
    im.n_grupo = 29
    im.criterio = "casas de 208–432 m², 4–6 quartos, em Jardim Acapulco"
    im.score = 48.0
    msg = formatar_alerta(im)

    # a diferença é a PRIMEIRA linha
    primeira = msg.splitlines()[0]
    assert "38% ABAIXO" in primeira
    assert "R$ 960.000" in primeira            # (8000-5000)*320

    assert "este imóvel: <b>R$ 5.000/m²</b>" in msg
    assert "R$ 7.000–9.500/m²" in msg
    assert "base: 29 imóveis parecidos" in msg
    assert "gap grande" not in msg             # 38% < 45%
    # o imóvel e o resto continuam aparecendo
    assert "Casa · Jardim Acapulco, Guarujá" in msg
    assert "R$ 1.600.000" in msg
    assert "320 m²" in msg and "5 quartos" in msg and "4 vagas" in msg
    assert "confiança boa (29 comparáveis)" in msg
    assert "não de venda" in msg
    assert "http://x/imovel-1" in msg


def test_tag_gap_grande_acima_de_45pct():
    im = _im()
    im.preco_m2 = 4_000.0
    im.mediana_grupo = 8_000.0
    im.faixa_lo, im.faixa_hi = 7_000.0, 9_500.0
    im.pct_abaixo = 0.50
    im.n_grupo = 20
    im.criterio = "casas ..."
    im.score = 60.0
    msg = formatar_alerta(im)
    assert "50% ABAIXO" in msg.splitlines()[0]
    assert "gap grande" in msg
    assert "reforma pesada" in msg


def test_keyword_only_vira_manchete_quando_nao_ha_gap():
    im = _im(descricao="Imóvel de espólio, aceito proposta")
    im.preco_m2 = 8_200.0
    im.mediana_grupo = None
    im.n_grupo = 3
    im.keywords = ["espolio", "aceito proposta"]
    im.score = 16.0
    msg = formatar_alerta(im)

    assert msg.splitlines()[0].startswith("🔑")
    assert "SINAIS DE VENDA RÁPIDA</b>: espólio, aceita proposta" in msg
    assert "preço não comparável" in msg
    assert "% ABAIXO" not in msg


def test_keyword_de_apoio_aparece_junto_do_gap():
    im = _im(descricao="espólio")
    im.preco_m2 = 5_000.0
    im.mediana_grupo = 8_000.0
    im.faixa_lo, im.faixa_hi = 7_000.0, 9_500.0
    im.pct_abaixo = 0.375
    im.n_grupo = 20
    im.criterio = "casas ..."
    im.keywords = ["espolio"]
    im.score = 55.0
    msg = formatar_alerta(im)
    assert "38% ABAIXO" in msg.splitlines()[0]   # gap continua sendo a manchete
    assert "🔑 ainda: espólio" in msg


def test_escapa_html_e_aguenta_campos_faltando():
    im = _im(titulo="Casa <b>promo</b>", area=None, quartos=None, vagas=None, tipo="")
    im.preco_m2 = None
    im.mediana_grupo = None
    msg = formatar_alerta(im)                     # não pode lançar
    assert "<b>promo</b>" not in msg
    assert "&lt;b&gt;promo&lt;/b&gt;" in msg
    assert "Imóvel · Jardim Acapulco, Guarujá" in msg
    assert "R$ 1.600.000" in msg
