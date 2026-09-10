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
import os
import sys
import time
import argparse
import yaml
import json
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone

import log
from scraper import raspar_todos
from analyzer import analisar, comps_do_historico
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
                    "realerta_queda": (0, 1), "historico_dias": (0, None),
                    "max_alertas_por_ciclo": (1, None),
                    "preco_min": (0, None), "preco_m2_min": (0, None), "preco_m2_max": (0, None)},
        "scraper": {"delay_segundos": (0, None), "delay_detalhe_segundos": (0, None)},
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
    for key in ("exigir_keyword", "permitir_keyword_sem_desconto"):
        if key in config.get("analise", {}) and type(config["analise"][key]) is not bool:
            raise ValueError(f"Valor inválido: analise.{key}")
    a = config.get("analise", {})
    if a.get("preco_m2_min", 300) >= a.get("preco_m2_max", 60000):
        raise ValueError("preco_m2_min deve ser menor que preco_m2_max.")


def _deve_realertar(im, preco_anterior, queda_min):
    """
    Já alertamos esse imóvel antes. Só vale re-alertar se o preço caiu pelo
    menos `queda_min` (0.10 = 10%) em relação ao preço do último alerta.
    """
    if not (preco_anterior and im.preco):
        return False
    return im.preco <= preco_anterior * (1 - queda_min)


def rodar_ciclo(config, storage, tg, dry_run=False, max_paginas=None, relatorio=None):
    _log.info("==== Novo ciclo: %s ====", time.strftime("%Y-%m-%d %H:%M:%S"))

    relatorio = relatorio if relatorio is not None else {}
    relatorio.update(inicio=datetime.now(timezone.utc).isoformat(), dry_run=dry_run)
    imoveis = raspar_todos(config, max_paginas=max_paginas, relatorio=relatorio)
    relatorio["anuncios"] = len(imoveis)
    relatorio["por_cidade"] = dict(Counter(im.cidade for im in imoveis))
    _log.info("Total raspado: %s anúncios", len(imoveis))

    a = config.get("analise", {})
    historico = comps_do_historico(
        storage.carregar_comparaveis(dias=a.get("historico_dias", 180)))
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
    )
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
    fila = pendentes if dry_run else pendentes[:limite_alertas]
    adiados = 0 if dry_run else max(0, novos - len(fila))
    enviados = falhas = 0
    for im in fila:
        msg = formatar_alerta(im)
        if dry_run:
            _log.info("--- (dry-run, não enviado) ---\n%s", msg)
            continue
        if tg and tg.enviar(msg):
            storage.marcar_alertado(im.url, im.score, im.preco)   # só marca se enviou
            enviados += 1
        else:
            falhas += 1        # não marca: tenta de novo no próximo ciclo
        time.sleep(1)          # respeita rate limit do Telegram

    if dry_run:
        _log.info("Alertas novos (dry-run): %s", novos)
    else:
        _log.info("Alertas novos: %s  |  enviados: %s  |  adiados: %s  |  falharam: %s",
                  novos, enviados, adiados, falhas)
    relatorio.update(novos=novos, enviados=enviados, adiados=adiados,
                     falhas_envio=falhas, fim=datetime.now(timezone.utc).isoformat())
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
