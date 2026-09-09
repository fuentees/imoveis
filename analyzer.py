"""
analyzer.py
O cérebro. Recebe uma lista de imóveis normalizados e devolve os que valem alerta.

Lógica:
1. Agrupa imóveis COMPARÁVEIS: (bairro, tipo, faixa de metragem, faixa de quartos).
   -> Comparar m² da região inteira gera falso positivo (unidade grande dilui o m²).
2. Para cada grupo com amostra suficiente, calcula a MEDIANA de preço/m².
3. Marca como candidato quem está X% ABAIXO da mediana do próprio grupo.
4. Cruza com PALAVRAS-CHAVE de espólio/urgência (o sinal que separa
   oportunidade real de imóvel-problema).
5. Pontua e devolve ordenado.
"""
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


def _faixa_metragem(area: Optional[float]) -> str:
    if area is None:
        return "area_?"
    # bandas até 350 pra imóvel comum; acima disso pra alto padrão
    # (Jardim Acapulco/Riviera tem casa de 400 a 900+ m² - sem essas
    # faixas tudo cai no mesmo balde e a mediana perde o sentido).
    for lim, nome in [(50, "0-50"), (80, "50-80"), (120, "80-120"),
                      (200, "120-200"), (350, "200-350"), (500, "350-500"),
                      (800, "500-800"), (1200, "800-1200")]:
        if area < lim:
            return nome
    return "1200+"


def _faixa_quartos(q: Optional[int]) -> str:
    if q is None:
        return "q?"
    if q >= 4:
        return "4+"
    return str(q)


def chave_grupo(im: Imovel) -> str:
    return "|".join([
        normalizar_texto(im.cidade),
        normalizar_texto(im.bairro),
        normalizar_texto(im.tipo) or "tipo?",
        _faixa_metragem(im.area),
        _faixa_quartos(im.quartos),
    ])


def detectar_keywords(im: Imovel) -> list:
    texto = im.texto_busca()
    return [kw for kw in PALAVRAS_CHAVE if kw in texto]


def _chaves_dedupe(im: Imovel):
    """URL + "impressão digital física" do imóvel."""
    chaves = ["u:" + im.url.rstrip("/")]
    if im.preco and im.area:
        chaves.append("f:%s|%s|%d|%d|%d" % (
            normalizar_texto(im.bairro), normalizar_texto(im.tipo),
            round(im.preco / 1000), round(im.area), im.quartos or 0,
        ))
    return chaves


def _dedupe(imoveis):
    """
    Colapsa o MESMO imóvel contando 2x: URL repetida (paginação) e o mesmo
    imóvel reanunciado com outro código (mesmo bairro/tipo/preço/área/quartos).
    Sem isso o grupo infla e sai alerta duplicado. Mantém o de descrição maior.
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


def analisar(imoveis, min_amostra=4, limiar_desconto=0.30, exigir_keyword=False,
             preco_min=50_000, preco_m2_min=300, preco_m2_max=60_000):
    """
    min_amostra: mínimo de comparáveis no grupo para confiar na mediana.
    limiar_desconto: % abaixo da mediana para virar candidato (0.30 = 30%).
    exigir_keyword: se True, só alerta imóvel barato QUE TAMBÉM tem palavra-chave.
                    Reduz muito o ruído; deixe False no começo para calibrar.
    preco_min / preco_m2_min / preco_m2_max: piso e teto de sanidade. Descarta
                    parse errado (ex.: pegou IPTU "R$ 1.300" no lugar do preço,
                    ou m² absurdo) antes que vire um alerta "100% abaixo".
    Retorna lista de Imovel marcados como oportunidade, ordenada por score.
    """
    # 0. tira duplicata antes de tudo (senão infla o grupo)
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

    # 2. mediana por grupo
    grupos = {}
    for im in validos:
        grupos.setdefault(im.grupo, []).append(im.preco_m2)

    medianas = {g: (median(v), len(v)) for g, v in grupos.items()}

    # 3 + 4. desconto vs mediana + keywords
    oportunidades = []
    for im in validos:
        med, n = medianas[im.grupo]
        im.mediana_grupo, im.n_grupo = med, n
        im.keywords = detectar_keywords(im)

        barato = False
        if n >= min_amostra and med > 0:
            im.pct_abaixo = (med - im.preco_m2) / med
            barato = im.pct_abaixo >= limiar_desconto

        tem_kw = len(im.keywords) > 0

        # regra de alerta:
        #  - barato o suficiente (com amostra confiável), OU
        #  - tem palavra-chave forte de espólio/urgência
        #  - se exigir_keyword=True, precisa das duas
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
