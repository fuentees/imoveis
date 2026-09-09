"""
analyzer.py
O cérebro. Recebe uma lista de imóveis normalizados e devolve os que valem alerta.

Lógica:
1. Dedupe: colapsa o MESMO imóvel visto 2x (URL repetida ou reanúncio com outro código).
2. Agrupa por (cidade | bairro | tipo). Dentro do grupo, a mediana de cada imóvel
   é calculada só sobre os COMPARÁVEIS dele: área ±35% e quartos ±1. Isso evita o
   "efeito degrau" das faixas fixas (349 m² e 351 m² caíam em baldes diferentes).
3. Junta comparáveis do histórico (banco) para grupos com amostra pequena.
4. Marca candidato quem está X% ABAIXO da mediana dos próprios comparáveis.
5. Cruza com PALAVRAS-CHAVE de espólio/urgência.
6. Pontua e devolve ordenado.
"""
import re
from dataclasses import dataclass, field
from statistics import median
from typing import Optional
from parser import normalizar_texto

# Palavras que indicam venda urgente / espólio. Ajuste à vontade.
# Retiradas as fracas ("oportunidade", "financia", "abaixo do valor"...):
# apareciam em ~90% dos anúncios (é jargão de corretor) e só geravam ruído.
PALAVRAS_CHAVE = [
    "espolio", "inventario", "herdeiros", "heranca", "partilha",
    "urgente", "abaixo da avaliacao", "abaixo do mercado",
    "aceito proposta", "aceita proposta", "aceito oferta",
    "motivo mudanca", "mudanca de cidade", "mudanca de pais",
    "precisa vender", "preciso vender", "vende-se rapido", "venda rapida",
    "desocupado", "documentacao ok", "escritura ok",
]

# Abreviações comuns de bairro -> forma canônica, pra "Jd Acapulco",
# "Jardim Acapulco" e "JD. ACAPULCO" caírem no mesmo grupo. Só as inequívocas:
# "st"/"pr"/"v" ficam de fora (sítio×santo, praia×professor, vila×vale).
_BAIRRO_ABREV = [
    (r"\bjd\b\.?", "jardim"), (r"\bpq\b\.?", "parque"),
    (r"\bres\b\.?", "residencial"), (r"\bresid\b\.?", "residencial"),
    (r"\bcj\b\.?", "conjunto"), (r"\bcjto\b\.?", "conjunto"),
    (r"\bvl\b\.?", "vila"), (r"\bcond\b\.?", "condominio"),
    (r"\bbal\b\.?", "balneario"), (r"\bbaln\b\.?", "balneario"),
    (r"\bpca\b\.?", "praca"),
]

# faixas de comparação relativa
_AREA_TOL = 0.35        # comparável = área dentro de ±35%
_QUARTOS_TOL = 1        # ... e quartos com diferença de no máximo 1


@dataclass
class Imovel:
    url: str
    titulo: str = ""
    descricao: str = ""
    bairro: str = ""
    cidade: str = ""
    tipo: str = ""            # apartamento / casa / etc.
    preco: Optional[float] = None
    area: Optional[float] = None
    quartos: Optional[int] = None
    vagas: Optional[int] = None
    fonte: str = ""           # nome do site de origem

    # calculados
    preco_m2: Optional[float] = field(default=None)
    grupo: str = field(default="")
    mediana_grupo: Optional[float] = field(default=None)
    n_grupo: int = field(default=0)
    pct_abaixo: float = field(default=0.0)     # 0.35 = 35% abaixo da mediana
    keywords: list = field(default_factory=list)
    score: float = field(default=0.0)

    def texto_busca(self) -> str:
        return normalizar_texto(f"{self.titulo} {self.descricao}")


@dataclass
class Comp:
    """Comparável enxuto: o que basta para compor a mediana de um grupo."""
    grupo: str
    area: Optional[float]
    quartos: Optional[int]
    preco_m2: float
    url: str = ""


def canon_bairro(s: str) -> str:
    """normaliza + expande abreviações comuns de bairro."""
    s = normalizar_texto(s)
    for pat, rep in _BAIRRO_ABREV:
        s = re.sub(pat, rep, s)
    return re.sub(r"\s+", " ", s).strip()


def _chave(cidade: str, bairro: str, tipo: str) -> str:
    return "|".join([
        normalizar_texto(cidade),
        canon_bairro(bairro),
        normalizar_texto(tipo) or "tipo?",
    ])


def chave_grupo(im: Imovel) -> str:
    return _chave(im.cidade, im.bairro, im.tipo)


def detectar_keywords(im: Imovel) -> list:
    texto = im.texto_busca()
    return [kw for kw in PALAVRAS_CHAVE if kw in texto]


def comps_do_historico(rows) -> list:
    """
    rows: iterável de (url, cidade, bairro, tipo, area, quartos, preco_m2) vindo
    do banco. Vira uma lista de Comp para engrossar a amostra das medianas.
    """
    out = []
    for url, cidade, bairro, tipo, area, quartos, preco_m2 in rows:
        if not (area and preco_m2 and area > 0):
            continue
        out.append(Comp(_chave(cidade or "", bairro or "", tipo or ""),
                        float(area), int(quartos) if quartos else None,
                        float(preco_m2), url or ""))
    return out


