"""Descobre imobiliárias públicas por cidade e prepara uma fila de integração."""
import argparse
import json
import re
import time
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
import yaml
from bs4 import BeautifulSoup

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_ENDPOINTS = (
    OVERPASS_URL,
    "https://overpass.kumi.systems/api/interpreter",
)
UA = "ImovelBot/1.0 (descoberta de fontes imobiliarias)"
RELACOES_OSM = {
    "São Paulo": 298285, "Itanhaém": 298298, "Mongaguá": 297939,
    "Praia Grande": 298316, "Santos": 298442, "Peruíbe": 298456,
    "São Vicente": 297995, "Guarujá": 298463, "Bertioga": 297935,
    "Caraguatatuba": 298259, "Ubatuba": 298203, "São Sebastião": 298504,
    "Ilhabela": 298379,
}
CHAVES_SITE = ("website", "contact:website", "url")
TERMOS_VENDA = ("venda", "comprar", "imoveis", "imóveis", "properties")
TERMOS_LISTAGEM = ("/imoveis", "/imóveis", "/busca", "/buscar", "pesquisa-de-imoveis")
TERMOS_CONTEUDO = ("/blog", "/noticia", "/artigo", "/news")


def _url_site(tags):
    for chave in CHAVES_SITE:
        valor = (tags.get(chave) or "").strip()
        if valor:
            if not valor.startswith(("http://", "https://")):
                valor = "https://" + valor
            if urlsplit(valor).netloc:
                return valor
    return ""


def _dominio(url):
    return urlsplit(url).netloc.lower().removeprefix("www.")


def _consulta_cidade(cidade, session, endpoint=OVERPASS_URL):
    relacao = RELACOES_OSM.get(cidade)
    if not relacao:
        raise ValueError(f"Município sem relação OSM configurada: {cidade}")
    area = 3_600_000_000 + relacao
    consulta = f'''[out:json][timeout:45];
area({area})->.cidade;
(
  nwr["office"="estate_agent"](area.cidade);
  nwr["shop"="estate_agent"](area.cidade);
);
out tags center;'''
    resposta = session.post(endpoint, data={"data": consulta}, timeout=25)
    resposta.raise_for_status()
    return resposta.json().get("elements", [])


def _robots_permite(session, url):
    partes = urlsplit(url)
    resposta = session.get(f"{partes.scheme}://{partes.netloc}/robots.txt", timeout=15)
    if resposta.status_code != 200 or not resposta.text.strip():
        return True
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(resposta.text.splitlines())
    return rp.can_fetch(UA, url)


def _verificar_site(session, url):
    try:
        if not _robots_permite(session, url):
            return "bloqueado_robots", ""
        resposta = session.get(url, timeout=20, allow_redirects=True)
        resposta.raise_for_status()
        soup = BeautifulSoup(resposta.text, "lxml")
        candidatos = []
        for link in soup.select("a[href]"):
            href = urljoin(resposta.url, link.get("href"))
            texto = link.get_text(" ", strip=True).lower()
            href_norm = href.lower()
            if _dominio(href) != _dominio(resposta.url):
                continue
            pontos = sum(6 for t in TERMOS_LISTAGEM if t in href_norm)
            pontos += sum(3 for t in TERMOS_VENDA if t in href_norm)
            pontos += sum(2 for t in TERMOS_VENDA if t in texto)
            pontos -= sum(10 for t in TERMOS_CONTEUDO if t in href_norm)
            if re.search(r"/20\d{2}/\d{2}/", urlsplit(href_norm).path):
                pontos -= 10
            if pontos > 0:
                candidatos.append((pontos, href))
        candidatos.sort(key=lambda item: item[0], reverse=True)
        return "novo_site_permitido", candidatos[0][1] if candidatos else resposta.url
    except (requests.RequestException, ValueError) as exc:
        return "indisponivel", type(exc).__name__


