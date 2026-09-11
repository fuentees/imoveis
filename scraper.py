"""
scraper.py
Raspador GENÉRICO e configurável. Cada site (imobiliária) é descrito no
config.yaml com seus próprios seletores CSS. Assim você adiciona uma nova
imobiliária editando o YAML, sem mexer no código.

Educado por padrão: User-Agent identificável, delay entre requisições,
limite de páginas e checagem de robots.txt. Ajuste no config.
"""
import re
import time
import urllib.robotparser
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
import urllib3
from bs4 import BeautifulSoup

from analyzer import Imovel
from parser import (parse_preco, parse_area, parse_area_construida,
                    parse_quartos, parse_vagas, parse_tipo, parse_local,
                    titulo_curto, normalizar_texto, preco_eh_parcial)
import log

_log = log.get(__name__)

DEFAULT_UA = "ImovelBot/1.0 (monitoramento de anuncios)"

# cache de robots.txt por domínio: netloc -> RobotFileParser (ou None se falhou)
_ROBOTS_CACHE = {}


def _texto(node):
    return node.get_text(" ", strip=True) if node else ""


def _selec(card, seletor):
    """Aplica um seletor CSS e devolve o texto do primeiro match."""
    if not seletor:
        return ""
    if isinstance(seletor, dict):
        node = card.select_one(seletor["css"])
        return str(node.get(seletor["atributo"], "")) if node else ""
    node = card.select_one(seletor)
    return _texto(node)


def _robots_permite(sess, url, user_agent, timeout=10):
    """
    True se o robots.txt do domínio permite baixar `url` para o nosso UA.
    Fail-open: se o robots.txt não existe ou não dá pra ler, assume permitido.
    """
    partes = urlsplit(url)
    base = f"{partes.scheme}://{partes.netloc}"
    if base not in _ROBOTS_CACHE:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = sess.get(urljoin(base, "/robots.txt"), timeout=timeout)
            if r.status_code == 200 and r.text.strip():
                rp.parse(r.text.splitlines())
            else:
                rp = None
        except Exception:
            rp = None
        _ROBOTS_CACHE[base] = rp
    rp = _ROBOTS_CACHE[base]
    if rp is None:
        return True
    return rp.can_fetch(user_agent, url)