def _chaves_dedupe(im: Imovel):
    """
    URL + "impressão digital" do imóvel. A digital inclui um trecho do título
    normalizado: reanúncio com outro código repete o texto; unidades diferentes
    no mesmo prédio (mesma metragem/preço) têm títulos distintos e NÃO colapsam.
    """
    chaves = ["u:" + im.url.rstrip("/")]
    if im.preco and im.area:
        titulo_norm = normalizar_texto(im.titulo or "")[:40]
        chaves.append("f:%s|%s|%s|%d|%d|%d" % (
            canon_bairro(im.bairro), normalizar_texto(im.tipo), titulo_norm,
            round(im.preco / 1000), round(im.area), im.quartos or 0,
        ))
    return chaves


def _dedupe(imoveis):
    """
    Colapsa o MESMO imóvel contando 2x: URL repetida (paginação) e o mesmo
    imóvel reanunciado com outro código. Mantém o de descrição maior.
    """
    dono = {}          # chave -> índice do representante em `saida`
    saida = []
    for im in imoveis:
        chaves = _chaves_dedupe(im)
        idx = next((dono[k] for k in chaves if k in dono), None)
        if idx is None:
            saida.append(im)
            for k in chaves:
                dono[k] = len(saida) - 1
        else:
            if len(im.descricao or "") > len(saida[idx].descricao or ""):
                saida[idx] = im
            for k in chaves:            # novas chaves apontam pro mesmo dono
                dono.setdefault(k, idx)
    return saida


def _comparaveis(im: Imovel, pool):
    """
    Do mesmo grupo, filtra por área dentro de ±_AREA_TOL e quartos com
    diferença <= _QUARTOS_TOL. O próprio imóvel entra na amostra (estabiliza
    grupos pequenos e deixa a mediana levemente conservadora).
    """
    if not im.area:
        return []
    lo, hi = im.area * (1 - _AREA_TOL), im.area * (1 + _AREA_TOL)
    out = []
    for c in pool:
        if c.area is None or not (lo <= c.area <= hi):
            continue
        if im.quartos and c.quartos and abs(c.quartos - im.quartos) > _QUARTOS_TOL:
            continue
        out.append(c.preco_m2)
    return out


def analisar(imoveis, min_amostra=4, limiar_desconto=0.30, exigir_keyword=False,
             preco_min=50_000, preco_m2_min=300, preco_m2_max=60_000,
             historico=None):
    """
    min_amostra: mínimo de comparáveis para confiar na mediana.
    limiar_desconto: % abaixo da mediana para virar candidato (0.30 = 30%).
    exigir_keyword: se True, só alerta imóvel barato QUE TAMBÉM tem palavra-chave.
    preco_min / preco_m2_min / preco_m2_max: piso e teto de sanidade.
    historico: lista de Comp (ver comps_do_historico) para engrossar a amostra.
    Retorna lista de Imovel marcados como oportunidade, ordenada por score.
    """
    imoveis = _dedupe(imoveis)

    # 1. preço/m² individual (com filtro de sanidade)
    validos = []
    for im in imoveis:
        if not (im.preco and im.area and im.area > 0):
            continue
        pm2 = im.preco / im.area
        if im.preco < preco_min or pm2 < preco_m2_min or pm2 > preco_m2_max:
            continue  # dado implausível -> fora
        im.preco_m2 = pm2
        im.grupo = chave_grupo(im)
        validos.append(im)

    # 2. pool de comparáveis por grupo: os válidos desta raspagem + histórico.
    #    o histórico não recontabiliza um imóvel que também está na raspagem atual.
    pool = {}
    urls_atuais = set()
    for im in validos:
        urls_atuais.add(im.url.rstrip("/"))
        pool.setdefault(im.grupo, []).append(
            Comp(im.grupo, im.area, im.quartos, im.preco_m2, im.url))
    for c in (historico or []):
        if not (preco_m2_min <= c.preco_m2 <= preco_m2_max):
            continue
        if c.url and c.url.rstrip("/") in urls_atuais:
            continue
        pool.setdefault(c.grupo, []).append(c)

    # 3 + 4. desconto vs mediana dos comparáveis + keywords
    oportunidades = []
    for im in validos:
        pm2s = _comparaveis(im, pool.get(im.grupo, []))
        n = len(pm2s)
        im.n_grupo = n
        im.keywords = detectar_keywords(im)

        barato = False
        if n >= min_amostra:
            med = median(pm2s)
            im.mediana_grupo = med
            if med > 0:
                im.pct_abaixo = (med - im.preco_m2) / med
                barato = im.pct_abaixo >= limiar_desconto

        tem_kw = len(im.keywords) > 0

        if exigir_keyword:
            alerta = barato and tem_kw
        else:
            alerta = barato or tem_kw

        if alerta:
            im.score = _score(im, barato, tem_kw)
            oportunidades.append(im)

    oportunidades.sort(key=lambda x: x.score, reverse=True)
    return oportunidades


def _score(im: Imovel, barato: bool, tem_kw: bool) -> float:
    """Score simples e explicável: desconto pesa, keyword dá bônus."""
    s = 0.0
    if barato:
        # teto em 60% pra um parse ainda meio torto não dominar o ranking
        s += min(im.pct_abaixo, 0.60) * 100
    s += len(im.keywords) * 8             # cada palavra-chave -> 8 pontos
    if barato and tem_kw:
        s += 20                           # combinação dos dois é o filé
    # amostra maior = mediana mais confiável
    s += min(im.n_grupo, 20) * 0.5
    return round(s, 1)
