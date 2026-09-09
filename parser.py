"""
parser.py
Normaliza texto bruto de anúncio (formato brasileiro) em números.
Lida com: "R$ 1.250.000,00", "R$ 1,2 milhão", "120 m²", "3 quartos", "2 vagas".
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


# ---------------------------------------------------------------------------
# PREÇO
# ---------------------------------------------------------------------------
# "mil"/"k" e "milhão/milhões". A ordem importa: 'milh...' ANTES de 'mil',
# senão o 'mil' casa com o começo de "milhão" e R$ 1,2 milhão vira R$ 1.200.
_MILHAO = r"milh(?:[aã]o|[oõ]es|ao|oes)"
_MIL = r"(?:mil|k)\b"

# Rótulo de taxa que aparece ANTES do valor ("Condomínio R$ 850", "IPTU R$ 300").
# Fica de fora "financi..."/"entrada"/"parcela" de propósito: costumam aparecer
# coladas no próprio preço de venda.
_FEE_ANTES = re.compile(r"condom|cond\.|iptu|taxa|alug|loca[çc]", re.IGNORECASE)
# Marca de aluguel que aparece DEPOIS do valor ("R$ 2.500/mês", "R$ 3.000 mensais").
_FEE_DEPOIS = re.compile(r"^\s*(?:/\s*m[êe]s|por\s+m[êe]s|ao\s+m[êe]s|mensa|/\s*m[êe])",
                         re.IGNORECASE)


def _taxa_ctx(t: str, ini: int, fim: int) -> bool:
    """True se o valor em [ini:fim] parece ser condomínio/IPTU/taxa/aluguel."""
    antes = t[max(0, ini - 18):ini]
    depois = t[fim:fim + 10]
    return bool(_FEE_ANTES.search(antes) or _FEE_DEPOIS.search(depois))


def parse_preco(texto: str):
    """
    Extrai o preço de VENDA do texto.

    - "R$ 1.250.000,00" -> 1250000.0
    - "R$ 480 mil" / "R$ 480k" -> 480000.0
    - "R$ 1,2 milhão" / "1.2 milhões" -> 1200000.0
    - ignora condomínio, IPTU, taxas e aluguel ("R$ 2.500/mês").

    Estratégia: coleta TODOS os valores plausíveis com o contexto de cada um e
    devolve o MAIOR. O preço de venda é quase sempre o maior número em reais do
    anúncio; condomínio/IPTU/aluguel são menores. Só cai para "o maior valor
    limpo" se o maior de todos estiver, ele próprio, num contexto de taxa.
    Retorna None se não houver valor de venda plausível.
    """
    if not texto:
        return None
    t = texto.replace("\xa0", " ")
    candidatos = []  # (valor, taxa?)

    # "480 mil" / "1,2 milhão" / "480k"
    for m in re.finditer(rf"r?\$?\s*([\d.,]+)\s*({_MILHAO}|{_MIL})", t, re.IGNORECASE):
        num = _num_br(m.group(1))
        if num is None:
            continue
        unid = _strip_accents(m.group(2).lower())
        val = num * 1_000_000 if unid.startswith("milh") else num * 1_000
        candidatos.append((val, _taxa_ctx(t, m.start(), m.end())))

    # valor cheio "R$ 1.250.000,00"
    for m in re.finditer(r"r\$\s*([\d.]+(?:,\d{2})?)", t, re.IGNORECASE):
        v = _num_br(m.group(1))
        if v is not None and v >= 1_000:
            candidatos.append((v, _taxa_ctx(t, m.start(), m.end())))

    # último recurso: número grande com separador de milhar, sem "R$"
    if not candidatos:
        for m in re.finditer(r"(\d{1,3}(?:\.\d{3})+(?:,\d{2})?)", t):
            v = _num_br(m.group(1))
            if v is not None and v >= 10_000:
                candidatos.append((v, _taxa_ctx(t, m.start(), m.end())))

    if not candidatos:
        return None
    candidatos.sort(reverse=True)          # maior valor primeiro
    maior_val, maior_taxa = candidatos[0]
    if not maior_taxa:
        return maior_val
    limpos = [v for v, taxa in candidatos if not taxa]
    return max(limpos) if limpos else None


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


# ---------------------------------------------------------------------------
# ÁREA
# ---------------------------------------------------------------------------
_AREA_UNID = r"(?:m2|m²|metros?|mts?)"
_TERRENO_CTX = r"terreno|lote|area total|area do lote|do lote"


def parse_area(texto: str):
    """
    Extrai metragem em m². '120 m²' / '120m2' / '120 metros' -> 120.0

    Pula ocorrências cujo contexto imediato fala em terreno/lote/área total:
    "560 m² de terreno" -> None (não serve para comparar preço/m² de construção).
    """
    if not texto:
        return None
    t = _strip_accents(texto.lower())
    for m in re.finditer(rf"([\d.,]+)\s*{_AREA_UNID}\b", t):
        antes = t[max(0, m.start() - 16):m.start()]
        # só o trecho ATÉ o próximo separador conta como "depois" deste número
        depois = re.split(r"[,;/•|]", t[m.end():m.end() + 16])[0]
        if re.search(_TERRENO_CTX, antes) or re.search(_TERRENO_CTX, depois):
            continue
        v = _num_br(m.group(1))
        if v:
            return v
    return None


def parse_area_construida(texto: str):
    """
    Metragem CONSTRUÍDA / útil - a que interessa pra comparar preço/m².
    Ignora "área do terreno" / "área total do lote". Cai pra parse_area()
    genérico só se não achar nada rotulado.
    'Casa ... 855,00 m² área construída ... 1.000 m² área total' -> 855.0
    """
    if not texto:
        return None
    t = _strip_accents(texto.lower())
    # número ANTES do rótulo: "855 m² area construida" / "120m² util"
    m = re.search(rf"([\d.,]+)\s*{_AREA_UNID}?\s*(?:de\s+)?"
                  r"(?:area\s+)?(?:constru[ií]da|util|privativa)", t)
    if m:
        v = _num_br(m.group(1))
        if v:
            return v
    # número DEPOIS do rótulo: "area construida: 120 m²"
    m = re.search(rf"(?:area\s+)?(?:constru[ií]da|util|privativa)\D{{0,12}}"
                  rf"([\d.,]+)\s*{_AREA_UNID}?", t)
    if m:
        v = _num_br(m.group(1))
        if v:
            return v
    # sem rótulo: pega o menor "X m²" que NÃO esteja colado em terreno/lote/
    # total NEM em preço ("valor do m² R$ 3.250" não é uma área!).
    cands = []
    for mm in re.finditer(rf"([\d.,]+)\s*{_AREA_UNID}\b", t):
        antes = t[max(0, mm.start() - 30):mm.start()]
        depois = t[mm.end():mm.end() + 20]
        if re.search(r"terreno|lote|area total", antes + depois):
            continue
        if re.search(r"r\$|valor do m|pre[çc]o|/\s*$", antes):
            continue
        v = _num_br(mm.group(1))
        if v and 5 <= v <= 20000:      # área plausível de imóvel
            cands.append(v)
    if cands:
        return cands[0]                # 1ª área não-terreno (não a menor)
    # nada de área construída/útil E todo "m²" era de terreno -> sem info
    # (retorna None de propósito: não dá pra comparar preço/m² de terreno
    #  com preço/m² de área construída).
    return None


_TIPOS = [
    ("cobertura", "cobertura"), ("apartamento", "apartamento"), ("apto", "apartamento"),
    ("casa de condominio", "casa"), ("casa em condominio", "casa"),
    ("sobrado", "sobrado"), ("casa", "casa"), ("kitnet", "kitnet"),
    ("kitchenette", "kitnet"), ("studio", "studio"), ("loft", "loft"),
    ("terreno", "terreno"), ("lote", "terreno"), ("chacara", "chacara"),
    ("sala comercial", "sala"), ("galpao", "galpao"), ("loja", "loja"),
]


def parse_tipo(texto: str):
    """Detecta o tipo do imóvel a partir do título/descrição. '' se não achar."""
    if not texto:
        return ""
    t = _strip_accents(texto.lower())
    for chave, tipo in _TIPOS:
        if chave in t:
            return tipo
    return ""


def titulo_curto(texto: str, limite: int = 90):
    """
    Faz um título apresentável quando o site não tem seletor de título e
    a gente só tem o texto do card. Tira código no começo ('CA0139-SISJ '),
    corta antes das specs ('... 400 m² 4 Quartos...') e da localização.
    """
    s = re.sub(r"\s+", " ", (texto or "").strip())
    s = re.sub(r"^[A-Z]{2,6}[\d.-]{2,10}[-\s]+", "", s)     # código "CA0139-"
    s = re.sub(r"^[A-Z]{2,6}\s+(?=[A-Z][a-zà-ÿ])", "", s)   # sigla solta "SISJ "
    s = re.split(r"\s+[-–]\s+[A-Za-zÀ-ÿ]", s)[0]            # antes de " - Cidade"
    s = re.split(rf"\s+\d[\d.,]*\s*{_AREA_UNID}\b", s)[0]   # antes de "400 m²"
    s = s.strip(" -–,")
    return s[:limite] if s else (texto or "")[:limite]


_ATE_TIPO = re.compile(
    r"^.*?\b(?:casa|apartamento|apto|cobertura|sobrado|terreno|lote|kitnet|"
    r"kitchenette|studio|loft|sala|salao|galpao|chacara|flat|duplex|triplex)"
    r"(?:\s+(?:de|em)\s+condominio)?\b\s+", re.IGNORECASE)


def _limpa_local(s: str):
    s = re.sub(r"\s+", " ", (s or "").strip(" ,-/–"))
    s = re.sub(r"^[A-Z]{2,6}\d{1,6}[-\s]+", "", s)   # tira código "CA0139-"
    s = _ATE_TIPO.sub("", s).strip(" ,-/–")          # "SISJ Casa Jardim X" -> "Jardim X"
    if not s or len(s) > 40 or re.search(r"\d", s):
        return ""
    if len(s.split()) > 5:
        return ""
    baixo = _strip_accents(s.lower())
    if baixo in ("sp", "brasil", "sao paulo") or "imovel" in baixo or "venda" in baixo:
        return ""
    return s


def _bairro_cidade_do_slug(url: str):
    """'...-sp-mongagua-vila-atlantica-RS460000/...' -> ('Mongagua', 'Vila Atlantica')"""
    m = re.search(r"[-/]sp[-/]([a-z]+(?:-[a-z]+){0,5}?)[-/](?:rs\d|id[-/])", url.lower())
    if not m:
        return "", ""
    toks = m.group(1).split("-")
    return toks[0].capitalize(), " ".join(toks[1:]).title()


def parse_local(texto: str, url: str = ""):
    """
    Tenta extrair (cidade, bairro) do texto do anúncio. Cobre os formatos
    comuns das imobiliárias BR:
      'Jardim Acapulco - Guarujá - SP'   'Vila Atlântica - Mongaguá / SP'
      'Rua X - Bal Stella Maris, Peruíbe-SP'   'Centro, Itanhaém-SP'
    Cai pro slug da URL quando o texto não ajuda. ('', '') se sem confiança.
    """
    t = re.sub(r"\s+", " ", texto or "")
    cidade = bairro = ""

    padroes = [
        r"([A-Za-zÀ-ÿ][\wÀ-ÿ .'()]{2,38}?)\s*[-–/]\s*"
        r"([A-Za-zÀ-ÿ][\wÀ-ÿ .']{2,32}?)\s*[-–/]\s*SP\b",
        r"([A-Za-zÀ-ÿ][\wÀ-ÿ .'()]{2,38}?)\s*,\s*"
        r"([A-Za-zÀ-ÿ][\wÀ-ÿ .']{2,32}?)\s*[-–/]\s*SP\b",
    ]
    for pat in padroes:
        for m in re.finditer(pat, t):
            b = _limpa_local(m.group(1).split(" - ")[-1])
            c = _limpa_local(m.group(2))
            if c:
                cidade, bairro = c, b
                break
        if cidade:
            break

    c_u, b_u = _bairro_cidade_do_slug(url)
    return (cidade or c_u, bairro or b_u)


# ---------------------------------------------------------------------------
# QUARTOS / VAGAS
# ---------------------------------------------------------------------------
def parse_quartos(texto: str):
    """
    Extrai nº de quartos/dormitórios. Considera também "suíte(s)" e devolve o
    MAIOR número rotulado — "1 suíte e 3 dormitórios" -> 3 (e não 1, nem 4).
    """
    if not texto:
        return None
    t = _strip_accents(texto.lower())
    nums = [int(n) for n in re.findall(
        r"(\d+)\s*(?:quartos?|dormitorios?|dorms?\b|qtos?\b|qts?\b)", t)]
    nums += [int(n) for n in re.findall(r"(\d+)\s*su[ií]te?s?\b", t)]
    nums = [n for n in nums if 0 < n <= 20]
    return max(nums) if nums else None


def parse_vagas(texto: str):
    if not texto:
        return None
    t = _strip_accents(texto.lower())
    m = re.search(r"(\d+)\s*(?:vagas?|garagem|garagens)", t)
    if m:
        return int(m.group(1))
    return None
