from types import SimpleNamespace

from tools.sondar_fontes import sondar

HTML = """<div class="thumbnail_one"><a class="property-card-link" href="/imovel/1">
<p class="property_card_address">Alphaville, Barueri-SP</p><div class="property_pricing">R$ 1.200.000</div>
<span class="thum_data">150 m²</span> 3 quartos</a></div>"""


class Sessao:
    headers = {}

    def get(self, url, **kwargs):
        if url.endswith("/robots.txt"):
            return SimpleNamespace(status_code=404, text="")
        return SimpleNamespace(text=HTML, encoding="utf-8", url=url, raise_for_status=lambda: None)


def test_sondagem_escolhe_seletores_que_extraem_preco_e_area():
    cfg = {"sites": [{"nome": "Praedium", "seletores": {
        "card": "div.thumbnail_one", "link": "a.property-card-link",
        "preco": ".property_pricing", "area": ".thum_data", "bairro": ".property_card_address"}}]}
    r = sondar({"nome": "X", "listagem_url": "https://x.test/imoveis/a-venda/barueri-sp?pagina={page}",
                "cidade": "Barueri"}, cfg, Sessao())
    assert r["status"] == "ok" and r["preset"] == "Praedium"
    assert r["com_preco_area"] == 1 and r["cidades"][0][0] == "Barueri"


def test_sondagem_sem_seletor_mostra_blocos_com_preco():
    cfg = {"sites": [{"nome": "Outro", "seletores": {"card": "article.nada"}}]}
    r = sondar({"nome": "X", "listagem_url": "https://x.test/venda"}, cfg, Sessao())
    assert r["status"] == "sem_seletor"
    assert r["blocos"][0][0].startswith("a.property-card-link")
