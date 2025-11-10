import sqlite3
import json
import datetime
from pathlib import Path

# Caminho padrão do banco (arquivo ao lado deste módulo)
DB_PATH = Path(__file__).parent / "interactions.sqlite"

def init_db(db_path: str | Path | None = None):
    """Inicializa o banco de dados e cria as tabelas se necessário."""
    global DB_PATH
    if db_path:
        DB_PATH = Path(db_path)

    conn = sqlite3.connect(str(DB_PATH))
    try:
        cursor = conn.cursor()
        # Tabela original de interações
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                message TEXT,
                response TEXT,
                timestamp TEXT,
                metadata TEXT
            )
            """
        )
        # Nova tabela de transações com campos estruturados
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount DECIMAL(10,2) NOT NULL,
                date DATE NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES interactions(user_id)
            )
            """
        )
        # Índices para consultas comuns
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user_date ON transactions(user_id, date)")
        conn.commit()
    finally:
        conn.close()

def log_interaction(user_id: int | None, username: str | None, message: str | None, response: str | None, metadata: dict | None = None):
    """Registra uma interação no banco. Abre uma conexão, insere e fecha.

    Usamos conexão curta para evitar problemas de concorrência com SQLite em ambientes
    assíncronos/threads.
    """
    ts = datetime.datetime.utcnow().isoformat()
    meta_json = json.dumps(metadata, ensure_ascii=False) if metadata is not None else None

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    try:
        with conn:
            conn.execute(
                "INSERT INTO interactions (user_id, username, message, response, timestamp, metadata) VALUES (?,?,?,?,?,?)",
                (user_id, username, message, response, ts, meta_json),
            )
    finally:
        conn.close()

def fetch_recent(limit: int = 100):
    """Retorna as últimas `limit` interações (útil para debug)."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, user_id, username, message, response, timestamp, metadata FROM interactions ORDER BY id DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        return rows
    finally:
        conn.close()

def add_transaction(user_id: int, amount: float, date: datetime.date, description: str | None = None):
    """Adiciona uma nova transação ao banco."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    try:
        with conn:
            conn.execute(
                "INSERT INTO transactions (user_id, amount, date, description) VALUES (?,?,?,?)",
                (user_id, amount, date.isoformat(), description)
            )
    finally:
        conn.close()

def get_user_transactions(user_id: int, start_date: datetime.date | None = None, end_date: datetime.date | None = None):
    """Retorna transações de um usuário, opcionalmente filtradas por período."""
    query = "SELECT id, amount, date, description, created_at FROM transactions WHERE user_id = ?"
    params = [user_id]
    
    if start_date:
        query += " AND date >= ?"
        params.append(start_date.isoformat())
    if end_date:
        query += " AND date <= ?"
        params.append(end_date.isoformat())
    
    query += " ORDER BY date DESC, id DESC"
    
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        return cur.fetchall()
    finally:
        conn.close()

def export_all_transactions(start_date: datetime.date | None = None, end_date: datetime.date | None = None):
    """Exporta todas as transações (útil para relatórios e backup).
    
    Returns:
        List[tuple]: Lista de (user_id, username, amount, date, description, created_at)
    """
    query = """
    SELECT t.user_id, MAX(i.username) as username, t.amount, t.date, t.description, t.created_at
    FROM transactions t
    LEFT JOIN interactions i ON t.user_id = i.user_id
    """
    params = []
    
    if start_date or end_date:
        query += " WHERE 1=1"
        if start_date:
            query += " AND t.date >= ?"
            params.append(start_date.isoformat())
        if end_date:
            query += " AND t.date <= ?"
            params.append(end_date.isoformat())
    
    query += " GROUP BY t.id ORDER BY t.date DESC, t.id DESC"
    
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        return cur.fetchall()
    finally:
        conn.close()
