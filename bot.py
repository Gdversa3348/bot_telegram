from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import datetime
import re
from . import db

# Banco de dados em memória para cálculos (mantemos a lógica atual)
dados = {"ganhos": [], "gastos": []}

# Formato esperado: valor; data; descrição
# Exemplos válidos:
# 1500; hoje; salário
# -89.90; ontem; mercado
# 150; 25/10; venda item
VALOR_RE = re.compile(r'^(-?\d+(?:[,.]\d{1,2})?)\s*;\s*([^;]+?)(?:\s*;\s*(.+))?$')

def parse_message(text: str) -> tuple[float, datetime.date, str] | None:
    """Parse mensagem do usuário no formato valor; data; descrição"""
    if not text:
        return None
        
    m = VALOR_RE.match(text.strip())
    if not m:
        return None
        
    # Extrair valor (converter , para .)
    try:
        valor = float(m.group(1).replace(',', '.'))
    except ValueError:
        return None
        
    # Parse data relativa/absoluta
    data_str = m.group(2).lower().strip()
    try:
        hoje = datetime.date.today()
        if data_str == 'hoje':
            data = hoje
        elif data_str == 'ontem':
            data = hoje - datetime.timedelta(days=1)
        elif data_str == 'amanha' or data_str == 'amanhã':
            data = hoje + datetime.timedelta(days=1)
        else:
            # Tentar DD/MM/YYYY, DD/MM/YY ou DD/MM
            partes = data_str.split('/')
            if len(partes) == 3:  # DD/MM/YYYY ou DD/MM/YY
                dia, mes, ano = map(int, partes)
                if ano < 100:  # Formato YY (23 -> 2023)
                    ano += 2000
                data = datetime.date(ano, mes, dia)
            elif len(partes) == 2:  # DD/MM
                dia, mes = map(int, partes)
                ano = hoje.year
                # Se a data ficaria no futuro, assume ano passado
                data = datetime.date(ano, mes, dia)
                if data > hoje:
                    data = datetime.date(ano - 1, mes, dia)
            else:
                return None
    except (ValueError, TypeError):
        return None
        
    # Descrição (opcional)
    desc = (m.group(3) or '').strip()
    
    return valor, data, desc

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Olá! Eu sou seu bot de orçamento pessoal.\n\n"
        "� Formato: valor; data; descrição\n"
        "📊 Use /ajuda para ver exemplos e /resumo para ver seu saldo."
    )
    await update.message.reply_text(text)

    # Log de interação (start)
    try:
        user = update.effective_user
        db.log_interaction(user.id if user else None, getattr(user, 'username', None), '/start', text, {'command': 'start'})
    except Exception:
        # Não falhar o bot por problemas no log
        pass

async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📝 Como registrar valores:\n\n"
        "Formato: valor; data; descrição\n\n"
        "Exemplos com data completa:\n"
        "✅ -200; 01/11/2025; comida\n"
        "✅ 1500; 05/11/2025; salário\n"
        "❌ -45.90; 02/11/2025; farmácia\n\n"
        "📅 Formatos de data aceitos:\n"
        "1. Data completa (recomendado):\n"
        "   - DD/MM/AAAA (01/11/2025)\n"
        "   - DD/MM/AA (01/11/25)\n\n"
        "2. Data relativa:\n"
        "   - hoje\n"
        "   - ontem\n"
        "   - amanhã\n\n"
        "3. Data curta (assume ano atual):\n"
        "   - DD/MM (25/10)\n\n"
        "� Comandos disponíveis:\n"
        "1. Ver resumo do mês atual:\n"
        "   /resumo\n\n"
        "2. Extrato por mês específico:\n"
        "   /extrato mes MM/YYYY\n"
        "   Exemplo: /extrato mes 11/2025\n\n"
        "3. Extrato por período:\n"
        "   /extrato periodo DD/MM/YYYY DD/MM/YYYY\n"
        "   Exemplo: /extrato periodo 01/10/2025 31/10/2025\n\n"
        "�💡 Dicas:\n"
        "- Use datas completas (DD/MM/AAAA) para registros passados\n"
        "- Use 'hoje', 'ontem', 'amanhã' para registros recentes\n"
        "- A descrição é opcional mas ajuda a organizar\n"
        "- Valores negativos (-200) são gastos\n"
        "- Valores positivos (1500) são ganhos"
    )
    await update.message.reply_text(text)
    
    try:
        user = update.effective_user
        db.log_interaction(user.id if user else None, getattr(user, 'username', None), '/ajuda', text, {'command': 'ajuda'})
    except Exception:
        pass

