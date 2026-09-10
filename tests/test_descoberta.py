from types import SimpleNamespace

from tools.descobrir_fontes import _url_site, descobrir, markdown


class FakeSession:
    def __init__(self):
        self.headers = {}

    def post(self, *args, **kwargs):
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"elements": [
            {"type": "node", "id": 1, "tags": {"name": "Nova Imóveis", "website": "nova.test"}},
            {"type": "node", "id": 2, "tags": {"name": "Sem Site"}},
        ]})

    def get(self, url, **kwargs):
        if url.endswith("/robots.txt"):
            return SimpleNamespace(status_code=404, text="")
        return SimpleNamespace(url="https://nova.test", text=(
            '<a href="/blog/quando-comprar-imovel">Comprar imóvel</a>'
            '<a href="/imoveis/venda">Comprar imóveis</a>'),
                               raise_for_status=lambda: None)


def test_normaliza_site_sem_esquema():
    assert _url_site({"contact:website": "exemplo.com.br"}) == "https://exemplo.com.br"


def test_descobre_e_prepara_pagina_candidata():
    cfg = {"cidades_monitoradas": ["Santos"], "sites": []}
    relatorio = descobrir(cfg, session=FakeSession(), pausa=0)
    novo = next(r for r in relatorio["resultados"] if r["nome"] == "Nova Imóveis")
    assert novo["status"] == "novo_site_permitido"
    assert novo["pagina_candidata"] == "https://nova.test/imoveis/venda"
    assert "Nova Imóveis" in markdown(relatorio)


def test_reconhece_dominio_ja_monitorado():
    cfg = {"cidades_monitoradas": ["Santos"],
           "sites": [{"base_url": "https://www.nova.test"}]}
    relatorio = descobrir(cfg, session=FakeSession(), pausa=0)
    novo = next(r for r in relatorio["resultados"] if r["nome"] == "Nova Imóveis")
    assert novo["status"] == "ja_monitorada"


def test_tenta_endpoint_reserva(monkeypatch):
    chamadas = []
    original = FakeSession().post

    def post(url, *args, **kwargs):
        chamadas.append(url)
        if len(chamadas) == 1:
            import requests
            raise requests.HTTPError("indisponível")
        return original(url, *args, **kwargs)

    sessao = FakeSession()
    sessao.post = post
    monkeypatch.setattr("tools.descobrir_fontes.time.sleep", lambda _: None)
    relatorio = descobrir({"cidades_monitoradas": ["Santos"], "sites": []},
                          session=sessao, verificar=False, pausa=0)
    assert len(chamadas) == 2
    assert not relatorio["erros"]
