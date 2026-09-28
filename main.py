"""
main.py  -  orquestrador do bot.

Uso:
    python main.py --once            # roda uma vez e sai
    python main.py --loop            # roda continuamente no intervalo do config
    python main.py --once --dry-run  # não envia Telegram, só imprime (calibração)
    python main.py --max-paginas 1   # limita páginas (teste rápido)

Credenciais do Telegram: via config.yaml OU variáveis de ambiente
    TELEGRAM_TOKEN / TELEGRAM_CHAT_ID  (ambiente tem prioridade).
"""
import html
import os
import sys
import time
import argparse
import yaml
import json
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlsplit

import log
from scraper import raspar_todos, validar_detalhes_candidatos
from analyzer import analisar, comps_do_historico, montar_regioes
from parser import normalizar_texto
from storage import Storage
from notifier import Telegram, formatar_alerta

_log = log.get(__name__)


def carregar_config(caminho):
    with open(caminho, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    validar_config(config)
    return config


def validar_config(config):
    """Rejeita configurações inválidas antes de acessar sites ou criar o banco."""
    import math
    if not isinstance(config, dict):
        raise ValueError("A configuração deve ser um mapa YAML.")
    for key in ("telegram", "scraper", "analise", "agendamento"):
        if key in config and not isinstance(config[key], dict):
            raise ValueError(f"{key} deve ser um mapa YAML.")
    cidades = config.get("cidades_monitoradas", [])
    if not isinstance(cidades, list) or any(not isinstance(c, str) or not c.strip() for c in cidades):
        raise ValueError("cidades_monitoradas deve ser uma lista de nomes de cidades.")
    sites = config.get("sites")
    if not isinstance(sites, list) or not sites:
        raise ValueError("Configure pelo menos um site em sites.")
    for site in sites:
        if not isinstance(site, dict):
            raise ValueError("Cada site deve ser um mapa YAML.")
        if not site.get("ativo", True):
            continue
        for key in ("nome", "base_url", "listagem_url"):
            if not isinstance(site.get(key), str) or not site[key].strip():
                raise ValueError(f"Site sem {key} válido.")
        from urllib.parse import urlsplit
        for key in ("base_url", "listagem_url"):
            url = urlsplit(site[key])
            if url.scheme not in ("http", "https") or not url.netloc:
                raise ValueError(f"{key} deve ser uma URL HTTP(S).")
        if not isinstance(site.get("seletores"), dict) or not site["seletores"].get("card"):
            raise ValueError(f"{site['nome']}: configure seletores.card.")
        cidades = site.get("cidades_permitidas", [])
        if not isinstance(cidades, list) or any(not isinstance(c, str) or not c.strip() for c in cidades):
            raise ValueError("cidades_permitidas deve ser uma lista de cidades.")
        n = site.get("paginas", 1)
        if type(n) is not int or n < 1:
            raise ValueError("paginas deve ser um inteiro positivo.")
    ranges = {
        "analise": {"min_amostra": (2, None), "limiar_desconto": (0, 1),
                    "limiar_desconto_regiao": (0, 1),
                    "realerta_queda": (0, 1), "historico_dias": (0, None),
                    "max_alertas_por_ciclo": (1, None),
                    "max_alertas_por_dominio": (1, None),
                    "max_alertas_por_cidade": (1, None),
                    "max_alertas_por_dominio_dia": (1, None),
                    "preco_min": (0, None), "preco_m2_min": (0, None), "preco_m2_max": (0, None)},
        "scraper": {"delay_segundos": (0, None), "delay_detalhe_segundos": (0, None),
                    "avisar_fonte_apos_falhas": (1, None)},
        "agendamento": {"intervalo_minutos": (0.01, None)},
    }
    for section, fields in ranges.items():
        for key, (low, high) in fields.items():
            if key not in config.get(section, {}):
                continue
            value = config[section][key]
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or value < low or (high is not None and value >= high)):
                raise ValueError(f"Valor inválido: {section}.{key}")
    cotas = config.get("scraper", {}).get("paginas_por_plataforma", {})
    if not isinstance(cotas, dict) or any(type(v) is not int or v < 1 for v in cotas.values()):
        raise ValueError("scraper.paginas_por_plataforma deve mapear plataforma -> páginas (inteiro positivo).")
    tipos = config.get("analise", {}).get("tipos_alerta", [])
    if not isinstance(tipos, list) or any(not isinstance(t, str) or not t.strip() for t in tipos):
        raise ValueError("analise.tipos_alerta deve ser uma lista de tipos (ex.: casa, sobrado).")
    regioes = config.get("regioes", [])
    if not isinstance(regioes, list):
        raise ValueError("regioes deve ser uma lista.")
    for r in regioes:
        if (not isinstance(r, dict) or not isinstance(r.get("nome"), str) or not r["nome"].strip()
                or not (r.get("cidade") or r.get("cidades"))
                or not (r.get("bairros") or r.get("prefixos"))):
            raise ValueError("Cada região precisa de nome, cidade(s) e bairros ou prefixos.")
    for key in ("exigir_keyword", "permitir_keyword_sem_desconto"):
        if key in config.get("analise", {}) and type(config["analise"][key]) is not bool:
            raise ValueError(f"Valor inválido: analise.{key}")
    a = config.get("analise", {})
    if a.get("preco_m2_min", 300) >= a.get("preco_m2_max", 60000):
        raise ValueError("preco_m2_min deve ser menor que preco_m2_max.")


