from analyzer import Imovel
from notifier import formatar_alerta, _reais, _confianca


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


def test_confianca_por_amostra():
    assert "confiança boa" in _confianca(29)
    assert "razoável" in _confianca(10)
    assert "amostra pequena" in _confianca(4)
    assert "sem comparação" in _confianca(0)


def test_alerta_barato_explica_tudo():
    im = _im()
    im.preco_m2 = 5_000.0
    im.mediana_grupo = 8_000.0
    im.pct_abaixo = 0.375
    im.n_grupo = 29
    im.criterio = "casas de 208–432 m², 4–6 quartos, em Jardim Acapulco"
    im.score = 47.5
    msg = formatar_alerta(im)

    assert "Casa · Jardim Acapulco, Guarujá" in msg
    assert "R$ 1.600.000" in msg
    assert "320 m²" in msg and "5 quartos" in msg and "4 vagas" in msg
    assert "38% abaixo" in msg                      # 0.375 -> 38%
    assert "~R$ 8.000/m²" in msg
    assert "R$ 960.000 mais barato" in msg          # (8000-5000)*320
    assert "base de comparação: casas de 208" in msg
    assert "29 imóveis parecidos na base — confiança boa" in msg
    assert "Preço de <i>anúncio</i>" in msg
    assert "http://x/imovel-1" in msg
    assert "fonte: 7 Praias" in msg


def test_alerta_keyword_only():
    im = _im(descricao="Imóvel de espólio, aceito proposta")
    im.preco_m2 = 8_200.0
    im.mediana_grupo = None
    im.n_grupo = 3
    im.keywords = ["espolio", "aceito proposta"]
    im.score = 16.0
    msg = formatar_alerta(im)

    assert "sinais de venda abaixo" in msg
    assert "Sinais de venda rápida:</b> espólio, aceita proposta" in msg
    assert "amostra pequena" in msg
    assert "% abaixo" not in msg                    # não afirma desconto que não calculou


def test_alerta_escapa_html_e_aguenta_campos_faltando():
    im = _im(titulo="Casa <b>promo</b>", area=None, quartos=None, vagas=None, tipo="")
    im.preco_m2 = None
    msg = formatar_alerta(im)                       # não pode lançar

    assert "<b>promo</b>" not in msg                # título não vira tag
    assert "&lt;b&gt;promo&lt;/b&gt;" in msg
    assert "Imóvel · Jardim Acapulco, Guarujá" in msg
    assert "R$ 1.600.000" in msg
