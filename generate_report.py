import sqlite3
from pathlib import Path
import datetime
import re
import json

DB_FILE = Path(__file__).parent / "interactions.sqlite"
REPORTS_DIR = Path(__file__).parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

VALUE_RE = re.compile(r"-?\d+[\.,]?\d*")

def parse_value_from_text(text: str):
    if not text:
        return None
    m = VALUE_RE.search(text.replace('R$', ''))
    if not m:
        return None
    try:
        s = m.group(0).replace(',', '.')
        return float(s)
    except Exception:
        return None

def export_transactions_csv(start_date: datetime.date | None = None, end_date: datetime.date | None = None):
    """Exporta todas as transações em formato CSV."""
    from . import db  # import local para evitar circular import
    
    now = datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    out_path = REPORTS_DIR / f"transactions_{now}.csv"
    
    # Busca transações
    try:
        rows = db.export_all_transactions(start_date, end_date)
    except Exception as e:
        raise RuntimeError(f"Erro ao buscar transações: {e}")
    
    if not rows:
        raise RuntimeError("Nenhuma transação encontrada no período especificado.")
    
    # Escreve CSV
    import csv
    with out_path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        # Header
        writer.writerow(['user_id', 'username', 'valor', 'data', 'descricao', 'criado_em'])
        # Dados
        for row in rows:
            writer.writerow(row)
    
    return out_path

def generate_report(limit_users: int = 1000):
    if not DB_FILE.exists():
        raise FileNotFoundError(f"DB not found: {DB_FILE}")

    conn = sqlite3.connect(str(DB_FILE))
    try:
        cur = conn.cursor()
        cur.execute("SELECT user_id, username, message, response, timestamp, metadata FROM interactions ORDER BY id ASC")
        rows = cur.fetchall()
    finally:
        conn.close()

    users = {}
    total_interactions = 0
    for user_id, username, message, response, timestamp, metadata in rows:
        total_interactions += 1
        key = user_id or f"anon_{username or 'unknown'}"
        entry = users.setdefault(key, {"user_id": user_id, "username": username, "count": 0, "last_timestamp": None, "messages": [], "values_total": 0.0, "values_count": 0})
        entry["count"] += 1
        entry["last_timestamp"] = timestamp
        entry["messages"].append(message)

        # tentar extrair valores numéricos das mensagens
        v = parse_value_from_text(message or "")
        if v is not None:
            entry["values_total"] += v
            entry["values_count"] += 1

    # ordenar usuários por contagem decrescente
    sorted_users = sorted(users.values(), key=lambda u: u["count"], reverse=True)[:limit_users]

    now = datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    out_path = REPORTS_DIR / f"report_{now}.md"

    with out_path.open('w', encoding='utf-8') as f:
        f.write(f"# Relatório de Interações — {now} UTC\n\n")
        f.write(f"Total de interações: **{total_interactions}**\n\n")
        f.write(f"Total de usuários: **{len(users)}**\n\n")

        f.write("## Top usuários por número de interações\n\n")
        for u in sorted_users:
            avg_value = (u["values_total"] / u["values_count"]) if u["values_count"] else None
            f.write(f"- **{u.get('username') or u.get('user_id')}** — {u['count']} interações — última: {u['last_timestamp']}\n")
            if u["values_count"]:
                f.write(f"  - valores detectados: {u['values_count']} (soma: {u['values_total']:.2f}, média: {avg_value:.2f})\n")
        f.write('\n')

        f.write('## Usuários detalhado (JSON)\n\n')
        # dump simplified JSON
        simplified = [{"user_id": u["user_id"], "username": u["username"], "count": u["count"], "last_timestamp": u["last_timestamp"], "values_total": u["values_total"], "values_count": u["values_count"]} for u in sorted_users]
        f.write('```json\n')
        f.write(json.dumps(simplified, ensure_ascii=False, indent=2))
        f.write('\n```\n')

    return out_path

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Gera relatórios e exporta transações do bot.')
    parser.add_argument('--csv', action='store_true', help='Exportar transações em CSV')
    parser.add_argument('--inicio', help='Data inicial (DD/MM/YYYY)')
    parser.add_argument('--fim', help='Data final (DD/MM/YYYY)')
    args = parser.parse_args()
    
    try:
        # Parse datas se fornecidas
        start_date = end_date = None
        if args.inicio:
            start_date = datetime.datetime.strptime(args.inicio, '%d/%m/%Y').date()
        if args.fim:
            end_date = datetime.datetime.strptime(args.fim, '%d/%m/%Y').date()
        
        if args.csv:
            path = export_transactions_csv(start_date, end_date)
            print(f"CSV exportado: {path}")
        else:
            path = generate_report()
            print(f"Relatório gerado: {path}")
    except Exception as e:
        print("Erro:", e)
