"""
storage.py
Persistência em SQLite. Duas funções principais:
 - salvar/atualizar imóveis vistos
 - controlar o que JÁ foi alertado, pra não mandar o mesmo imóvel duas vezes no Telegram
"""
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS imoveis (
    url TEXT PRIMARY KEY,
    titulo TEXT, bairro TEXT, cidade TEXT, tipo TEXT,
    preco REAL, area REAL, quartos INTEGER, vagas INTEGER,
    fonte TEXT, preco_m2 REAL, visto_em REAL, atualizado_em REAL
);
CREATE TABLE IF NOT EXISTS alertas (
    url TEXT PRIMARY KEY,
    score REAL,
    alertado_em REAL
);
"""


class Storage:
    def __init__(self, caminho="imoveis.db"):
        self.con = sqlite3.connect(caminho)
        self.con.executescript(SCHEMA)
        self.con.commit()

    def upsert_imovel(self, im):
        agora = time.time()
        cur = self.con.execute("SELECT url FROM imoveis WHERE url=?", (im.url,))
        existe = cur.fetchone() is not None
        if existe:
            self.con.execute("""
                UPDATE imoveis SET titulo=?, bairro=?, cidade=?, tipo=?, preco=?,
                area=?, quartos=?, vagas=?, fonte=?, preco_m2=?, atualizado_em=?
                WHERE url=?""",
                (im.titulo, im.bairro, im.cidade, im.tipo, im.preco, im.area,
                 im.quartos, im.vagas, im.fonte, im.preco_m2, agora, im.url))
        else:
            self.con.execute("""
                INSERT INTO imoveis (url, titulo, bairro, cidade, tipo, preco, area,
                quartos, vagas, fonte, preco_m2, visto_em, atualizado_em)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (im.url, im.titulo, im.bairro, im.cidade, im.tipo, im.preco, im.area,
                 im.quartos, im.vagas, im.fonte, im.preco_m2, agora, agora))
        self.con.commit()

    def ja_alertado(self, url):
        cur = self.con.execute("SELECT url FROM alertas WHERE url=?", (url,))
        return cur.fetchone() is not None

    def marcar_alertado(self, url, score):
        self.con.execute(
            "INSERT OR REPLACE INTO alertas (url, score, alertado_em) VALUES (?,?,?)",
            (url, score, time.time()))
        self.con.commit()

    def fechar(self):
        self.con.close()
