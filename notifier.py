"""
notifier.py
Envia alertas pelo Telegram usando a Bot API (sem dependência extra além de requests).

Como obter as credenciais:
 1. No Telegram, fale com @BotFather -> /newbot -> ele te dá o TOKEN.
 2. Mande qualquer mensagem para o seu bot.
 3. Pegue o chat_id acessando:
    https://api.telegram.org/bot<TOKEN>/getUpdates
    e procure "chat":{"id": ...}.  (ou use @userinfobot)
"""
import html
import requests

import log

_log = log.get(__name__)


class Telegram:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base = f"https://api.telegram.org/bot{token}"

    def enviar(self, texto_html: str) -> bool:
        try:
            # json= (não data=) pra o booleano ir como booleano de verdade;
            # como string "false" a API tratava como "ativar" e sumia com a
            # prévia do link (a foto do imóvel).
            r = requests.post(f"{self.base}/sendMessage", json={
                "chat_id": self.chat_id,
                "text": texto_html,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            }, timeout=20)
            if r.status_code != 200:
                _log.warning("  [!] Telegram respondeu %s: %s", r.status_code, r.text[:200])
            return r.status_code == 200
        except Exception as e:
            _log.warning("  [!] Falha ao enviar Telegram: %s", e)
            return False


# palavra-chave normalizada -> forma legível (com acento) pro alerta
_KW_LEGIVEL = {
    "espolio": "espólio", "inventario": "inventário", "heranca": "herança",
    "aceito proposta": "aceita proposta", "aceita proposta": "aceita proposta",
    "aceito oferta": "aceita oferta",
    "abaixo da avaliacao": "abaixo da avaliação",
    "motivo mudanca": "mudança", "mudanca de cidade": "mudança de cidade",
    "mudanca de pais": "mudança de país",
    "preciso vender": "precisa vender", "vende-se rapido": "venda rápida",
    "venda rapida": "venda rápida", "documentacao ok": "documentação ok",
}


def _reais(v, casas=0):
    """1600000 -> 'R$ 1.600.000' (formato brasileiro)."""
    if not v:
        return "—"
    s = f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def _confianca(n):
    if n <= 0:
        return "sem comparação de preço (poucos imóveis parecidos)"
    if n >= 15:
        return f"{n} imóveis parecidos na base — confiança boa"
    if n >= 8:
        return f"{n} imóveis parecidos — confiança razoável"
    return f"só {n} imóveis parecidos — amostra pequena, confirme com calma"


def formatar_alerta(im) -> str:
    """
    Monta a mensagem do Telegram (HTML). Objetivo: dá pra entender em 5 segundos
    POR QUE isso é um alerta, quão confiável é, e o que ainda falta checar.
    """
    E = html.escape
    tipo = (im.tipo or "Imóvel").capitalize()
    local = ", ".join(p for p in (im.bairro, im.cidade) if p) or "local não identificado"

    L = [f"🏠 <b>{E(tipo)} · {E(local)}</b>"]
    if im.titulo and im.titulo.strip().lower() not in (tipo.lower(), local.lower()):
        L.append(f"<i>{E(im.titulo[:90])}</i>")
    L.append("")

    # specs
    specs = [f"<b>{_reais(im.preco)}</b>"]
    if im.area:
        specs.append(f"{im.area:.0f} m²")
    if im.quartos:
        specs.append(f"{im.quartos} quartos")
    if im.vagas:
        specs.append(f"{im.vagas} vagas")
    L.append("   ·   ".join(specs))
    if im.preco_m2:
        L.append(f"📐 {_reais(im.preco_m2)}/m²")
    L.append("")

    # por que virou alerta
    if im.mediana_grupo and im.pct_abaixo > 0:
        L.append(f"📉 <b>{im.pct_abaixo * 100:.0f}% abaixo</b> do preço/m² típico da região")
        L.append(f"    este: {_reais(im.preco_m2)}/m²   ·   típico: ~{_reais(im.mediana_grupo)}/m²")
        econ = (im.mediana_grupo - im.preco_m2) * (im.area or 0)
        if econ > 0:
            L.append(f"    ≈ {_reais(econ)} mais barato que o típico de imóveis parecidos")
        if im.criterio:
            L.append(f"    <i>base de comparação: {E(im.criterio)}</i>")
    elif im.keywords:
        L.append("📉 Não está claramente abaixo do mercado — "
                 "entrou pelos <b>sinais de venda abaixo</b>.")
    L.append("")

    if im.keywords:
        legiveis = ", ".join(_KW_LEGIVEL.get(k, k) for k in im.keywords)
        L.append(f"🔑 <b>Sinais de venda rápida:</b> {E(legiveis)}")
        L.append("")

    L.append(f"📊 {_confianca(im.n_grupo)}  ·  relevância {im.score:.0f}")
    L.append("⚠️ Preço de <i>anúncio</i>, não de venda. O bot só encurta a busca — confirme visitando.")
    L.append("")
    L.append(f"🔗 {E(im.url)}")
    L.append(f"<i>fonte: {E(im.fonte)}</i>")
    return "\n".join(L)