async def registrar_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
        
    # Tenta fazer o parse no novo formato
    parsed = parse_message(update.message.text)
    if not parsed:
        resp = (
            "⚠️ Formato inválido. Use: valor; data; descrição\n\n"
            "Exemplos:\n"
            "1500; hoje; salário\n"
            "-89.90; ontem; mercado\n\n"
            "Use /ajuda para ver todos os formatos aceitos."
        )
        await update.message.reply_text(resp)
        try:
            user = update.effective_user
            db.log_interaction(user.id if user else None, getattr(user, 'username', None), 
                             update.message.text, resp, {'handler': 'registrar_valor', 'error': 'parse'})
        except Exception:
            pass
        return
        
    valor, data, desc = parsed
    try:
        # Registra na nova tabela transactions
        user = update.effective_user
        if not user or not user.id:
            resp = "⚠️ Erro: não foi possível identificar o usuário."
            await update.message.reply_text(resp)
            return
            
        # Adiciona à nova tabela
        db.add_transaction(user.id, valor, data, desc)
        
        # Mantém lógica atual dos totais em memória
        if valor >= 0:
            dados["ganhos"].append(valor)
            tipo = "Ganho"
            emoji = "✅"
        else:
            dados["gastos"].append(abs(valor))
            tipo = "Gasto"
            emoji = "❌"
            
        # Formata resposta com data e descrição
        desc_fmt = f" ({desc})" if desc else ""
        data_fmt = data.strftime("%d/%m/%Y")
        resp = f"{emoji} {tipo} de R$ {abs(valor):.2f} registrado em {data_fmt}{desc_fmt}!"
        
        await update.message.reply_text(resp)
        
        # Log de sucesso
        try:
            db.log_interaction(user.id, getattr(user, 'username', None), 
                             update.message.text, resp,
                             {'handler': 'registrar_valor', 'parsed': {'amount': valor, 'date': data.isoformat(), 'desc': desc}})
        except Exception:
            pass
            
    except Exception as e:
        resp = f"⚠️ Erro ao registrar: {str(e)}"
        await update.message.reply_text(resp)
        try:
            user = update.effective_user
            db.log_interaction(user.id if user else None, getattr(user, 'username', None),
                             update.message.text, resp,
                             {'handler': 'registrar_valor', 'error': str(e)})
        except Exception:
            pass

