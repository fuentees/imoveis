"""
log.py
Logging simples e centralizado: escreve no console E num arquivo (bot.log por
padrão), com timestamp.

- cada módulo faz `log = log.get(__name__)` (sem efeito colateral no import);
- o programa chama `log.configurar(...)` uma vez, cedo, no main.
Sem `configurar()`, o logging padrão do Python só mostra WARNING+ no stderr
(suficiente para testes e uso como biblioteca).
"""
import logging
import sys


class _StreamHandlerTolerante(logging.StreamHandler):
    """
    Como o StreamHandler padrão, mas se o console não conseguir codificar um
    caractere (cp1252 do Windows + emoji do alerta), reescreve a linha com
    escapes em vez de derrubar o programa.
    """

    def emit(self, record):
        try:
            super().emit(record)
        except UnicodeEncodeError:
            try:
                msg = self.format(record)
                enc = getattr(self.stream, "encoding", None) or "ascii"
                self.stream.write(msg.encode(enc, "backslashreplace").decode(enc))
                self.stream.write(self.terminator)
                self.flush()
            except Exception:
                self.handleError(record)


def configurar(nivel=logging.INFO, arquivo="bot.log"):
    """(Re)configura o logging raiz: console tolerante a unicode + arquivo."""
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S")
    root = logging.getLogger()
    for h in list(root.handlers):          # idempotente: limpa o que já existia
        root.removeHandler(h)
        h.close()
    root.setLevel(nivel)

    stream = sys.stdout
    try:
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, ValueError):
        pass
    ch = _StreamHandlerTolerante(stream)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    if arquivo:
        try:
            fh = logging.FileHandler(arquivo, encoding="utf-8")
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except OSError:
            pass  # sem permissão de escrita -> segue só no console


def get(nome: str) -> logging.Logger:
    """Logger do módulo. Não configura nada por conta própria."""
    return logging.getLogger(nome)