# Sinais de que o imóvel não é uma casa pronta. No título qualquer um desclassifica;
# na descrição só os de obra/planta (descrição de casa costuma citar "terreno de 500 m²").
_NAO_PRONTO_TITULO = ("terreno", "lote", "galpao", "na planta", "em construcao",
                      "lancamento", "pre-lancamento", "pre lancamento")
_NAO_PRONTO_DESCRICAO = ("na planta", "em construcao", "previsao de entrega",
                         "entrega prevista", "obra em andamento", "pre-lancamento")


def _alertavel(im, tipos):
    """Só alerta os tipos pedidos (ex.: casas) e prontos para morar."""
    if tipos and normalizar_texto(im.tipo) not in tipos:
        return False
    titulo = normalizar_texto(im.titulo)
    descricao = normalizar_texto(im.descricao)
    return not (any(t in titulo for t in _NAO_PRONTO_TITULO)
                or any(t in descricao for t in _NAO_PRONTO_DESCRICAO))


def _deve_realertar(im, preco_anterior, queda_min):
    """
    Já alertamos esse imóvel antes. Só vale re-alertar se o preço caiu pelo
    menos `queda_min` (0.10 = 10%) em relação ao preço do último alerta.
    """
    if not (preco_anterior and im.preco):
        return False
    return im.preco <= preco_anterior * (1 - queda_min)


def _dominio(url):
    return urlsplit(url).netloc.lower().removeprefix("www.")


def _selecionar_diverso(pendentes, limite, max_dominio=2, max_cidade=3,
                        max_dominio_dia=None, enviados_24h=None):
    """
    Escolhe os maiores scores sem deixar um portal ou cidade dominar o ciclo.
    `max_dominio_dia` limita também a soma com o que o portal já recebeu nas
    últimas 24h (`enviados_24h`): um portal grande não ocupa todos os ciclos.
    """
    escolhidos = []
    por_dominio = Counter()
    por_cidade = Counter()
    enviados_24h = enviados_24h or Counter()
    for im in pendentes:
        dominio = _dominio(im.url) or im.fonte
        cidade = (im.cidade or "").casefold()
        if por_dominio[dominio] >= max_dominio or por_cidade[cidade] >= max_cidade:
            continue
        if max_dominio_dia and enviados_24h[dominio] + por_dominio[dominio] >= max_dominio_dia:
            continue
        escolhidos.append(im)
        por_dominio[dominio] += 1
        por_cidade[cidade] += 1
        if len(escolhidos) == limite:
            return escolhidos
    return escolhidos


def _status_fonte(diag):
    erros = "; ".join(diag.get("erros", []))
    return f"{diag.get('status', '?')}: {erros}"[:160] if erros else diag.get("status", "?")


