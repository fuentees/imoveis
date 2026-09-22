"""Sonda páginas candidatas antes de ativá-las no config.

Para cada candidata: confere o robots.txt, baixa a 1ª página uma única vez e
testa os conjuntos de seletores já usados no config (Praedium, Kenlo, Chavee...).
Quando nenhum conjunto funciona, mostra os blocos repetidos que têm preço e
link, para facilitar escrever seletores novos. Nada é ativado automaticamente.
"""
import argparse
import collections
import json
import sys
import time
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper import DEFAULT_UA, _baixar, _monta_url_pagina, _robots_permite, raspar_site  # noqa: E402

KENLO = {"card": "a.card-with-buttons", "link": "a"}


class SessaoCache:
    """Sessão que devolve a mesma resposta para a mesma URL (1 download por página)."""

    def __init__(self, sess):
        self.sess, self.headers, self.cache = sess, sess.headers, {}

    def get(self, url, **kwargs):
        if url not in self.cache:
            self.cache[url] = self.sess.get(url, **kwargs)
        return self.cache[url]


def presets(config):
    vistos, saida = set(), [("kenlo", KENLO)]
    for site in config.get("sites", []):
        sel = site.get("seletores") or {}
        if not sel.get("card"):
            continue
        chave = json.dumps(sel, sort_keys=True, ensure_ascii=False)
        if chave not in vistos:
            vistos.add(chave)
            saida.append((site["nome"], sel))
    return saida


def _classe(node):
    classes = ".".join((node.get("class") or [])[:2])
    return f"{node.name}.{classes}" if classes else node.name


def impressao_digital(html):
    """Blocos repetidos que contêm preço (R$) e um link: candidatos a card."""
    soup = BeautifulSoup(html, "lxml")
    contagem = collections.Counter()
    exemplo = {}
    for texto in soup.find_all(string=lambda s: s and "R$" in s):
        node = texto.parent
        for _ in range(8):
            if node is None or node.name in ("body", "html"):
                break
            if node.name == "a" and node.get("href") or node.select_one("a[href]"):
                chave = _classe(node)
                contagem[chave] += 1
                exemplo.setdefault(chave, str(node)[:2500])
                break
            node = node.parent
    paginacao = sorted({a["href"] for a in soup.select("a[href]")
                        if any(t in a["href"].lower() for t in ("pagina", "page", "pag/"))})[:6]
    links = collections.Counter(
        a["href"] for a in soup.select("a[href]")
        if any(t in a["href"].lower() for t in ("venda", "comprar", "/imoveis", "busca"))
        and "/imovel/" not in a["href"].lower())
    titulo = soup.title.get_text(strip=True) if soup.title else ""
    return {"titulo": titulo, "blocos": contagem.most_common(5),
            "exemplo": exemplo.get(contagem.most_common(1)[0][0]) if contagem else "",
            "paginacao": paginacao, "links_venda": [h for h, _ in links.most_common(8)]}


def sondar(candidato, config, sess):
    url = _monta_url_pagina(candidato["listagem_url"], 1, candidato.get("pular_param_pagina_1", True))
    res = {"nome": candidato["nome"], "url": url, "cidade": candidato.get("cidade", "")}
    try:
        if not _robots_permite(sess, url, DEFAULT_UA):
            res["status"] = "bloqueado_robots"
            return res
        resposta = _baixar(sess, url, 20, True, tentativas=2)
    except Exception as exc:
        res.update(status="erro_http", erro=f"{type(exc).__name__}: {exc}"[:200])
        return res
    cache = SessaoCache(sess)
    cache.cache[url] = resposta
    testes = [("candidato", candidato["seletores"])] if candidato.get("seletores") else []
    testes += presets(config)
    melhor = None
    for nome, sel in testes:
        cfg = {"cidade_auto": True, "detalhe": False, **candidato}
        cfg.update(base_url=candidato.get("base_url") or url, listagem_url=url,
                   paginas=1, seletores=sel)
        diag = {}
        try:
            ims = raspar_site(cfg, delay=0, session=cache, respeitar_robots=False, diagnostico=diag)
        except Exception:
            continue
        uteis = sum(bool(im.preco and im.area) for im in ims)
        placar = (uteis, len(ims))
        if ims and (melhor is None or placar > melhor["placar"]):
            melhor = {"placar": placar, "preset": nome, "seletores": sel, "anuncios": len(ims),
                      "com_preco_area": uteis,
                      "cidades": collections.Counter(im.cidade for im in ims).most_common(4),
                      "amostra": [dict(titulo=im.titulo[:60], preco=im.preco, area=im.area,
                                       bairro=im.bairro, cidade=im.cidade, url=im.url)
                                  for im in ims[:2]]}
    if melhor:
        melhor.pop("placar")
        res.update(status="ok", **melhor)
        if candidato.get("detalhar"):
            res.update(impressao_digital(resposta.text))
    else:
        res.update(status="sem_seletor", **impressao_digital(resposta.text))
    return res


def markdown(resultados):
    linhas = ["# Sondagem de fontes candidatas", "",
              "| Fonte | Cidade | Situação | Anúncios | Preço+área | Seletores |",
              "| --- | --- | --- | ---: | ---: | --- |"]
    for r in resultados:
        linhas.append(f"| [{r['nome']}]({r['url']}) | {r['cidade']} | `{r['status']}` | "
                      f"{r.get('anuncios', 0)} | {r.get('com_preco_area', 0)} | {r.get('preset', '')} |")
    return "\n".join(linhas) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Sonda fontes candidatas sem ativá-las")
    ap.add_argument("--candidatas", default="tools/fontes_candidatas.yaml")
    ap.add_argument("--config", default="config.example.yaml")
    ap.add_argument("--json", default="fontes-sondadas.json")
    ap.add_argument("--markdown", default="fontes-sondadas.md")
    ap.add_argument("--pausa", type=float, default=1.0)
    args = ap.parse_args()
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    candidatas = yaml.safe_load(Path(args.candidatas).read_text(encoding="utf-8")) or []
    sess = requests.Session()
    sess.headers.update({"User-Agent": DEFAULT_UA})
    resultados = []
    for candidato in candidatas:
        r = sondar(candidato, config, sess)
        resultados.append(r)
        print(json.dumps(r, ensure_ascii=False, default=str), flush=True)
        time.sleep(args.pausa)
    Path(args.json).write_text(json.dumps(resultados, ensure_ascii=False, indent=2, default=str),
                               encoding="utf-8")
    Path(args.markdown).write_text(markdown(resultados), encoding="utf-8")
    print(f"Sondadas: {len(resultados)}; ok: {sum(r['status'] == 'ok' for r in resultados)}")


if __name__ == "__main__":
    main()
