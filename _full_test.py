import sys, time, collections, yaml
try:                                   # console do Windows (cp1252) + emoji do alerta
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
except (AttributeError, ValueError):
    pass
from scraper import raspar_todos
from analyzer import analisar, _dedupe
from notifier import formatar_alerta

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
t0 = time.time()
ims = raspar_todos(cfg, max_paginas=2)
print(f"\n=== RASPAGEM: {len(ims)} anuncios em {time.time()-t0:.0f}s ===")

dd = _dedupe(ims)
print(f"apos dedupe: {len(dd)} (removeu {len(ims)-len(dd)})")

by = collections.Counter(im.fonte for im in dd)
carea = collections.Counter(im.fonte for im in dd if im.area)
cbairro = collections.Counter(im.fonte for im in dd if im.bairro and "SP" not in im.bairro.upper())
print("\nfonte / total / c-area / c-bairro:")
for f in by:
    print(f"  {f[:40]:40} {by[f]:3} {carea[f]:3} {cbairro[f]:3}")

print("\ncidades (agregadores):",
      collections.Counter(im.cidade for im in dd if "Paulumar" in im.fonte or "M&M" in im.fonte))

a = cfg["analise"]
ops = analisar(ims, min_amostra=a["min_amostra"], limiar_desconto=a["limiar_desconto"],
               exigir_keyword=a["exigir_keyword"], preco_min=a["preco_min"],
               preco_m2_min=a["preco_m2_min"], preco_m2_max=a["preco_m2_max"])
print(f"\n=== {len(ops)} ALERTAS ===  keywords:",
      collections.Counter(k for o in ops for k in o.keywords).most_common() or "nenhuma")
for o in ops[:12]:
    tag = "B" if o.pct_abaixo >= a["limiar_desconto"] else "K"
    print(f"  [{o.score:5}] {tag} {o.fonte[:18]:18} R$ {o.preco:>11,.0f} {o.area:>4.0f}m2 "
          f"{o.preco_m2:>7,.0f}/m2 {o.pct_abaixo*100:3.0f}%<(n={o.n_grupo}) "
          f"{o.cidade}/{(o.bairro or '?')[:16]} {o.keywords}")

print("\n--- alerta formatado (top1) ---")
if ops:
    print(formatar_alerta(ops[0]))

print("FIM (diagnóstico sem alterar banco ou alertas)")