def _monta_url_pagina(tmpl, p, pular_param_pagina_1):
    """
    Monta a URL da página p. Se o site usa '&page=1' que dá 404 (a 1ª página
    é a URL "pelada"), marque 'pular_param_pagina_1: true' no config: na página
    1 o parâmetro/segmento que carrega {page} é removido.
    """
    if "{page}" not in tmpl:
        return tmpl
    if p == 1 and pular_param_pagina_1:
        parts = urlsplit(tmpl)
        query = "&".join(x for x in parts.query.split("&") if "{page}" not in x)
        u = urlunsplit(parts._replace(query=query))
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
        _log.info("     [i] detalhe falhou (%s): %s", im.url[-40:], e)
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
                verify_ssl=True, delay_detalhe=None, respeitar_robots=True, diagnostico=None):
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
      respeitar_robots: false    -> ignora o robots.txt DESTE site.
      verificar_ssl: false       -> não valida o certificado TLS DESTE site.
    """
    diagnostico = diagnostico if diagnostico is not None else {}
    diagnostico.update(status="ok", paginas=0, erros=[], precos_parciais=0)
    sess = session or requests.Session()
    sess.headers.update({"User-Agent": site_cfg.get("user_agent", DEFAULT_UA)})
    ua = sess.headers["User-Agent"]
    verify_ssl = site_cfg.get("verificar_ssl", verify_ssl)
    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    respeitar_robots = site_cfg.get("respeitar_robots", respeitar_robots)
    delay_detalhe = delay_detalhe if delay_detalhe is not None else delay

    nome = site_cfg["nome"]
    base = site_cfg["base_url"]
    url_tmpl = site_cfg["listagem_url"]
    sel = site_cfg.get("seletores") or {}
    card_sel = sel.get("card")
    if not card_sel:
        _log.warning("  [!] %s: sem 'seletores.card' no config -> site ignorado.", nome)
        return []
    link_sel = sel.get("link") or "a"
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

        if respeitar_robots and not _robots_permite(sess, url, ua):
            _log.warning("  [robots] %s: %s bloqueado pelo robots.txt -> pulando. "
                         "(use 'respeitar_robots: false' para ignorar)", nome, url)
            diagnostico["status"] = "bloqueado_robots"
            break

        try:
            r = _baixar(sess, url, timeout, verify_ssl, tentativas=3)
        except Exception as e:
            _log.warning("  [!] %s pag %s: erro ao baixar (%s)", nome, p, e)
            diagnostico["status"] = "erro_http"
            diagnostico["erros"].append(str(e))
            break

        soup = BeautifulSoup(r.text, "lxml")
        try:
            cards = soup.select(card_sel)
        except Exception as e:
            _log.warning("  [!] %s: seletor de card inválido (%r): %s", nome, card_sel, e)
            break
        diagnostico["paginas"] += 1
        if not cards:
            _log.info("  [i] %s pag %s: nenhum card encontrado (seletor %r).",
                      nome, p, card_sel)
            break

        novos_na_pagina = 0
        for card in cards:
          try:  # um card com HTML estranho não pode derrubar o site inteiro
            link_node = card.select_one(link_sel)
            href = link_node.get("href") if link_node else None
            # alguns layouts (ex.: Kenlo) fazem o próprio card ser um <a>;
            # select_one só olha descendentes, então caímos aqui.
            if not href and card.name == "a":
                href = card.get("href")
            if not href:
                href = card.get("data-href") or card.get("data-url")
            link = urljoin(base, href) if href else None
            if link and urlsplit(link).scheme not in ("http", "https"):
                continue
            if not link or link in vistos:
                continue
            vistos.add(link)
            novos_na_pagina += 1

            titulo = _selec(card, sel.get("titulo"))
            descricao = _selec(card, sel.get("descricao"))
            texto_card = _texto(card)

            # O card inteiro dá contexto para não confundir entrada/parcela com preço total.
            preco = parse_preco(texto_card)
            parcial_detectado = (not preco and any(
                termo in normalizar_texto(texto_card)
                for termo in ("entrada", "sinal", "parcela", "mensais")))
            # area construída (ignora "560 m² de terreno" e afins)
            area = (parse_area(_selec(card, sel.get("area")))
                    or parse_area_construida(texto_card))
            quartos = parse_quartos(_selec(card, sel.get("quartos"))) or parse_quartos(texto_card)
            vagas = parse_vagas(_selec(card, sel.get("vagas"))) or parse_vagas(texto_card)

            bairro = _selec(card, sel.get("bairro"))
            cidade_txt = _selec(card, sel.get("cidade"))
            cidade = re.sub(r"\s*[-/,]\s*SP$", "", cidade_txt, flags=re.I).strip() or cidade_cfg
            if site_cfg.get("bairro_inclui_cidade") and "," in bairro:
                bairro, cidade = (p.strip() for p in bairro.rsplit(",", 1))
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

            tipo = tipo_padrao or parse_tipo(_selec(card, sel.get("tipo")) or f"{titulo} {texto_card}")

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

            if usar_detalhe and (not respeitar_robots or _robots_permite(sess, im.url, ua)):
                _enriquecer_com_detalhe(im, sess, sel_det, timeout, verify_ssl)
                if preco_eh_parcial(im.descricao, im.preco):
                    im.preco = None
                    parcial_detectado = True
                if not im.tipo:
                    im.tipo = parse_tipo(im.descricao)
                time.sleep(delay_detalhe)

            permitidas = site_cfg.get("cidades_permitidas", [])
            if permitidas and normalizar_texto(im.cidade) not in {normalizar_texto(c) for c in permitidas}:
                continue
            if parcial_detectado:
                diagnostico["precos_parciais"] += 1
            achados.append(im)
          except Exception as e:
            _log.info("     [i] %s: card ignorado (%s: %s)", nome, type(e).__name__, e)

        _log.info("  [ok] %s pag %s: %s cards (%s novos)",
                  nome, p, len(cards), novos_na_pagina)
        if novos_na_pagina == 0:      # paginou além do fim -> para
            break
        time.sleep(delay)

    if not achados and diagnostico["status"] == "ok":
        diagnostico["status"] = "sem_anuncios"
    elif diagnostico["status"] == "ok" and diagnostico["paginas"] == paginas and "{page}" in url_tmpl and novos_na_pagina:
        diagnostico["status"] = "limite_paginas"
    return achados


def raspar_todos(config, max_paginas=None, relatorio=None):
    """Percorre todas as imobiliárias ativas do config."""
    _ROBOTS_CACHE.clear()  # regras podem mudar entre ciclos do modo loop
    todos = []
    scfg = config.get("scraper", {})
    delay = scfg.get("delay_segundos", 2.0)
    delay_detalhe = scfg.get("delay_detalhe_segundos", min(delay, 1.5))
    respeitar_robots = scfg.get("respeitar_robots", True)
    # em rede com proxy que intercepta TLS (certificado próprio), o requests
    # rejeita a conexão. verificar_ssl: false desliga a checagem (por site ou global).
    verify_ssl = scfg.get("verificar_ssl", True)
    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    if relatorio is not None:
        relatorio["fontes"] = []
    nomes_cidades = {normalizar_texto(c): c for c in config.get("cidades_monitoradas", [])}
    permitidas = set(nomes_cidades)
    sess = requests.Session()
    for site in config.get("sites", []):
        if not site.get("ativo", True):
            continue
        _log.info("> Raspando: %s", site["nome"])
        inicio = time.monotonic()
        diag = {"nome": site["nome"], "url": site["listagem_url"], "anuncios": 0}
        try:
            achados = raspar_site(site, delay=delay, max_paginas=max_paginas,
                                 session=sess, verify_ssl=verify_ssl,
                                 delay_detalhe=delay_detalhe,
                                 respeitar_robots=respeitar_robots, diagnostico=diag)
            if permitidas:
                achados = [im for im in achados if normalizar_texto(im.cidade) in permitidas]
            for im in achados:
                im.cidade = nomes_cidades.get(normalizar_texto(im.cidade), im.cidade)
            diag["anuncios"] = len(achados)
            diag["com_preco_area"] = sum(bool(im.preco and im.area) for im in achados)
            if not achados and diag.get("status") == "ok":
                diag["status"] = "sem_anuncios"
            todos.extend(achados)
        except Exception as e:
            diag.update(status="erro", erros=[str(e)])
            _log.warning("  [!] falha geral em %s: %s", site["nome"], e)
        diag["segundos"] = round(time.monotonic() - inicio, 1)
        if relatorio is not None:
            relatorio["fontes"].append(diag)
    sess.close()
    if not todos and any(site.get("ativo", True) for site in config.get("sites", [])):
        raise RuntimeError("Nenhum anúncio coletado dos sites ativos; confira os logs e seletores.")
    return todos
