"""
storage.py
Persistência em SQLite. Três papéis:
 - salvar/atualizar imóveis vistos (histórico que engrossa a mediana)
 - controlar o que JÁ foi alertado, pra não repetir no Telegram
 - guardar o preço no momento do alerta, pra re-alertar se cair mais depois
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
    preco REAL,
    alertado_em REAL
);
CREATE INDEX IF NOT EXISTS ix_imoveis_atualizado ON imoveis (atualizado_em);
"""


class Storage:
    def __init__(self, caminho="imoveis.db"):
        self.con = sqlite3.connect(caminho)
        self.con.executescript(SCHEMA)
        self._migrar()
        self.con.commit()

    def _migrar(self):
        """Migrações idempotentes para bancos criados por versões antigas."""
        cols = {r[1] for r in self.con.execute("PRAGMA table_info(alertas)")}
        if "preco" not in cols:
            self.con.execute("ALTER TABLE alertas ADD COLUMN preco REAL")

    def upsert_imovel(self, im):
        self._upsert_imovel(im)
        self.con.commit()

    def _upsert_imovel(self, im):
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

    def upsert_imoveis(self, imoveis):
        """Persiste um ciclo inteiro em uma única transação."""
        with self.con:
            for im in imoveis:
                self._upsert_imovel(im)

    def carregar_comparaveis(self, dias=180):
        """
        Histórico recente (últimos `dias`) para engrossar a amostra das medianas.
        Retorna tuplas (url, cidade, bairro, tipo, area, quartos, preco_m2).
        `dias=0` -> só o instante atual (na prática, desliga o histórico).
        """
        corte = time.time() - dias * 86400
        cur = self.con.execute(
            "SELECT url, cidade, bairro, tipo, area, quartos, preco_m2 FROM imoveis "
            "WHERE preco_m2 IS NOT NULL AND area IS NOT NULL AND atualizado_em >= ?",
            (corte,))
        return cur.fetchall()

    def info_alerta(self, url):
        """(preco, score) do último alerta desse imóvel, ou None se nunca alertou."""
        cur = self.con.execute("SELECT preco, score FROM alertas WHERE url=?", (url,))
        row = cur.fetchone()
        return (row[0], row[1]) if row else None

    def ja_alertado(self, url):
        return self.info_alerta(url) is not None

    def marcar_alertado(self, url, score, preco=None):
        self.con.execute(
            "INSERT OR REPLACE INTO alertas (url, score, preco, alertado_em) "
            "VALUES (?,?,?,?)",
            (url, score, preco, time.time()))
        self.con.commit()

    def fechar(self):
        self.con.close()
