"""
main.py  -  orquestrador do bot.

Uso:
    python3 main.py --once            # roda uma vez e sai
    python3 main.py --loop            # roda continuamente no intervalo do config
    python3 main.py --once --dry-run  # não envia Telegram, só imprime (calibração)
    python3 main.py --max-paginas 1   # limita páginas (teste rápido)

Credenciais do Telegram: via config.yaml OU variáveis de ambiente
    TELEGRAM_TOKEN / TELEGRAM_CHAT_ID  (ambiente tem prioridade).
"""
import os
import sys
import time
import argparse
import yaml

from scraper import raspar_todos
from analyzer import analisar
from storage import Storage
from notifier import Telegram, formatar_alerta


def carregar_config(caminho):
    with open(caminho, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def rodar_ciclo(config, storage, tg, dry_run=False, max_paginas=None):
    print("\n==== Novo ciclo:", time.strftime("%Y-%m-%d %H:%M:%S"), "====")

    imoveis = raspar_todos(config, max_paginas=max_paginas)
    print(f"\nTotal raspado: {len(imoveis)} anúncios")

    a = config.get("analise", {})
    ops = analisar(
        imoveis,
        min_amostra=a.get("min_amostra", 4),
        limiar_desconto=a.get("limiar_desconto", 0.30),
        exigir_keyword=a.get("exigir_keyword", False),
        preco_min=a.get("preco_min", 50_000),
        preco_m2_min=a.get("preco_m2_min", 300),
        preco_m2_max=a.get("preco_m2_max", 60_000),
    )
    print(f"Oportunidades detectadas: {len(ops)}")

    # persiste tudo que viu (histórico ajuda a calibrar mediana no futuro)
    for im in imoveis:
        if im.preco_m2:
            storage.upsert_imovel(im)

    novos = enviados = falhas = 0
    for im in ops:
        if storage.ja_alertado(im.url):
            continue
        novos += 1
        msg = formatar_alerta(im)
        if dry_run:
            print("\n--- (dry-run, não enviado) ---")
            print(msg)
            continue
        if tg and tg.enviar(msg):
            storage.marcar_alertado(im.url, im.score)   # só marca se enviou
            enviados += 1
        else:
            falhas += 1        # não marca: tenta de novo no próximo ciclo
        time.sleep(1)          # respeita rate limit do Telegram

    if dry_run:
        print(f"\nAlertas novos (dry-run): {novos}")
    else:
        print(f"\nAlertas novos: {novos}  |  enviados: {enviados}  |  falharam: {falhas}")
    return novos


def montar_telegram(config, dry_run):
    if dry_run:
        return None
    token = os.environ.get("TELEGRAM_TOKEN") or config.get("telegram", {}).get("token")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or config.get("telegram", {}).get("chat_id")
    if not token or not chat_id:
        print("[!] Sem TELEGRAM_TOKEN/CHAT_ID. Rode com --dry-run ou configure as credenciais.")
        sys.exit(1)
    return Telegram(token, chat_id)


def main():
    ap = argparse.ArgumentParser(description="Bot garimpeiro de imóveis")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--once", action="store_true", help="roda um ciclo e sai")
    ap.add_argument("--loop", action="store_true", help="roda em loop contínuo")
    ap.add_argument("--dry-run", action="store_true", help="não envia Telegram, só imprime")
    ap.add_argument("--max-paginas", type=int, default=None, help="limita páginas por site")
    args = ap.parse_args()

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
            print(f"Modo loop: a cada {intervalo} min. Ctrl+C para parar.")
            while True:
                rodar_ciclo(config, storage, tg, args.dry_run, args.max_paginas)
                print(f"\nDormindo {intervalo} min...")
                time.sleep(intervalo * 60)
    except KeyboardInterrupt:
        print("\nEncerrado pelo usuário.")
    finally:
        storage.fechar()


if __name__ == "__main__":
    main()
