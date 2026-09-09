import pytest

from scraper import _monta_url_pagina, raspar_site


@pytest.mark.parametrize("tmpl, p, pular, esperado", [
    ("http://x/lista", 3, False, "http://x/lista"),                       # sem {page}
    ("http://x/?pagina={page}", 2, False, "http://x/?pagina=2"),
    ("http://x/?pagina={page}", 1, True, "http://x/"),                    # 1ª pelada
    ("http://x/a?negotiation=1&type=1&page={page}", 1, True,
     "http://x/a?negotiation=1&type=1"),
    ("http://x/imoveis/pagina-{page}/", 1, True, "http://x/imoveis/"),
])
def test_monta_url_pagina(tmpl, p, pular, esperado):
    assert _monta_url_pagina(tmpl, p, pular) == esperado


def test_raspar_site_sem_card_nao_quebra():
    cfg = {"nome": "teste", "base_url": "http://x", "listagem_url": "http://x",
           "seletores": {"card": ""}}
    assert raspar_site(cfg) == []


def test_raspar_site_sem_seletores_nao_quebra():
    cfg = {"nome": "teste", "base_url": "http://x", "listagem_url": "http://x"}
    assert raspar_site(cfg) == []
