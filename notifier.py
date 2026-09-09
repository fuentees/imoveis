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


def formatar_alerta(im) -> str:
    """Monta a mensagem de um imóvel. Usa HTML simples suportado pelo Telegram."""
    def fmt_reais(v):
        return f"R$ {v:,.0f}".replace(",", ".") if v else "—"

    linhas = []
    linhas.append(f"🏠 <b>{html.escape(im.titulo[:90])}</b>")
    linhas.append(f"📍 {html.escape(im.bairro or '?')}, {html.escape(im.cidade or '?')}")
    linhas.append(f"💰 <b>{fmt_reais(im.preco)}</b>  •  {im.area:.0f} m²  •  {im.quartos or '?'} quartos"
                  if im.area else f"💰 <b>{fmt_reais(im.preco)}</b>")
    if im.preco_m2:
        linhas.append(f"📐 {fmt_reais(im.preco_m2)}/m²")
    if im.mediana_grupo and im.pct_abaixo > 0:
        linhas.append(f"📉 <b>{im.pct_abaixo*100:.0f}% abaixo</b> da mediana do grupo "
                      f"({fmt_reais(im.mediana_grupo)}/m², n={im.n_grupo})")
    if im.keywords:
        linhas.append(f"🔑 {', '.join(im.keywords)}")
    linhas.append(f"⭐ score {im.score}  •  fonte: {html.escape(im.fonte)}")
    linhas.append(f"🔗 {html.escape(im.url)}")
    return "\n".join(linhas)
