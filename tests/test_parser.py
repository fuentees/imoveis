import pytest

from parser import (parse_preco, parse_area, parse_area_construida, parse_tipo,
                    parse_quartos, parse_vagas, parse_local, _num_br, normalizar_texto)


# ---------------------------------------------------------------- preço
@pytest.mark.parametrize("texto, esperado", [
    ("R$ 1.250.000,00", 1_250_000.0),
    ("R$ 480 mil", 480_000.0),
    ("R$ 480k", 480_000.0),
    ("R$ 1,2 milhão", 1_200_000.0),          # bug: 'mil' sombreava 'milhão'
    ("1.2 milhões", 1_200_000.0),
    ("Preço sob consulta a partir de R$ 2,5 milhões", 2_500_000.0),
    ("R$ 90.000", 90_000.0),
    ("Casa R$ 750.000 - Cond. R$ 850", 750_000.0),
])
def test_parse_preco_venda(texto, esperado):
    assert parse_preco(texto) == esperado


@pytest.mark.parametrize("texto", [
    "",
    "Preço sob consulta",
    "R$ 2.500/mês",                          # aluguel
    "Aluguel R$ 3.500 por mês",
    "Locação R$ 4.000 mensais",
])
def test_parse_preco_sem_venda(texto):
    assert parse_preco(texto) is None


def test_parse_preco_ignora_condominio_e_iptu():
    t = "Condomínio R$ 1.200  IPTU R$ 800  Casa à venda R$ 750.000"
    assert parse_preco(t) == 750_000.0


def test_parse_preco_maior_valor_vence_mesmo_com_taxa_ao_lado():
    t = "R$ 890.000  •  Cond. R$ 750/mês  •  IPTU R$ 210/mês"
    assert parse_preco(t) == 890_000.0


@pytest.mark.parametrize("texto, esperado", [
    ("De R$ 1.600.000 por R$ 1.300.000", 1_300_000.0),
    ("Casa em Guarujá, de R$ 900 mil por apenas R$ 720 mil", 720_000.0),
    ("Baixou! Era R$ 2.000.000, agora por R$ 1.750.000", 1_750_000.0),
])
def test_parse_preco_de_x_por_y(texto, esperado):
    assert parse_preco(texto) == esperado


# ---------------------------------------------------------------- área
@pytest.mark.parametrize("texto, esperado", [
    ("120 m²", 120.0),
    ("120m2", 120.0),
    ("70,5 m²", 70.5),
    ("1.070 M²", 1070.0),
])
def test_parse_area_ok(texto, esperado):
    assert parse_area(texto) == esperado


def test_parse_area_ignora_terreno():
    assert parse_area("560 m² de terreno") is None
    assert parse_area("Casa 180 m², terreno 500 m²") == 180.0


def test_parse_area_ignora_metros_de_distancia():
    # "500 metros do centro" é distância, não área
    assert parse_area("Apartamento a 500 metros do centro da cidade") is None
    assert parse_area("fica a 300 metros da praia. Área: 88 m²") == 88.0
    assert parse_area("120 metros quadrados") == 120.0
    assert parse_area_construida("Lindo apto a 500 metros da praia, 3 dorms") is None


def test_parse_area_construida():
    t = "Casa 855,00 m² área construída em terreno de 1.000 m² área total"
    assert parse_area_construida(t) == 855.0
    assert parse_area_construida("área útil: 120 m²") == 120.0
    assert parse_area_construida("560 m² de terreno") is None


# ---------------------------------------------------------------- tipo
@pytest.mark.parametrize("texto, esperado", [
    ("Apartamento 2 quartos na praia", "apartamento"),
    ("Casa em condomínio fechado", "casa"),
    ("Excelente Cobertura duplex", "cobertura"),
    ("Terreno plano 500 m²", "terreno"),
    ("Imóvel comercial", ""),
])
def test_parse_tipo(texto, esperado):
    assert parse_tipo(texto) == esperado


# ---------------------------------------------------------------- quartos / vagas
@pytest.mark.parametrize("texto, esperado", [
    ("1 suíte master e 3 dormitórios", 3),    # bug: retornava 1
    ("4 quartos", 4),
    ("2 dorm", 2),
    ("3 qtos", 3),
    ("2 suítes", 2),
    ("apenas suíte, sem número", None),
    ("", None),
])
def test_parse_quartos(texto, esperado):
    assert parse_quartos(texto) == esperado


def test_parse_vagas():
    assert parse_vagas("2 vagas") == 2
    assert parse_vagas("3 vagas de garagem") == 3
    assert parse_vagas("sem garagem") is None


# ---------------------------------------------------------------- local
@pytest.mark.parametrize("texto, cidade, bairro", [
    ("Jardim Acapulco - Guarujá - SP", "Guarujá", "Jardim Acapulco"),
    ("Centro, Itanhaém-SP", "Itanhaém", "Centro"),
    ("Rodovia SP-55 km 12", "", ""),
])
def test_parse_local(texto, cidade, bairro):
    c, b = parse_local(texto)
    assert (c, b) == (cidade, bairro)


# ---------------------------------------------------------------- _num_br
@pytest.mark.parametrize("s, esperado", [
    ("1.250.000,00", 1_250_000.0),
    ("480", 480.0),
    ("1,2", 1.2),
    ("1.070", 1070.0),
    ("1.2", 1.2),
])
def test_num_br(s, esperado):
    assert _num_br(s) == esperado


def test_normalizar_texto():
    assert normalizar_texto("  Jardim   ACAPÚLCO ") == "jardim acapulco"
