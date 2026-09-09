"""
scraper.py
Raspador GENÉRICO e configurável. Cada site (imobiliária) é descrito no
config.yaml com seus próprios seletores CSS. Assim você adiciona uma nova
imobiliária editando o YAML, sem mexer no código.

Educado por padrão: User-Agent identificável, delay entre requisições,
respeita um limite de páginas. Ajuste no config.
"""
import re
import time
import requests
import urllib3
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from analyzer import Imovel
from parser import (parse_preco, parse_area, parse_area_construida,
                    parse_quartos, parse_vagas, parse_tipo, parse_local,
                    titulo_curto)

DEFAULT_UA = "Mozilla/5.0 (compatible; ImovelBot/1.0; monitoramento de anuncios)"


def _texto(node):
    return node.get_text(" ", strip=True) if node else ""


def _selec(card, seletor):
    """Aplica um seletor CSS e devolve o texto do primeiro match."""
    if not seletor:
        return ""
    node = card.select_one(seletor)
    return _texto(node)


def _monta_url_pagina(tmpl, p, pular_param_pagina_1):
    """
    Monta a URL da página p. Se o site usa '&page=1' que dá 404 (a 1ª página
    é a URL "pelada"), marque 'pular_param_pagina_1: true' no config: na página
    1 o parâmetro/segmento que carrega {page} é removido.
    """
    if "{page}" not in tmpl:
        return tmpl
    if p == 1 and pular_param_pagina_1:
        u = re.sub(r"[?&][^?&=]+=\{page\}", "", tmpl)      # &page={page}
        u = re.sub(r"/[^/]*\{page\}[^/]*/?", "/", u)       # /pagina-{page}/
        u = u.replace("{page}", "1").replace("?&", "?").rstrip("?&")
        return u
    return tmpl.format(page=p)


def _baixar(sess, url, timeout, verify_ssl, tentativas=1):
    """GET com N tentativas (WAF de imobiliária às vezes solta 403/405/429
    intermitente; uma pausa curta costuma resolver)."""
    erro = None
    for i in range(tentativas):
        try:
            r = sess.get(url, timeout=timeout, verify=verify_ssl)
            r.raise_for_status()
            # evita mojibake ("m²" -> "mÂ²") quando o servidor não declara charset.
            if not r.encoding or r.encoding.lower() in ("iso-8859-1", "latin-1"):
                r.encoding = r.apparent_encoding or "utf-8"
            return r
        except Exception as e:
            erro = e
            if i + 1 < tentativas:
                time.sleep(2 + 2 * i)
    raise erro


