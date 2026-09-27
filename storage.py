"""
storage.py
Persistência em SQLite. Três papéis:
 - salvar/atualizar imóveis vistos (histórico que engrossa a mediana)
 - controlar o que JÁ foi alertado, pra não repetir no Telegram
 - guardar o preço no momento do alerta, pra re-alertar se cair mais depois
 - contar ciclos seguidos sem dados de cada fonte, pra avisar quando uma parar
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
CREATE TABLE IF NOT EXISTS saude_fontes (
    nome TEXT PRIMARY KEY,
    falhas_seguidas INTEGER NOT NULL DEFAULT 0,
    ultimo_ok REAL,
    ultimo_status TEXT,
    avisado_em REAL
);
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

    def urls_alertadas_desde(self, instante):
        return [r[0] for r in self.con.execute(
            "SELECT url FROM alertas WHERE alertado_em >= ?", (instante,))]

    def registrar_saude(self, nome, ok, status=""):
        """
        Atualiza a contagem de ciclos seguidos sem dados da fonte.
        Retorna True quando a fonte voltou depois de já ter sido avisada.
        """
        row = self.con.execute(
            "SELECT falhas_seguidas, avisado_em FROM saude_fontes WHERE nome=?", (nome,)).fetchone()
        voltou = bool(ok and row and row[1])
        if ok:
            self.con.execute(
                "INSERT INTO saude_fontes (nome, falhas_seguidas, ultimo_ok, ultimo_status, avisado_em) "
                "VALUES (?, 0, ?, ?, NULL) ON CONFLICT(nome) DO UPDATE SET falhas_seguidas=0, "
                "ultimo_ok=excluded.ultimo_ok, ultimo_status=excluded.ultimo_status, avisado_em=NULL",
                (nome, time.time(), status))
        else:
            self.con.execute(
                "INSERT INTO saude_fontes (nome, falhas_seguidas, ultimo_status) VALUES (?, 1, ?) "
                "ON CONFLICT(nome) DO UPDATE SET falhas_seguidas=falhas_seguidas+1, "
                "ultimo_status=excluded.ultimo_status", (nome, status))
        self.con.commit()
        return voltou

    def fontes_para_avisar(self, minimo_falhas):
        """Fontes com `minimo_falhas`+ ciclos seguidos sem dados e ainda não avisadas."""
        return self.con.execute(
            "SELECT nome, falhas_seguidas, ultimo_ok, ultimo_status FROM saude_fontes "
            "WHERE falhas_seguidas >= ? AND avisado_em IS NULL ORDER BY nome",
            (minimo_falhas,)).fetchall()

    def marcar_avisadas(self, nomes):
        with self.con:
            self.con.executemany("UPDATE saude_fontes SET avisado_em=? WHERE nome=?",
                                 [(time.time(), n) for n in nomes])

    def fechar(self):
        self.con.close()
