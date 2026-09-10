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
import time
import requests

import log

_log = log.get(__name__)


class Telegram:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base = f"https://api.telegram.org/bot{token}"

    def enviar(self, texto_html: str) -> bool:
        # O Telegram impõe um limite por chat. Quando ele informa retry_after,
        # aguardar esse período preserva o alerta em vez de descartá-lo.
        for tentativa in range(3):
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
                corpo = r.json()
                if r.status_code == 200 and corpo.get("ok") is True:
                    return True
                retry_after = corpo.get("parameters", {}).get("retry_after")
                if r.status_code == 429 and retry_after and tentativa < 2:
                    espera = min(max(int(retry_after) + 1, 1), 90)
                    _log.info("  Telegram pediu uma pausa de %ss; tentando novamente.", espera)
                    time.sleep(espera)
                    continue
                _log.warning("  [!] Telegram respondeu %s: %s", r.status_code, r.text[:200])
                return False
            except Exception as e:
                _log.warning("  [!] Falha ao enviar Telegram: %s", type(e).__name__)
                return False
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
        return f"confiança boa ({n} comparáveis)"
    if n >= 8:
        return f"confiança razoável ({n} comparáveis)"
    return f"amostra pequena — só {n} comparáveis, confirme com calma"


def _faixa(lo, hi):
    """(7000, 9500) -> 'R$ 7.000–9.500/m²'."""
    if not (lo and hi):
        return ""
    ini = _reais(lo)
    fim = _reais(hi).replace("R$ ", "")
    return f"{ini}–{fim}/m²"


def formatar_alerta(im) -> str:
    """
    Mensagem do Telegram (HTML). A DIFERENÇA DE VALOR é a manchete (primeira
    linha, em destaque); o resto — imóvel, specs, confiança, ressalva — vem
    embaixo. Dá pra decidir "abro ou não" só pela primeira linha.
    """
    E = html.escape
    tipo = (im.tipo or "Imóvel").capitalize()
    local = ", ".join(p for p in (im.bairro, im.cidade) if p) or "local não identificado"
    L = []

    # ---- MANCHETE: a diferença ----
    tem_gap = bool(im.mediana_grupo) and im.pct_abaixo > 0
    if tem_gap:
        econ = (im.mediana_grupo - im.preco_m2) * (im.area or 0)
        cabeca = f"🔻 <b>{im.pct_abaixo * 100:.0f}% ABAIXO</b> do preço/m² típico"
        if econ > 0:
            cabeca += f"  ·  ≈ <b>{_reais(econ)}</b> mais barato"
        L.append(cabeca)
        faixa = _faixa(im.faixa_lo, im.faixa_hi)
        alvo = f"típico {faixa}" if faixa else f"típico ~{_reais(im.mediana_grupo)}/m²"
        L.append(f"    este imóvel: <b>{_reais(im.preco_m2)}/m²</b>   |   {alvo}")
        if im.criterio:
            L.append(f"    base: {im.n_grupo} imóveis parecidos — <i>{E(im.criterio)}</i>")
        if im.pct_abaixo >= 0.45:
            L.append("    ⚑ <b>gap grande</b>: provável reforma pesada / permuta / "
                     "terreno — não conte com \"pronto pra morar\"")
    elif im.keywords:
        legiveis = ", ".join(_KW_LEGIVEL.get(k, k) for k in im.keywords)
        L.append(f"🔑 <b>SINAIS DE VENDA RÁPIDA</b>: {E(legiveis)}")
        L.append(f"    preço não comparável ({_confianca(im.n_grupo)})")
    L.append("")

    # ---- o imóvel ----
    L.append(f"🏠 <b>{E(tipo)} · {E(local)}</b>  —  <b>{_reais(im.preco)}</b>")
    specs = []
    if im.area:
        specs.append(f"{im.area:.0f} m²")
    if im.quartos:
        specs.append(f"{im.quartos} quartos")
    if im.vagas:
        specs.append(f"{im.vagas} vagas")
    if im.preco_m2:
        specs.append(f"{_reais(im.preco_m2)}/m²")
    if specs:
        L.append("   " + "  ·  ".join(specs))
    if im.titulo and im.titulo.strip().lower() not in (tipo.lower(), local.lower()):
        L.append(f"   <i>{E(im.titulo[:90])}</i>")
    if tem_gap and im.keywords:
        legiveis = ", ".join(_KW_LEGIVEL.get(k, k) for k in im.keywords)
        L.append(f"   🔑 ainda: {E(legiveis)}")
    L.append("")

    # ---- rodapé ----
    L.append(f"📊 {_confianca(im.n_grupo)}  ·  relevância {im.score:.0f}")
    L.append("⚠️ Preço de <i>anúncio</i>, não de venda. A base também é de anúncios "
             "(pedidos, inflados) — o gap real tende a ser menor. Confirme visitando.")
    L.append("")
    L.append(f"🔗 {E(im.url)}")
    L.append(f"<i>fonte: {E(im.fonte)}</i>")
    return "\n".join(L)
