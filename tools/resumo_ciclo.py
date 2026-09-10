"""Resumo legível do ciclo, usado na página de execução do GitHub Actions."""
import json
from pathlib import Path


def formatar(dados):
    linhas = ["## Monitor de imóveis", "",
              f"Início (UTC): {dados.get('inicio', 'não iniciado')}", "",
              f"Anúncios: **{dados.get('anuncios', 0)}** · Oportunidades: **{dados.get('oportunidades', 0)}** · Enviados: **{dados.get('enviados', 0)}** · Falhas de envio: **{dados.get('falhas_envio', 0)}**", ""]
    if dados.get("erro"):
        linhas += [f"**Falha:** {dados['erro']}", ""]
    linhas += ["### Cobertura nesta execução", "", "| Cidade | Anúncios |", "| --- | ---: |"]
    for cidade, total in sorted(dados.get("por_cidade", {}).items()):
        linhas.append(f"| {cidade} | {total} |")
    linhas += ["", "### Fontes", "", "| Fonte | Estado | Páginas | Anúncios | Com preço e área |", "| --- | --- | ---: | ---: | ---: |"]
    for fonte in dados.get("fontes", []):
        nome = fonte["nome"].replace("|", "/")
        linhas.append(f"| {nome} | {fonte.get('status', 'desconhecido')} | {fonte.get('paginas', 0)} | {fonte.get('anuncios', 0)} | {fonte.get('com_preco_area', 0)} |")
    linhas += ["", "`limite_paginas` significa coleta parcial: aumente paginas na configuração para ampliar. Zero alertas novos pode ser normal; consulte os totais de coleta e as falhas acima."]
    return "\n".join(linhas)


if __name__ == "__main__":
    path = Path("relatorio.json")
    if path.exists():
        print(formatar(json.loads(path.read_text(encoding="utf-8"))))
    else:
        print("## Monitor de imóveis\n\nO ciclo não produziu relatório. Confira as etapas de preparação e execução.")
