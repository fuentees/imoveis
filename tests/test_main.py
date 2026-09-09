from types import SimpleNamespace

from main import _deve_realertar


def im(preco):
    return SimpleNamespace(preco=preco)


def test_realerta_so_com_queda_relevante():
    assert _deve_realertar(im(900_000), preco_anterior=1_000_000, queda_min=0.10) is True
    assert _deve_realertar(im(950_000), preco_anterior=1_000_000, queda_min=0.10) is False
    assert _deve_realertar(im(1_050_000), preco_anterior=1_000_000, queda_min=0.10) is False


def test_realerta_sem_preco_anterior():
    assert _deve_realertar(im(900_000), preco_anterior=None, queda_min=0.10) is False
    assert _deve_realertar(im(None), preco_anterior=1_000_000, queda_min=0.10) is False