def _enriquecer_com_detalhe(im, sess, sel_det, timeout, verify_ssl):
    """
    Abre a página do próprio imóvel e melhora os campos: área CONSTRUÍDA
    (não a do terreno), descrição completa (é onde 'espólio/inventário'
    costuma aparecer), e preço/bairro se faltarem no card.
    """
    try:
        r = _baixar(sess, im.url, timeout, verify_ssl, tentativas=2)
    except Exception as e:
        print(f"     [i] detalhe falhou ({im.url[-40:]}): {e}")
        return
    soup = BeautifulSoup(r.text, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.extract()
    texto = _texto(soup.body or soup)

    desc = _selec(soup, sel_det.get("descricao")) or texto
    if len(desc) > len(im.descricao or ""):
        im.descricao = desc[:4000]

    area_txt = _selec(soup, sel_det.get("area"))
    area = parse_area_construida(area_txt) if area_txt else parse_area_construida(texto)
    if area:
        im.area = area

    if not im.preco:
        im.preco = parse_preco(_selec(soup, sel_det.get("preco")) or texto)
    if not im.bairro:
        cidade, bairro = parse_local(texto, im.url)
        im.bairro = bairro or im.bairro
        if cidade and not im.cidade:
            im.cidade = cidade


def raspar_site(site_cfg, delay=2.0, max_paginas=None, timeout=20, session=None,
                verify_ssl=True, delay_detalhe=None):
    """
    site_cfg: dict do config.yaml para UMA imobiliária.
    Retorna lista de Imovel (ainda sem análise).

    Chaves opcionais do site_cfg:
      cidade_auto: true          -> extrai a cidade do próprio anúncio (agregadores
                                    que misturam municípios). Sobrescreve 'cidade'.
      pular_param_pagina_1: true -> some com o parâmetro de página na 1ª página.
      detalhe: true              -> abre a página de cada imóvel p/ pegar a área
                                    CONSTRUÍDA e a descrição inteira (mais lento).
      seletores.detalhe: {...}   -> seletores da página de detalhe (opcional).
    """
    sess = session or requests.Session()
    sess.headers.update({"User-Agent": site_cfg.get("user_agent", DEFAULT_UA)})
    verify_ssl = site_cfg.get("verificar_ssl", verify_ssl)
    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    delay_detalhe = delay_detalhe if delay_detalhe is not None else delay

    nome = site_cfg["nome"]
    base = site_cfg["base_url"]
    url_tmpl = site_cfg["listagem_url"]
    sel = site_cfg["seletores"]
    sel_det = sel.get("detalhe", {}) or {}
    cidade_cfg = site_cfg.get("cidade", "")
    cidade_auto = site_cfg.get("cidade_auto", False)
    tipo_padrao = site_cfg.get("tipo_padrao", "")
    usar_detalhe = site_cfg.get("detalhe", False)
    pular_p1 = site_cfg.get("pular_param_pagina_1", False)
    paginas = site_cfg.get("paginas", 1)
    if max_paginas:
        paginas = min(paginas, max_paginas)

    achados = []
    vistos = set()
    for p in range(1, paginas + 1):
        url = _monta_url_pagina(url_tmpl, p, pular_p1)
        try:
            r = _baixar(sess, url, timeout, verify_ssl, tentativas=3)
        except Exception as e:
            print(f"  [!] {nome} pag {p}: erro ao baixar ({e})")
            break

        soup = BeautifulSoup(r.text, "lxml")
        cards = soup.select(sel["card"])
        if not cards:
            print(f"  [i] {nome} pag {p}: nenhum card encontrado (seletor '{sel['card']}').")
            break

        novos_na_pagina = 0
        for card in cards:
          try:  # um card com HTML estranho não pode derrubar o site inteiro
            link_node = card.select_one(sel.get("link", "a"))
            href = link_node.get("href") if link_node else None
            # alguns layouts (ex.: Kenlo) fazem o próprio card ser um <a>;
            # select_one só olha descendentes, então caímos aqui.
            if not href and card.name == "a":
                href = card.get("href")
            if not href:
                href = card.get("data-href") or card.get("data-url")
            link = urljoin(base, href) if href else None
            if not link or link in vistos:
                continue
            vistos.add(link)
            novos_na_pagina += 1

            titulo = _selec(card, sel.get("titulo"))
            descricao = _selec(card, sel.get("descricao"))
            texto_card = _texto(card)

            preco = parse_preco(_selec(card, sel.get("preco"))) or parse_preco(texto_card)
            # area construída (ignora "560 m² de terreno" e afins)
            area = (parse_area(_selec(card, sel.get("area")))
                    or parse_area_construida(texto_card))
            quartos = parse_quartos(_selec(card, sel.get("quartos"))) or parse_quartos(texto_card)
            vagas = parse_vagas(texto_card)

            bairro = _selec(card, sel.get("bairro"))
            cidade = cidade_cfg
            # o seletor de bairro costuma vir "Bairro, Cidade-SP" -> separa
            if bairro and re.search(r"[-/]\s*SP\b", bairro, re.I):
                c_b, b_b = parse_local(bairro)
                if b_b:
                    bairro = b_b
                if cidade_auto and c_b:
                    cidade = c_b
            if not bairro or (cidade_auto and cidade == cidade_cfg):
                c_txt, b_txt = parse_local(f"{titulo} {texto_card}", link)
                bairro = bairro or b_txt
                if cidade_auto and c_txt:
                    cidade = c_txt

            tipo = tipo_padrao or parse_tipo(f"{titulo} {texto_card}")

            im = Imovel(
                url=link,
                titulo=titulo or titulo_curto(texto_card),
                descricao=descricao or texto_card,
                bairro=bairro,
                cidade=cidade,
                tipo=tipo,
                preco=preco,
                area=area,
                quartos=quartos,
                vagas=vagas,
                fonte=nome,
            )

            if usar_detalhe:
                _enriquecer_com_detalhe(im, sess, sel_det, timeout, verify_ssl)
                if not im.tipo:
                    im.tipo = parse_tipo(im.descricao)
                time.sleep(delay_detalhe)

            achados.append(im)
          except Exception as e:
            print(f"     [i] {nome}: card ignorado ({type(e).__name__}: {e})")

        print(f"  [ok] {nome} pag {p}: {len(cards)} cards ({novos_na_pagina} novos)")
        if novos_na_pagina == 0:      # paginou além do fim -> para
            break
        time.sleep(delay)

    return achados


def raspar_todos(config, max_paginas=None):
    """Percorre todas as imobiliárias ativas do config."""
    todos = []
    scfg = config.get("scraper", {})
    delay = scfg.get("delay_segundos", 2.0)
    delay_detalhe = scfg.get("delay_detalhe_segundos", min(delay, 1.5))
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
                                     session=sess, verify_ssl=verify_ssl,
                                     delay_detalhe=delay_detalhe))
        except Exception as e:
            print(f"  [!] falha geral em {site['nome']}: {e}")
    return todos
