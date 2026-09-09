"""
tools/telegram_chat_id.py
Descobre o chat_id (canal/grupo/privado) a partir do TELEGRAM_TOKEN.
Roda no GitHub Actions (workflow "descobrir-chat-id") — o token vem do secret,
não precisa colar em lugar nenhum.

Antes de rodar: publique/mande uma mensagem QUALQUER no canal ou grupo alvo,
e garanta que o bot é ADMIN lá.
"""
import json
import os
import sys
import urllib.request

API = "https://api.telegram.org/bot{tok}/{method}"


def _get(tok, method):
    with urllib.request.urlopen(API.format(tok=tok, method=method), timeout=20) as r:
        return json.load(r)


def main():
    tok = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if not tok:
        sys.exit("Falta o secret TELEGRAM_TOKEN.")

    me = _get(tok, "getMe")
    if not me.get("ok"):
        sys.exit(f"Token inválido: {me}")
    print(f"Bot: @{me['result'].get('username')}  (id {me['result'].get('id')})\n")

    wh = _get(tok, "getWebhookInfo").get("result", {})
    if wh.get("url"):
        print(f"[!] Há um webhook configurado ({wh['url']}).")
        print("    Isso deixa o getUpdates vazio. Rode uma vez:")
        print(f"    https://api.telegram.org/bot<TOKEN>/deleteWebhook\n")

    ups = _get(tok, "getUpdates").get("result", [])
    if not ups:
        print("Nenhum update. Faça assim:")
        print(" 1. confirme que o bot é ADMIN do canal/grupo;")
        print(" 2. publique uma mensagem nova nesse canal/grupo AGORA;")
        print(" 3. rode este workflow de novo em seguida.")
        return

    vistos = {}
    for u in ups:
        for k in ("channel_post", "edited_channel_post", "message",
                  "edited_message", "my_chat_member", "chat_member"):
            if k in u and "chat" in u[k]:
                c = u[k]["chat"]
                vistos[c["id"]] = (c.get("type"), c.get("title") or c.get("username")
                                   or c.get("first_name") or "")
    print("Chats encontrados:\n")
    for cid, (tipo, nome) in vistos.items():
        marca = "  <-- provável alvo" if str(cid).startswith("-100") else ""
        print(f"  TELEGRAM_CHAT_ID = {cid}   ({tipo}: {nome}){marca}")
    print("\nCopie o número (com o '-') pro secret TELEGRAM_CHAT_ID.")


if __name__ == "__main__":
    main()