async def extrato(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gera relatório de transações por mês ou período personalizado.
    
    Comandos:
    /extrato mes MM/YYYY
    /extrato periodo DD/MM/YYYY DD/MM/YYYY
    """
    user = update.effective_user
    if not user or not user.id:
        await update.message.reply_text("⚠️ Erro: não foi possível identificar o usuário.")
        return

    args = context.args if hasattr(context, 'args') else []
    if not args:
        text = (
            "📊 Como usar o extrato:\n\n"
            "1. Extrato mensal:\n"
            "/extrato mes MM/YYYY\n"
            "Exemplo: /extrato mes 11/2025\n\n"
            "2. Extrato por período:\n"
            "/extrato periodo DD/MM/YYYY DD/MM/YYYY\n"
            "Exemplo: /extrato periodo 01/10/2025 31/10/2025"
        )
        await update.message.reply_text(text)
        return

    try:
        tipo = args[0].lower()
        hoje = datetime.date.today()
        
        if tipo == "mes" and len(args) == 2:
            # Formato: MM/YYYY
            try:
                mes, ano = map(int, args[1].split('/'))
                if ano < 100:  # Converter YY para YYYY
                    ano += 2000
                inicio = datetime.date(ano, mes, 1)
                if mes == 12:
                    fim = datetime.date(ano, 12, 31)
                else:
                    fim = datetime.date(ano, mes + 1, 1) - datetime.timedelta(days=1)
            except (ValueError, TypeError):
                await update.message.reply_text("⚠️ Formato inválido. Use: /extrato mes MM/YYYY")
                return
                
        elif tipo == "periodo" and len(args) == 3:
            # Formato: DD/MM/YYYY DD/MM/YYYY
            try:
                d1 = datetime.datetime.strptime(args[1], "%d/%m/%Y").date()
                d2 = datetime.datetime.strptime(args[2], "%d/%m/%Y").date()
                inicio, fim = (d1, d2) if d1 <= d2 else (d2, d1)
            except (ValueError, TypeError):
                await update.message.reply_text("⚠️ Formato inválido. Use: /extrato periodo DD/MM/YYYY DD/MM/YYYY")
                return
        else:
            await update.message.reply_text("⚠️ Comando inválido. Use /extrato para ver as opções.")
            return

        # Buscar transações do período
        trans = db.get_user_transactions(user.id, inicio, fim)
        if not trans:
            await update.message.reply_text(f"📊 Nenhuma transação encontrada no período de {inicio.strftime('%d/%m/%Y')} a {fim.strftime('%d/%m/%Y')}")
            return

        # Calcular totais
        ganhos = sum(valor for _, valor, *_ in trans if valor > 0)
        gastos = sum(abs(valor) for _, valor, *_ in trans if valor < 0)
        saldo = ganhos - gastos

        # Gerar relatório
        linhas = [
            f"📊 Extrato: {inicio.strftime('%d/%m/%Y')} a {fim.strftime('%d/%m/%Y')}\n",
            f"✅ Total Ganhos: R$ {ganhos:.2f}",
            f"❌ Total Gastos: R$ {gastos:.2f}",
            f"💰 Saldo: R$ {saldo:.2f}\n",
            "📝 Transações:"
        ]

        # Agrupar por dia
        por_dia = {}
        for _, valor, data, desc, _ in trans:
            data_obj = datetime.date.fromisoformat(data)
            if data_obj not in por_dia:
                por_dia[data_obj] = []
            sinal = "+" if valor > 0 else "-"
            desc_fmt = f" ({desc})" if desc else ""
            por_dia[data_obj].append(f"  {sinal}R$ {abs(valor):.2f}{desc_fmt}")

        # Listar transações por dia
        for data in sorted(por_dia.keys(), reverse=True):
            linhas.append(f"\n📅 {data.strftime('%d/%m/%Y')}:")
            linhas.extend(por_dia[data])

        await update.message.reply_text("\n".join(linhas))

        # Log do comando
        try:
            db.log_interaction(
                user.id, 
                getattr(user, 'username', None),
                f"/extrato {' '.join(args)}", 
                "ok",
                {'command': 'extrato', 'tipo': tipo, 'inicio': inicio.isoformat(), 'fim': fim.isoformat()}
            )
        except Exception:
            pass

    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro ao gerar extrato: {str(e)}")
        try:
            db.log_interaction(
                user.id,
                getattr(user, 'username', None),
                f"/extrato {' '.join(args)}",
                f"erro: {str(e)}",
                {'command': 'extrato', 'error': str(e)}
            )
        except Exception:
            pass

async def resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not user.id:
        await update.message.reply_text("⚠️ Erro: não foi possível identificar o usuário.")
        return
        
    # Pega transações do mês atual
    hoje = datetime.date.today()
    inicio_mes = hoje.replace(day=1)
    
    try:
        trans = db.get_user_transactions(user.id, inicio_mes, hoje)
        if not trans:
            text = "📊 Nenhuma transação registrada este mês."
            await update.message.reply_text(text)
            return
            
        # Calcula totais
        ganhos = sum(valor for _, valor, *_ in trans if valor > 0)
        gastos = sum(abs(valor) for _, valor, *_ in trans if valor < 0)
        saldo = ganhos - gastos
        
        # Lista últimas 5 transações
        ultimas = []
        for _, valor, data, desc, _ in trans[:5]:
            data_fmt = datetime.date.fromisoformat(data).strftime("%d/%m")
            desc_fmt = f" ({desc})" if desc else ""
            sinal = "+" if valor > 0 else "-"
            ultimas.append(f"{data_fmt}: {sinal}R$ {abs(valor):.2f}{desc_fmt}")
        
        text = (
            f"📊 Resumo do mês ({hoje.strftime('%m/%Y')}):\n\n"
            f"✅ Ganhos: R$ {ganhos:.2f}\n"
            f"❌ Gastos: R$ {gastos:.2f}\n"
            f"💰 Saldo: R$ {saldo:.2f}\n\n"
            f"📝 Últimas transações:\n" + "\n".join(ultimas)
        )
        await update.message.reply_text(text)
        
        try:
            db.log_interaction(user.id, getattr(user, 'username', None), '/resumo', text, 
                             {'command': 'resumo', 'month': hoje.strftime('%Y-%m')})
        except Exception:
            pass
            
    except Exception as e:
        text = f"⚠️ Erro ao gerar resumo: {str(e)}"
        await update.message.reply_text(text)
        try:
            db.log_interaction(user.id, getattr(user, 'username', None), '/resumo', text,
                             {'command': 'resumo', 'error': str(e)})
        except Exception:
            pass

def main():
    # Inicializa banco de dados
    try:
        db.init_db()
    except Exception:
        # Não interrompe a inicialização do bot se houver problema no DB
        pass

    app = Application.builder().token("8299762062:AAGPXqwgPciG07T896tso4RWOg7dges58fg").build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("resumo", resumo))
    app.add_handler(CommandHandler("extrato", extrato))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_valor))
    app.run_polling()

if __name__ == "__main__":
    main()
