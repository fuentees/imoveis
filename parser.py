"""
parser.py
Normaliza texto bruto de anúncio (formato brasileiro) em números.
Lida com: "R$ 1.250.000,00", "120 m²", "3 quartos", "2 vagas" etc.
"""
import re
import unicodedata


def _strip_accents(s: str) -> str:
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar_texto(s: str) -> str:
    """minúsculas, sem acento, espaços colapsados. Bom para bairro e busca de palavra-chave."""
    s = _strip_accents(s or "").lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_preco(texto: str):
    """
    Extrai o primeiro valor monetário do texto.
    'R$ 1.250.000,00' -> 1250000.0 ; 'R$ 480 mil' -> 480000.0
    Retorna None se não achar algo plausível.
    """
    if not texto:
        return None
    t = texto.replace("\xa0", " ")

    # caso "480 mil" / "1,2 milhão"
    m = re.search(r"r?\$?\s*([\d.,]+)\s*(mil|milh(?:ao|oes|ões|ao))", t, re.IGNORECASE)
    if m:
        num = _num_br(m.group(1))
        if num is not None:
            unidade = _strip_accents(m.group(2).lower())
            if unidade.startswith("mil"):
                return num * 1_000
            return num * 1_000_000

    # caso valor cheio "R$ 1.250.000,00"
    m = re.search(r"r\$\s*([\d.]+(?:,\d{2})?)", t, re.IGNORECASE)
    if m:
        return _num_br(m.group(1))

    # fallback: primeiro número grande solto
    m = re.search(r"([\d.]{4,}(?:,\d{2})?)", t)
    if m:
        v = _num_br(m.group(1))
        if v and v >= 10_000:  # evita pegar metragem por engano
            return v
    return None


def _num_br(s: str):
    """'1.250.000,00' -> 1250000.0 ; '480' -> 480.0 ; '1,2' -> 1.2"""
    if not s:
        return None
    s = s.strip()
    # se tem vírgula, ela é o decimal e ponto é milhar
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        # só pontos: se parecem milhar (grupos de 3), remove; senão trata como decimal
        if re.match(r"^\d{1,3}(\.\d{3})+$", s):
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_area(texto: str):
    """Extrai metragem em m². '120 m²' / '120m2' / '120 metros' -> 120.0"""
    if not texto:
        return None
    t = _strip_accents(texto.lower())
    m = re.search(r"([\d.,]+)\s*(?:m2|m²|metros?|mts?)\b", t)
    if m:
        return _num_br(m.group(1))
    return None


def parse_quartos(texto: str):
    """Extrai nº de quartos/dormitórios."""
    if not texto:
        return None
    t = _strip_accents(texto.lower())
    m = re.search(r"(\d+)\s*(?:quartos?|dorm|dormitorios?|suites?\b.*)", t)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*qto", t)
    if m:
        return int(m.group(1))
    return None


def parse_vagas(texto: str):
    if not texto:
        return None
    t = _strip_accents(texto.lower())
    m = re.search(r"(\d+)\s*(?:vagas?|garagem|garagens)", t)
    if m:
        return int(m.group(1))
    return None