def verificar_saude_fontes(fontes, storage, tg, minimo_falhas, relatorio=None):
    """
    Conta ciclos seguidos sem nenhum anúncio por fonte e avisa no Telegram
    uma única vez quando passa de `minimo_falhas` (e de novo quando voltar).
    Sem isso, uma fonte bloqueada fica dias parada com o workflow "verde".
    """
    voltaram = [f["nome"] for f in fontes
                if storage.registrar_saude(f["nome"], f.get("anuncios", 0) > 0, _status_fonte(f))]
    paradas = storage.fontes_para_avisar(minimo_falhas)
    if relatorio is not None:
        relatorio["fontes_paradas"] = [nome for nome, *_ in paradas]
    if not (paradas or voltaram) or tg is None:
        return
    linhas = []
    if paradas:
        linhas.append(f"⚠️ <b>Fontes sem dados há {minimo_falhas}+ ciclos seguidos</b>")
        for nome, falhas, ultimo_ok, status in paradas:
            quando = datetime.fromtimestamp(ultimo_ok).strftime("%d/%m %H:%M") if ultimo_ok else "nunca"
            linhas.append(f"• {html.escape(nome)} ({falhas} ciclos; último dado: {quando})\n"
                          f"  <i>{html.escape(status or '')}</i>")
    if voltaram:
        linhas.append("✅ <b>Voltaram a coletar:</b> " + html.escape(", ".join(voltaram)))
    if tg.enviar("\n".join(linhas)):
        storage.marcar_avisadas([nome for nome, *_ in paradas])


def rodar_ciclo(config, storage, tg, dry_run=False, max_paginas=None, relatorio=None):
    _log.info("==== Novo ciclo: %s ====", time.strftime("%Y-%m-%d %H:%M:%S"))

    relatorio = relatorio if relatorio is not None else {}
    relatorio.update(inicio=datetime.now(timezone.utc).isoformat(), dry_run=dry_run)
    imoveis = raspar_todos(config, max_paginas=max_paginas, relatorio=relatorio)
    relatorio["anuncios"] = len(imoveis)
    relatorio["por_cidade"] = dict(Counter(im.cidade for im in imoveis))
    _log.info("Total raspado: %s anúncios", len(imoveis))
    if not dry_run:
        verificar_saude_fontes(relatorio.get("fontes", []), storage, tg,
                               config.get("scraper", {}).get("avisar_fonte_apos_falhas", 6),
                               relatorio)

    a = config.get("analise", {})
    regioes = montar_regioes(config.get("regioes"))
    historico = comps_do_historico(
        storage.carregar_comparaveis(dias=a.get("historico_dias", 180)), regioes)
    _log.info("Comparáveis do histórico: %s", len(historico))

    ops = analisar(
        imoveis,
        min_amostra=a.get("min_amostra", 4),
        limiar_desconto=a.get("limiar_desconto", 0.30),
        exigir_keyword=a.get("exigir_keyword", False),
        permitir_keyword_sem_desconto=a.get("permitir_keyword_sem_desconto", False),
        preco_min=a.get("preco_min", 50_000),
        preco_m2_min=a.get("preco_m2_min", 300),
        preco_m2_max=a.get("preco_m2_max", 60_000),
        historico=historico,
        regioes=regioes,
        limiar_desconto_regiao=a.get("limiar_desconto_regiao"),
    )
    tipos = {normalizar_texto(t) for t in a.get("tipos_alerta", [])}
    ops = [im for im in ops if _alertavel(im, tipos)]           # antes de abrir detalhes
    ops = validar_detalhes_candidatos(ops, config, relatorio)
    ops = [im for im in ops if _alertavel(im, tipos)]           # descrição completa
    _log.info("Oportunidades detectadas: %s", len(ops))
    relatorio["oportunidades"] = len(ops)

    # persiste tudo que viu (histórico ajuda a calibrar a mediana nos próximos ciclos)
    storage.upsert_imoveis(im for im in imoveis if im.preco_m2)

    queda_min = a.get("realerta_queda", 0.10)
    limite_alertas = a.get("max_alertas_por_ciclo", 10)
    pendentes = []
    for im in ops:
        info = storage.info_alerta(im.url)
        if info is not None:
            preco_ant, _ = info
            if not _deve_realertar(im, preco_ant, queda_min):
                continue
            _log.info("re-alerta (preço caiu): %s  %s -> %s",
                      im.url[-50:], preco_ant, im.preco)
        pendentes.append(im)

    novos = len(pendentes)
    enviados_24h = Counter(_dominio(u) for u in storage.urls_alertadas_desde(time.time() - 86400))
    fila = pendentes if dry_run else _selecionar_diverso(
        pendentes, limite_alertas,
        max_dominio=a.get("max_alertas_por_dominio", 2),
        max_cidade=a.get("max_alertas_por_cidade", 3),
        max_dominio_dia=a.get("max_alertas_por_dominio_dia"),
        enviados_24h=enviados_24h)
    adiados = 0 if dry_run else max(0, novos - len(fila))
    enviados = falhas = 0
    enviados_lista = []
    for im in fila:
        msg = formatar_alerta(im)
        if dry_run:
            _log.info("--- (dry-run, não enviado) ---\n%s", msg)
            continue
        if tg and tg.enviar(msg):
            storage.marcar_alertado(im.url, im.score, im.preco)   # só marca se enviou
            enviados += 1
            enviados_lista.append(im)
        else:
            falhas += 1        # não marca: tenta de novo no próximo ciclo
        time.sleep(1)          # respeita rate limit do Telegram

    if dry_run:
        _log.info("Alertas novos (dry-run): %s", novos)
    else:
        _log.info("Alertas novos: %s  |  enviados: %s  |  adiados: %s  |  falharam: %s",
                  novos, enviados, adiados, falhas)
    relatorio.update(novos=novos, enviados=enviados, adiados=adiados,
                     falhas_envio=falhas,
                     fontes_enviadas=dict(Counter(im.fonte for im in enviados_lista)),
                     cidades_enviadas=dict(Counter(im.cidade for im in enviados_lista)),
                     fim=datetime.now(timezone.utc).isoformat())
    if falhas:
        raise RuntimeError(f"Falha no envio de {falhas} alerta(s); serão tentados no próximo ciclo.")
    return novos


