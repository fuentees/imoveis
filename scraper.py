"""
scraper.py
Raspador GENÉRICO e configurável. Cada site (imobiliária) é descrito no
config.yaml com seus próprios seletores CSS. Assim você adiciona uma nova
imobiliária editando o YAML, sem mexer no código.

Educado por padrão: User-Agent identificável, delay entre requisições,
respeita um limite de páginas. Ajuste no config.
"""
import time
import requests
import urllib3
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from analyzer import Imovel
from parser import parse_preco, parse_area, parse_quartos, parse_vagas

DEFAULT_UA = "Mozilla/5.0 (compatible; ImovelBot/1.0; monitoramento de anuncios)"


def _texto(node):
    return node.get_text(" ", strip=True) if node else ""


def _selec(card, seletor):
    """Aplica um seletor CSS e devolve o texto do primeiro match."""
    if not seletor:
        return ""
    node = card.select_one(seletor)
    return _texto(node)


def raspar_site(site_cfg, delay=2.0, max_paginas=None, timeout=20, session=None,
                verify_ssl=True):
    """
    site_cfg: dict do config.yaml para UMA imobiliária.
    Retorna lista de Imovel (ainda sem análise).
    """
    sess = session or requests.Session()
    sess.headers.update({"User-Agent": site_cfg.get("user_agent", DEFAULT_UA)})
    verify_ssl = site_cfg.get("verificar_ssl", verify_ssl)

    nome = site_cfg["nome"]
    base = site_cfg["base_url"]
    url_tmpl = site_cfg["listagem_url"]          # pode conter {page}
    sel = site_cfg["seletores"]
    cidade = site_cfg.get("cidade", "")
    tipo_padrao = site_cfg.get("tipo_padrao", "")
    paginas = site_cfg.get("paginas", 1)
    if max_paginas:
        paginas = min(paginas, max_paginas)

    achados = []
    for p in range(1, paginas + 1):
        url = url_tmpl.format(page=p) if "{page}" in url_tmpl else url_tmpl
        try:
            r = sess.get(url, timeout=timeout, verify=verify_ssl)
            r.raise_for_status()
            # evita mojibake (ex.: "m²" virar "mÂ²"): usa o encoding detectado
            # quando o servidor não declara charset no header.
            if not r.encoding or r.encoding.lower() in ("iso-8859-1", "latin-1"):
                r.encoding = r.apparent_encoding or "utf-8"
        except Exception as e:
            print(f"  [!] {nome} pag {p}: erro ao baixar ({e})")
            break

        soup = BeautifulSoup(r.text, "lxml")
        cards = soup.select(sel["card"])
        if not cards:
            print(f"  [i] {nome} pag {p}: nenhum card encontrado (seletor '{sel['card']}').")
            break

        for card in cards:
            link_node = card.select_one(sel.get("link", "a"))
            href = link_node.get("href") if link_node else None
            link = urljoin(base, href) if href else None
            if not link:
                continue

            titulo = _selec(card, sel.get("titulo"))
            descricao = _selec(card, sel.get("descricao"))
            preco_txt = _selec(card, sel.get("preco"))
            area_txt = _selec(card, sel.get("area"))
            quartos_txt = _selec(card, sel.get("quartos"))
            bairro = _selec(card, sel.get("bairro"))

            # fallback: se não achou por seletor, tenta do texto todo do card
            texto_card = _texto(card)
            preco = parse_preco(preco_txt) or parse_preco(texto_card)
            area = parse_area(area_txt) or parse_area(texto_card)
            quartos = parse_quartos(quartos_txt) or parse_quartos(texto_card)
            vagas = parse_vagas(texto_card)

            achados.append(Imovel(
                url=link,
                titulo=titulo or texto_card[:80],
                descricao=descricao or texto_card,
                bairro=bairro,
                cidade=cidade,
                tipo=tipo_padrao,
                preco=preco,
                area=area,
                quartos=quartos,
                vagas=vagas,
                fonte=nome,
            ))

        print(f"  [ok] {nome} pag {p}: {len(cards)} cards")
        time.sleep(delay)

    return achados


def raspar_todos(config, max_paginas=None):
    """Percorre todas as imobiliárias ativas do config."""
    todos = []
    scfg = config.get("scraper", {})
    delay = scfg.get("delay_segundos", 2.0)
    # em rede com proxy que intercepta TLS (certificado próprio), o requests
    # rejeita a conexão. verificar_ssl: false desliga a checagem (por site ou global).
    verify_ssl = scfg.get("verificar_ssl", True)
    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    sess = requests.Session()
    for site in config.get("sites", []):
        if not site.get("ativo", True):
            continue
        print(f"> Raspando: {site['nome']}")
        try:
            todos.extend(raspar_site(site, delay=delay, max_paginas=max_paginas,
                                     session=sess, verify_ssl=verify_ssl))
        except Exception as e:
            print(f"  [!] falha geral em {site['nome']}: {e}")
    return todos
