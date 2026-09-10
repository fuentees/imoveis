import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import yaml
from parser import parse_local, normalizar_texto
from scraper import raspar_site, raspar_todos
from main import executar_ciclo
from tools.resumo_ciclo import formatar

CIDADES = ["São Paulo", "Itanhaém", "Mongaguá", "Praia Grande", "Santos", "Peruíbe", "São Vicente", "Guarujá", "Bertioga", "Caraguatatuba", "Ubatuba", "São Sebastião", "Ilhabela"]


@pytest.mark.parametrize("cidade", CIDADES)
def test_localizacao_todas_cidades(cidade):
    assert parse_local(f"Centro, {cidade}-SP") == (cidade, "Centro")


def test_config_cobre_todas_as_cidades():
    cfg = yaml.safe_load(Path("config.example.yaml").read_text(encoding="utf-8"))
    assert set(cfg["cidades_monitoradas"]) == set(CIDADES)
    ativas = [s for s in cfg["sites"] if s.get("ativo", True)]
    cidades = {normalizar_texto(s.get("cidade", "")) for s in ativas}
    assert {normalizar_texto(c) for c in CIDADES} <= cidades
    assert len({s["nome"] for s in ativas}) == len(ativas)
    assert all(s.get("respeitar_robots", True) for s in ativas)


def test_cidade_explicita_e_filtro_de_recomendacoes(monkeypatch):
    html = """<article><a href='/1'>Apartamento</a><p class='cidade'>Santos / SP</p><p class='bairro'>Centro</p>R$ 500.000 100 m2 2 quartos</article>
    <article><a href='/2'>Apartamento</a><p class='cidade'>Campinas / SP</p><p class='bairro'>Centro</p>R$ 600.000 100 m2 2 quartos</article>"""
    sess = Mock(headers={})
    sess.get.return_value = SimpleNamespace(text=html, encoding="utf-8", raise_for_status=lambda: None)
    cfg = dict(nome="teste", base_url="https://x", listagem_url="https://x/venda", cidade_auto=True,
               cidades_permitidas=["Santos"], seletores=dict(card="article", cidade=".cidade", bairro=".bairro"))
    monkeypatch.setattr("scraper.time.sleep", lambda _: None)
    diag = {}
    ims = raspar_site(cfg, session=sess, respeitar_robots=False, diagnostico=diag)
    assert len(ims) == 1 and ims[0].cidade == "Santos" and ims[0].bairro == "Centro"
    assert diag["paginas"] == 1


def test_relatorio_preserva_falha_de_coleta(monkeypatch, tmp_path):
    def falhar(config, st, tg, dry, paginas, relatorio):
        relatorio["fontes"] = [{"nome": "X", "status": "erro_http"}]
        raise RuntimeError("Coleta indisponível")
    monkeypatch.setattr("main.rodar_ciclo", falhar)
    destino = tmp_path / "ciclo.json"
    args = SimpleNamespace(dry_run=True, max_paginas=1, relatorio=str(destino))
    with pytest.raises(RuntimeError):
        executar_ciclo({}, None, None, args)
    dados = json.loads(destino.read_text(encoding="utf-8"))
    assert dados["erro"] == "Coleta indisponível"
    assert dados["fontes"][0]["status"] == "erro_http"
    assert "Coleta indisponível" in formatar(dados)


def test_resumo_distingue_sem_alertas_de_sem_coleta():
    texto = formatar(dict(anuncios=300, oportunidades=0, enviados=0,
                          por_cidade={"São Paulo": 300},
                          fontes=[dict(nome="Teste",status="limite_paginas",paginas=20,anuncios=300)]))
    assert "**300**" in texto and "São Paulo | 300" in texto
    assert "limite_paginas" in texto


def test_portal_usa_atributos_e_local_sem_uf(monkeypatch):
    html = """<a class='property-card__body' href='/imovel/teste'>
    <p class='property-card__location'>Centro, Mongaguá</p>
    <h3 class='property-card__title'>Apartamento com 2 quartos e 74 m²</h3>
    <span class='property-card__attr' title='74 m²'>74 m²</span>
    <span class='property-card__attr' title='2 quartos'>2</span>
    <span class='property-card__attr' title='1 vaga'>1</span>
    <span class='property-card__price'>R$ 490.000</span></a>"""
    cfg = yaml.safe_load(Path("config.example.yaml").read_text(encoding="utf-8"))
    site = next(s for s in cfg["sites"] if s["nome"] == "Chavee - Mongaguá")
    sess = Mock(headers={})
    sess.get.return_value = SimpleNamespace(text=html, encoding="utf-8", raise_for_status=lambda: None)
    monkeypatch.setattr("scraper.time.sleep", lambda _: None)
    ims = raspar_site(site, max_paginas=1, session=sess, respeitar_robots=False)
    assert len(ims) == 1
    im = ims[0]
    assert (im.cidade, im.bairro, im.preco, im.area, im.quartos, im.vagas) == ("Mongaguá", "Centro", 490000, 74, 2, 1)


def test_relatorio_unifica_nome_das_cidades(monkeypatch):
    from analyzer import Imovel
    def coleta(*a, **k):
        return [Imovel(url="https://x/1",cidade="SAO PAULO",preco=500000,area=100)]
    monkeypatch.setattr("scraper.raspar_site", coleta)
    relatorio = {}
    ims = raspar_todos({"cidades_monitoradas": ["São Paulo"], "sites": [{"nome": "teste", "listagem_url": "https://x/lista"}]}, relatorio=relatorio)
    assert ims[0].cidade == "São Paulo"
    assert relatorio["fontes"][0]["anuncios"] == 1
