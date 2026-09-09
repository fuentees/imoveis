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

import log
from scraper import raspar_todos
from analyzer import analisar, comps_do_historico
from storage import Storage
from notifier import Telegram, formatar_alerta

_log = log.get(__name__)


def carregar_config(caminho):
    with open(caminho, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _deve_realertar(im, preco_anterior, queda_min):
    """
    Já alertamos esse imóvel antes. Só vale re-alertar se o preço caiu pelo
    menos `queda_min` (0.10 = 10%) em relação ao preço do último alerta.
    """
    if not (preco_anterior and im.preco):
        return False
    return im.preco <= preco_anterior * (1 - queda_min)


def rodar_ciclo(config, storage, tg, dry_run=False, max_paginas=None):
    _log.info("==== Novo ciclo: %s ====", time.strftime("%Y-%m-%d %H:%M:%S"))

    imoveis = raspar_todos(config, max_paginas=max_paginas)
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
        preco_min=a.get("preco_min", 50_000),
        preco_m2_min=a.get("preco_m2_min", 300),
        preco_m2_max=a.get("preco_m2_max", 60_000),
        historico=historico,
    )
    _log.info("Oportunidades detectadas: %s", len(ops))

    # persiste tudo que viu (histórico ajuda a calibrar a mediana nos próximos ciclos)
    for im in imoveis:
        if im.preco_m2:
            storage.upsert_imovel(im)

    queda_min = a.get("realerta_queda", 0.10)
    novos = enviados = falhas = 0
    for im in ops:
        info = storage.info_alerta(im.url)
        if info is not None:
            preco_ant, _ = info
            if not _deve_realertar(im, preco_ant, queda_min):
                continue
            _log.info("re-alerta (preço caiu): %s  %s -> %s",
                      im.url[-50:], preco_ant, im.preco)
        novos += 1
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
        _log.info("Alertas novos: %s  |  enviados: %s  |  falharam: %s",
                  novos, enviados, falhas)
    return novos


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
    ap.add_argument("--once", action="store_true", help="roda um ciclo e sai")
    ap.add_argument("--loop", action="store_true", help="roda em loop contínuo")
    ap.add_argument("--dry-run", action="store_true", help="não envia Telegram, só imprime")
    ap.add_argument("--max-paginas", type=int, default=None, help="limita páginas por site")
    ap.add_argument("--log-file", default="bot.log", help="arquivo de log (vazio p/ só console)")
    args = ap.parse_args()

    log.configurar(arquivo=args.log_file or None)

    if not (args.once or args.loop):
        args.once = True

    config = carregar_config(args.config)
    storage = Storage(config.get("db", "imoveis.db"))
    tg = montar_telegram(config, args.dry_run)

    try:
        if args.once:
            rodar_ciclo(config, storage, tg, args.dry_run, args.max_paginas)
        else:
            intervalo = config.get("agendamento", {}).get("intervalo_minutos", 180)
            _log.info("Modo loop: a cada %s min. Ctrl+C para parar.", intervalo)
            while True:
                rodar_ciclo(config, storage, tg, args.dry_run, args.max_paginas)
                _log.info("Dormindo %s min...", intervalo)
                time.sleep(intervalo * 60)
    except KeyboardInterrupt:
        _log.info("Encerrado pelo usuário.")
    finally:
        storage.fechar()


if __name__ == "__main__":
    main()