def descobrir(config, session=None, endpoint=None, verificar=True, pausa=1):
    session = session or requests.Session()
    session.headers.update({"User-Agent": UA})
    dominios_atuais = {_dominio(s.get("base_url", "")) for s in config.get("sites", [])
                       if s.get("base_url")}
    achados, erros, vistos = [], [], set()
    endpoints = (endpoint,) if endpoint else OVERPASS_ENDPOINTS
    for indice, cidade in enumerate(config.get("cidades_monitoradas", [])):
        print(f"Consultando {cidade}...", flush=True)
        elementos = None
        ultimo_erro = None
        # Distribui as cidades entre instâncias e usa as demais como reserva.
        ordem = endpoints[indice % len(endpoints):] + endpoints[:indice % len(endpoints)]
        for tentativa, atual in enumerate(ordem):
            try:
                elementos = _consulta_cidade(cidade, session, atual)
                break
            except (requests.RequestException, ValueError) as exc:
                ultimo_erro = exc
                if tentativa + 1 < len(ordem):
                    time.sleep(3 * (tentativa + 1))
        if elementos is None:
            erros.append({"cidade": cidade, "erro": type(ultimo_erro).__name__})
            print(f"  consulta indisponível ({type(ultimo_erro).__name__})", flush=True)
            continue
        for elemento in elementos:
            tags = elemento.get("tags", {})
            nome = tags.get("name") or tags.get("brand") or "Imobiliária sem nome"
            site = _url_site(tags)
            chave = (cidade.casefold(), nome.casefold(), _dominio(site))
            if chave in vistos:
                continue
            vistos.add(chave)
            if not site:
                status, pagina = "sem_site", ""
            elif _dominio(site) in dominios_atuais:
                status, pagina = "ja_monitorada", ""
            elif verificar:
                status, pagina = _verificar_site(session, site)
            else:
                status, pagina = "novo_site_nao_verificado", ""
            achados.append({"nome": nome, "cidade": cidade, "site": site,
                            "pagina_candidata": pagina, "status": status,
                            "osm_tipo": elemento.get("type"), "osm_id": elemento.get("id")})
        if pausa:
            time.sleep(pausa)
        print(f"  {len(elementos)} cadastro(s) público(s)", flush=True)
    achados.sort(key=lambda x: (x["status"], x["cidade"], x["nome"].casefold()))
    return {"gerado_em": datetime.now(timezone.utc).isoformat(),
            "fonte": "OpenStreetMap/Overpass", "resultados": achados, "erros": erros}


def markdown(relatorio):
    resultados = relatorio["resultados"]
    novos = sum(r["status"] == "novo_site_permitido" for r in resultados)
    linhas = ["# Descoberta contínua de imobiliárias", "",
              f"Gerado em `{relatorio['gerado_em']}`. Encontradas **{len(resultados)}** empresas; "
              f"**{novos}** sites novos permitem verificação pública.", "",
              "| Cidade | Imobiliária | Situação | Site / página candidata |",
              "| --- | --- | --- | --- |"]
    for r in resultados:
        alvo = r["pagina_candidata"] or r["site"]
        link = f"[{alvo}]({alvo})" if alvo else "—"
        linhas.append(f"| {r['cidade']} | {r['nome'].replace('|', '/')} | `{r['status']}` | {link} |")
    if relatorio["erros"]:
        linhas += ["", "## Consultas que falharam", ""]
        linhas += [f"- {e['cidade']}: `{e['erro']}`" for e in relatorio["erros"]]
    linhas += ["", "Dados: © colaboradores do OpenStreetMap, consultados pela Overpass API.",
               "A descoberta não ativa coleta automaticamente; cada página candidata exige validação dos campos."]
    return "\n".join(linhas) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Descobre novas fontes imobiliárias públicas")
    ap.add_argument("--config", default="config.example.yaml")
    ap.add_argument("--json", default="fontes-descobertas.json")
    ap.add_argument("--markdown", default="fontes-descobertas.md")
    ap.add_argument("--sem-verificar-sites", action="store_true")
    args = ap.parse_args()
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    relatorio = descobrir(config, verificar=not args.sem_verificar_sites)
    Path(args.json).write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.markdown).write_text(markdown(relatorio), encoding="utf-8")
    print(f"Empresas encontradas: {len(relatorio['resultados'])}")
    print(f"Sites novos permitidos: {sum(r['status'] == 'novo_site_permitido' for r in relatorio['resultados'])}")
    if relatorio["erros"] and len(relatorio["erros"]) == len(config.get("cidades_monitoradas", [])):
        raise SystemExit("Todas as consultas de descoberta falharam.")


if __name__ == "__main__":
    main()