def executar_ciclo(config, storage, tg, args):
    relatorio = {}
    try:
        return rodar_ciclo(config, storage, tg, args.dry_run, args.max_paginas, relatorio)
    except Exception as exc:
        relatorio["erro"] = str(exc)
        raise
    finally:
        if args.relatorio:
            destino = Path(args.relatorio)
            temporario = destino.with_suffix(destino.suffix + ".tmp")
            temporario.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
            temporario.replace(destino)


def montar_telegram(config, dry_run):
    if dry_run:
        return None
    token = os.environ.get("TELEGRAM_TOKEN") or config.get("telegram", {}).get("token")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or config.get("telegram", {}).get("chat_id")
    if not token or not chat_id:
        _log.error("Sem TELEGRAM_TOKEN/CHAT_ID. Rode com --dry-run ou configure as credenciais.")
        sys.exit(1)
    return Telegram(token, chat_id)


def main():
    ap = argparse.ArgumentParser(description="Bot garimpeiro de imóveis")
    ap.add_argument("--config", default="config.yaml")
    modo = ap.add_mutually_exclusive_group()
    modo.add_argument("--once", action="store_true", help="roda um ciclo e sai")
    modo.add_argument("--loop", action="store_true", help="roda em loop contínuo")
    ap.add_argument("--dry-run", action="store_true", help="não envia Telegram, só imprime")
    ap.add_argument("--max-paginas", type=int, default=None, help="limita páginas por site")
    ap.add_argument("--log-file", default="bot.log", help="arquivo de log (vazio p/ só console)")
    ap.add_argument("--relatorio", default="relatorio.json", help="relatório JSON do ciclo")
    args = ap.parse_args()

    log.configurar(arquivo=args.log_file or None)

    if not (args.once or args.loop):
        args.once = True

    if args.max_paginas is not None and args.max_paginas < 1:
        ap.error("--max-paginas deve ser positivo")
    try:
        config = carregar_config(args.config)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        ap.error(str(exc))
    tg = montar_telegram(config, args.dry_run)
    storage = Storage(config.get("db", "imoveis.db"))

    try:
        if args.once:
            executar_ciclo(config, storage, tg, args)
        else:
            intervalo = config.get("agendamento", {}).get("intervalo_minutos", 180)
            _log.info("Modo loop: a cada %s min. Ctrl+C para parar.", intervalo)
            while True:
                try:
                    executar_ciclo(config, storage, tg, args)
                except RuntimeError as exc:
                    _log.error("Ciclo falhou: %s", exc)
                _log.info("Dormindo %s min...", intervalo)
                time.sleep(intervalo * 60)
    except RuntimeError as exc:
        _log.error("Ciclo falhou: %s", exc)
        return 1
    except KeyboardInterrupt:
        _log.info("Encerrado pelo usuário.")
    finally:
        storage.fechar()


if __name__ == "__main__":
    sys.exit(main())
