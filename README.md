# Bot Telegram — Interações (SQLite)

Este diretório contém um módulo simples para registrar todas as interações do bot com usuários em um banco SQLite (`interactions.sqlite`).

Arquivos principais:
- `db.py`: inicializa o banco e fornece `log_interaction()` e `fetch_recent()`.
- `bot.py`: integra chamadas para gravar cada mensagem/ resposta enviada.

Como usar:
1. Execute o bot normalmente (ex: `python -m bot_telegram.bot` a partir do root do projeto).
2. Um arquivo `interactions.sqlite` será criado ao lado de `db.py`.

Formato de mensagens:
```
valor; data; descrição

Exemplos:
1500; hoje; salário
-89.90; ontem; mercado
150; 25/10; venda item
-250; 15/11/23; conta de luz
```

Formatos de data aceitos:
- hoje
- ontem
- DD/MM (25/10)
- DD/MM/AA (25/10/23)
- DD/MM/AAAA (25/10/2023)

Comandos do bot:
- /start - Inicia o bot
- /ajuda - Mostra exemplos de uso
- /resumo - Mostra resumo do mês atual

Exportar dados e relatórios:

```powershell
# Gerar relatório Markdown (resumo de uso)
python .\bot_telegram\generate_report.py

# Exportar todas as transações em CSV
python .\bot_telegram\generate_report.py --csv

# Exportar transações por período
python .\bot_telegram\generate_report.py --csv --inicio 01/10/2023 --fim 31/10/2023
```

Os arquivos serão salvos em `bot_telegram/reports/`.

Inspecionar o banco com a CLI sqlite3 (Windows PowerShell):

```powershell
# abrir o banco
sqlite3 .\bot_telegram\interactions.sqlite

# listar últimas transações
SELECT t.date, t.amount, t.description, i.username 
FROM transactions t 
LEFT JOIN interactions i ON t.user_id = i.user_id 
ORDER BY t.date DESC LIMIT 20;
```

Ou use um visualizador SQLite (DB Browser for SQLite) para abrir o arquivo graficamente.

Observações:
- O registro tenta não bloquear o bot: erros de gravação são capturados silenciosamente.
- `metadata` é armazenado como JSON no campo `metadata`.

Gerar relatório
----------------

Um script simples gera um relatório Markdown resumindo interações e detectando valores numéricos nas mensagens.

Executar (PowerShell):

```powershell
python .\bot_telegram\generate_report.py
```

O relatório será salvo em `bot_telegram/reports/report_YYYYMMDD_HHMMSS.md` e o caminho será impresso no terminal.

