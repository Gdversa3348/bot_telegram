from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler
import datetime
import re
import random
import string
import os
from pathlib import Path
from . import db
from . import ocr as ocr_module

# Detecta engine de OCR disponível no ambiente
OCR_ENGINE = ocr_module.detect_engine()
print(f"[INFO] OCR engine detected: {OCR_ENGINE}")

# Armazena recepientes pendentes para interação por usuário
pending_receipts: dict = {}

# Removida variável global dados - agora usamos apenas o banco SQLite

# Formato esperado: valor; data; descrição
# Exemplos válidos:
# 1500; hoje; salário
# -89.90; ontem; mercado
# +150; 25/10; venda item
# Aceita números com ou sem sinal (+ ou -)
VALOR_RE = re.compile(r'^([+-]?\d+(?:[,.]\d{1,2})?)\s*;\s*([^;]+?)(?:\s*;\s*(.+))?$')

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


async def process_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa uma imagem enviada pelo usuário (foto ou documento-imagem).
    Usa PaddleOCR/EasyOCR via `ocr.parse_receipt`. Se encontrar um valor total, registra
    automaticamente como transação; caso contrário, retorna opções ao usuário.
    """
    if not update.message:
        return

    user = update.effective_user
    if not user or not user.id:
        await update.message.reply_text("⚠️ Erro: não foi possível identificar o usuário.")
        return

    file_obj = None
    if update.message.photo:
        file_obj = await update.message.photo[-1].get_file()
    elif update.message.document and (getattr(update.message.document, 'mime_type', '') or '').startswith('image'):
        file_obj = await update.message.document.get_file()
    else:
        await update.message.reply_text("Envie uma foto ou imagem do comprovante para processar.")
        return

    uploads_dir = Path(__file__).parent / 'uploads'
    uploads_dir.mkdir(parents=True, exist_ok=True)
    filename = uploads_dir / f"{user.id}_{int(datetime.datetime.utcnow().timestamp())}.jpg"

    try:
        # tentativa assíncrona
        await file_obj.download_to_drive(str(filename))
    except Exception:
        try:
            # fallback síncrono
            file_obj.download(str(filename))
        except Exception as e:
            await update.message.reply_text(f"❌ Erro ao salvar a imagem: {e}")
            return

    await update.message.reply_text("🔎 Processando imagem... Isso pode levar alguns segundos.")

    try:
        result = ocr_module.parse_receipt(str(filename))
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao executar OCR: {str(e)}")
        return

    # Se o OCR não retornou nada útil, informa o usuário com dicas
    if not result or not (result.get('text') or '').strip():
        msg = (
            "❌ Não consegui reconhecer texto nessa imagem.\n\n"
            "Dicas para melhorar a leitura:\n"
            "- Tire uma foto mais nítida e bem iluminada (evite reflexos).\n"
            "- Foque na área do recibo/extrato (dê um crop se possível).\n"
            "- Se for um PDF/documento, envie como documento em vez de foto.\n"
            "- Tente enviar a imagem em alta resolução.\n\n"
            "Se quiser, envie outra imagem e eu tento novamente."
        )
        await update.message.reply_text(msg)
        return

    total = result.get('total')
    date = result.get('date')
    desc = result.get('description') or 'Recibo (OCR)'

    if total is not None:
            # Use the OCR module classifier to decide if this looks like a payment/receipt
            classification = ocr_module.is_payment_receipt(result)
            is_bank_like = classification.get('is_payment', False)
            score = classification.get('score', 0.0)
            strong = classification.get('strong', False)

            tx_date = date if date else datetime.date.today()

            # Strong confidence -> add automatically
            if strong:
                try:
                    db.add_transaction(user.id, float(total), tx_date, desc)
                    await update.message.reply_text(
                        f"✅ (IA) Transação registrada automaticamente:\nR$ {abs(total):.2f} em {tx_date.strftime('%d/%m/%Y')}\n{desc}"
                    )
                except Exception as e:
                    await update.message.reply_text(f"❌ Erro ao salvar transação: {str(e)}")
                return

            # Medium/low confidence but identified as payment -> ask for confirmation
            if is_bank_like:
                pending_receipts[user.id] = {
                    'filename': str(filename),
                    'values': [total],
                    'result': result,
                    'auto_candidate': True,
                    'total': float(total),
                    'date': tx_date,
                    'desc': desc,
                    'score': score
                }

                keyboard = [
                    [InlineKeyboardButton("Adicionar ao extrato", callback_data='add_receipt')],
                    [InlineKeyboardButton("Cancelar", callback_data='cancel_receipt')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await update.message.reply_text(
                    f"🔎 A IA detectou que esta imagem parece um comprovante (confiança {score:.2f}).\nValor estimado: R$ {abs(total):.2f} em {tx_date.strftime('%d/%m/%Y')}\nDeseja adicioná-lo ao seu extrato?",
                    reply_markup=reply_markup
                )
                return

            # Caso contrário, grava automaticamente mas informa que não foi identificado como comprovante
            try:
                db.add_transaction(user.id, float(total), tx_date, desc)
                await update.message.reply_text(
                    f"✅ Transação registrada:\nR$ {abs(total):.2f} em {tx_date.strftime('%d/%m/%Y')}\n{desc}"
                )
            except Exception as e:
                await update.message.reply_text(f"❌ Erro ao salvar transação: {str(e)}")
                return
    else:
        vals = result.get('values') or []
        # Interativo: oferece botões para escolher qual valor registrar
        if vals:
            keyboard = []
            for v in vals:
                # callback_data: choose:{amount}
                cb = f"choose:{v}"
                keyboard.append([InlineKeyboardButton(f"R$ {v:.2f}", callback_data=cb)])
            # botão cancelar
            keyboard.append([InlineKeyboardButton("Cancelar", callback_data="cancel_receipt")])
            reply_markup = InlineKeyboardMarkup(keyboard)

            # salva estado pendente para o usuário
            pending_receipts[user.id] = {
                'filename': str(filename),
                'values': vals,
                'result': result
            }

            await update.message.reply_text(
                "⚠️ Não foi possível identificar o valor total automaticamente. Selecione o valor correto:",
                reply_markup=reply_markup
            )
        else:
            msg = "⚠️ Não foi possível identificar o valor total automaticamente. Nenhum valor encontrado. Tente enviar uma imagem mais legível."
            await update.message.reply_text(msg)


async def callback_choose_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback quando o usuário escolhe um valor detectado na imagem."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    if not user or not user.id:
        await query.edit_message_text("⚠️ Erro: usuário não identificado.")
        return

    data = query.data or ''
    try:
        _, amt_str = data.split(':', 1)
        amount = float(amt_str)
    except Exception:
        await query.edit_message_text("⚠️ Dados inválidos.")
        return

    pending = pending_receipts.get(user.id)
    if not pending:
        await query.edit_message_text("⏳ Tempo expirado para essa ação. Envie a imagem novamente.")
        return

    # Pergunta se é crédito ou débito
    keyboard = [
        [InlineKeyboardButton("Crédito (+)", callback_data=f"confirm:{amount}:credit")],
        [InlineKeyboardButton("Débito (-)", callback_data=f"confirm:{amount}:debit")],
        [InlineKeyboardButton("Cancelar", callback_data="cancel_receipt")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"Você escolheu R$ {amount:.2f}. É crédito ou débito?", reply_markup=reply_markup)


async def callback_confirm_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback para quando o usuário confirma o tipo (crédito/debito) do valor selecionado."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    if not user or not user.id:
        await query.edit_message_text("⚠️ Erro: usuário não identificado.")
        return

    data = query.data or ''
    try:
        _, rest = data.split(':', 1)
        amt_str, tipo = rest.rsplit(':', 1)
        amount = float(amt_str)
    except Exception:
        await query.edit_message_text("⚠️ Dados inválidos.")
        return

    pending = pending_receipts.get(user.id)
    if not pending:
        await query.edit_message_text("⏳ Tempo expirado para essa ação. Envie a imagem novamente.")
        return

    # determina sinal
    if tipo == 'debit' or tipo == 'debito':
        value = -abs(amount)
        tipo_txt = 'gasto'
    else:
        value = abs(amount)
        tipo_txt = 'ganho'

    # tenta extrair data/desc do resultado OCR
    result = pending.get('result', {})
    tx_date = result.get('date') or datetime.date.today()
    desc = result.get('description') or 'Recibo (OCR)'

    try:
        db.add_transaction(user.id, float(value), tx_date, desc)
        await query.edit_message_text(f"✅ Transação registrada: R$ {abs(value):.2f} ({tipo_txt}) em {tx_date.strftime('%d/%m/%Y')}\n{desc}")
    except Exception as e:
        await query.edit_message_text(f"❌ Erro ao salvar transação: {str(e)}")

    # limpa pendente
    try:
        del pending_receipts[user.id]
    except Exception:
        pass


async def callback_cancel_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    if user and user.id in pending_receipts:
        try:
            del pending_receipts[user.id]
        except Exception:
            pass
    await query.edit_message_text("✅ Processo cancelado. Seus dados não foram salvos.")


async def callback_add_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback para confirmar adição de comprovante detectado pelo OCR."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    if not user or not user.id:
        await query.edit_message_text("⚠️ Erro: usuário não identificado.")
        return

    pending = pending_receipts.get(user.id)
    if not pending or not pending.get('auto_candidate'):
        await query.edit_message_text("⏳ Tempo expirado ou nenhum comprovante pendente. Envie a imagem novamente.")
        return

    total = pending.get('total')
    tx_date = pending.get('date') or datetime.date.today()
    desc = pending.get('desc') or 'Recibo (OCR)'

    try:
        db.add_transaction(user.id, float(total), tx_date, desc)
        await query.edit_message_text(f"✅ Transação registrada: R$ {abs(total):.2f} em {tx_date.strftime('%d/%m/%Y')}\n{desc}")
    except Exception as e:
        await query.edit_message_text(f"❌ Erro ao salvar transação: {str(e)}")

    try:
        del pending_receipts[user.id]
    except Exception:
        pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Olá! Eu sou seu bot de orçamento pessoal.\n\n"
        "� Formato: valor; data; descrição\n"
        "📊 Use /ajuda para ver exemplos e /resumo para ver seu saldo.\n\n"
        f"🔎 OCR disponível: {OCR_ENGINE} (PaddleOCR > EasyOCR > pytesseract)"
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
        "1️⃣ Uma transação por linha:\n"
        "✅ -200; 01/11/2025; comida\n\n"
        "2️⃣ Várias transações de uma vez:\n"
        "-200; 01/11/2025; comida\n"
        "+1500; 05/11/2025; salário\n"
        "-45.90; hoje; farmácia\n"
        "+150; ontem; venda\n\n"
        "💡 Valores positivos podem usar + ou nada:\n"
        "+1500 e 1500 são equivalentes\n\n"
        "💡 Você pode registrar até 20 transações por mensagem!\n\n"
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
        "2. Ver resumo de um mês específico:\n"
        "   /resumo mes MM/YYYY\n"
        "   Exemplo: /resumo mes 11/2025\n\n"
        "3. Extrato por mês específico:\n"
        "   /extrato mes MM/YYYY\n"
        "   Exemplo: /extrato mes 11/2025\n\n"
        "4. Extrato por período:\n"
        "   /extrato periodo DD/MM/YYYY DD/MM/YYYY\n"
        "   Exemplo: /extrato periodo 01/10/2025 31/10/2025\n\n"
        "5. Apagar todos os seus dados:\n"
        "   /limpar\n"
        "   ⚠️ Esta ação é irreversível!\n\n"
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

    # Limite de 20 linhas por mensagem para evitar spam
    LIMITE_LINHAS = 20
    
    # Divide a mensagem em linhas e remove linhas vazias
    linhas = [l.strip() for l in update.message.text.split('\n') if l.strip()]
    
    if len(linhas) > LIMITE_LINHAS:
        await update.message.reply_text(f"⚠️ Máximo de {LIMITE_LINHAS} transações por vez permitidas.")
        return
    
    user = update.effective_user
    if not user or not user.id:
        await update.message.reply_text("⚠️ Erro: não foi possível identificar o usuário.")
        return

    # Processar cada linha
    sucessos = []
    erros = []
    
    for linha in linhas:
        try:
            parsed = parse_message(linha)
            if not parsed:
                erros.append(f"❌ Linha inválida: {linha}")
                continue
                
            valor, data, desc = parsed
            
            # Adiciona à tabela
            db.add_transaction(user.id, valor, data, desc)
            
            # Define tipo para a mensagem
            tipo = "ganho" if valor >= 0 else "gasto"
                
            # Formata para o resumo
            desc_fmt = f" ({desc})" if desc else ""
            data_fmt = data.strftime("%d/%m/%Y")
            sucessos.append(f"✅ {tipo}: R$ {abs(valor):.2f} em {data_fmt}{desc_fmt}")
            
        except Exception as e:
            erros.append(f"❌ Erro na linha '{linha}': {str(e)}")
    
    # Prepara resposta consolidada
    mensagens = []
    
    if sucessos:
        mensagens.extend([
            "📝 Transações registradas:",
            *sucessos
        ])
        
    if erros:
        if mensagens:
            mensagens.append("")
        mensagens.extend([
            "⚠️ Problemas encontrados:",
            *erros
        ])
        
    if not mensagens:
        mensagens = ["⚠️ Nenhuma transação válida encontrada. Use /ajuda para ver o formato correto."]
    
    # Envia resposta
    resp = "\n".join(mensagens)
    await update.message.reply_text(resp)
    
    # Log da interação
    try:
        metadata = {
            'handler': 'registrar_valor',
            'total_linhas': len(linhas),
            'sucessos': len(sucessos),
            'erros': len(erros)
        }
        db.log_interaction(
            user.id,
            getattr(user, 'username', None),
            update.message.text,
            resp,
            metadata
        )
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
    
    args = context.args if hasattr(context, 'args') else []
    hoje = datetime.date.today()
    
    # Se tem argumento, verifica se é mês específico
    if args and args[0].lower() == "mes" and len(args) == 2:
        try:
            mes, ano = map(int, args[1].split('/'))
            if ano < 100:  # Converter YY para YYYY
                ano += 2000
            data_ref = datetime.date(ano, mes, 1)
            if mes == 12:
                fim_mes = datetime.date(ano, 12, 31)
            else:
                fim_mes = datetime.date(ano, mes + 1, 1) - datetime.timedelta(days=1)
                
            # Buscar transações do mês específico
            trans = db.get_user_transactions(user.id, data_ref, fim_mes)
            if not trans:
                text = f"📊 Nenhuma transação registrada em {data_ref.strftime('%m/%Y')}."
                await update.message.reply_text(text)
                return
                
            # Calcula totais usando list comprehension
            ganhos = sum(valor for _, valor, *_ in trans if valor > 0)
            gastos = sum(abs(valor) for _, valor, *_ in trans if valor < 0)
            saldo = ganhos - gastos
            
            # Organiza todas as transações do mês por data
            todas_transacoes = []
            for _, valor, data, desc, _ in sorted(trans, key=lambda x: datetime.date.fromisoformat(x[2]), reverse=True):
                data_fmt = datetime.date.fromisoformat(data).strftime("%d/%m")
                desc_fmt = f" ({desc})" if desc else ""
                sinal = "+" if valor > 0 else "-"
                todas_transacoes.append(f"{data_fmt}: {sinal}R$ {abs(valor):.2f}{desc_fmt}")
            
            # Prepara a mensagem de resumo do mês específico
            text = [
                f"📊 Resumo do mês ({data_ref.strftime('%m/%Y')}):",
                "",
                f"✅ Total de Ganhos: R$ {ganhos:.2f}",
                f"❌ Total de Gastos: R$ {gastos:.2f}",
                f"💰 Saldo Final: R$ {saldo:.2f}",
                "",
                "📝 Todas as transações do mês:"
            ]
            text.extend(todas_transacoes)
            
        except (ValueError, TypeError):
            await update.message.reply_text("⚠️ Formato inválido. Use: /resumo mes MM/YYYY")
            return
    else:
        # Busca todas as transações do usuário
        trans = db.get_user_transactions(user.id)
        if not trans:
            text = "📊 Nenhuma transação registrada ainda."
            await update.message.reply_text(text)
            return
            
        # Agrupa transações por mês
        meses = {}
        for _, valor, data, *_ in trans:
            data_obj = datetime.date.fromisoformat(data)
            mes_ano = data_obj.strftime("%m/%Y")
            
            if mes_ano not in meses:
                meses[mes_ano] = {"ganhos": 0, "gastos": 0}
                
            if valor > 0:
                meses[mes_ano]["ganhos"] += valor
            else:
                meses[mes_ano]["gastos"] += abs(valor)
        
        # Calcula totais gerais
        total_ganhos = sum(m["ganhos"] for m in meses.values())
        total_gastos = sum(m["gastos"] for m in meses.values())
        saldo_geral = total_ganhos - total_gastos
        
        # Prepara a mensagem de resumo geral
        text = [
            "📊 RESUMO GERAL:",
            "",
            f"✅ Total Geral de Ganhos: R$ {total_ganhos:.2f}",
            f"❌ Total Geral de Gastos: R$ {total_gastos:.2f}",
            f"💰 Saldo Geral: R$ {saldo_geral:.2f}",
            "",
            "📅 Resumo por mês:"
        ]
        
        # Adiciona resumo de cada mês (ordenado do mais recente para o mais antigo)
        for mes_ano in sorted(meses.keys(), reverse=True):
            dados_mes = meses[mes_ano]
            saldo_mes = dados_mes["ganhos"] - dados_mes["gastos"]
            sinal = "+" if saldo_mes >= 0 else "-"
            text.extend([
                "",
                f"📆 {mes_ano}:",
                f"   ✅ Ganhos: R$ {dados_mes['ganhos']:.2f}",
                f"   ❌ Gastos: R$ {dados_mes['gastos']:.2f}",
                f"   💰 Saldo: {sinal}R$ {abs(saldo_mes):.2f}"
            ])
            
    try:
        # Junta tudo em uma única string
        text = "\n".join(text)
        
        # Envia a mensagem
        await update.message.reply_text(text)
        
        # Log da interação
        try:
            db.log_interaction(user.id, getattr(user, 'username', None), '/resumo', text, 
                             {'command': 'resumo', 'type': 'success'})
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

# Estados para o fluxo de limpar dados
CONFIRMAR_CODIGO = 1

# Dicionário para armazenar códigos de confirmação temporários
codigos_confirmacao = {}

async def limpar_dados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o processo de limpeza de dados do usuário"""
    user = update.effective_user
    if not user or not user.id:
        await update.message.reply_text("⚠️ Erro: não foi possível identificar o usuário.")
        return ConversationHandler.END

    # Gera um código de confirmação aleatório de 6 caracteres
    codigo = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    codigos_confirmacao[user.id] = codigo

    text = (
        "⚠️ *ATENÇÃO: ESTA AÇÃO É IRREVERSÍVEL* ⚠️\n\n"
        "Você está prestes a apagar *TODOS* os seus dados, incluindo:\n"
        "- Todas as transações registradas\n"
        "- Todo o histórico de ganhos e gastos\n"
        "- Todos os seus registros no sistema\n\n"
        f"Para confirmar, envie exatamente o código: `{codigo}`\n\n"
        "Para cancelar, envie /cancelar"
    )
    
    await update.message.reply_text(text, parse_mode='Markdown')
    return CONFIRMAR_CODIGO

async def confirmar_limpeza(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirma e executa a limpeza dos dados"""
    user = update.effective_user
    if not user or not user.id:
        await update.message.reply_text("⚠️ Erro: não foi possível identificar o usuário.")
        return ConversationHandler.END

    codigo_enviado = update.message.text.strip()
    codigo_correto = codigos_confirmacao.get(user.id)

    if not codigo_correto:
        await update.message.reply_text("❌ Tempo expirado. Por favor, inicie o processo novamente com /limpar")
        return ConversationHandler.END

    if codigo_enviado != codigo_correto:
        await update.message.reply_text("❌ Código incorreto. Processo cancelado por segurança.")
        del codigos_confirmacao[user.id]
        return ConversationHandler.END

    try:
        # Remove o código de confirmação
        del codigos_confirmacao[user.id]
        
        # Apaga os dados do usuário
        db.delete_user_data(user.id)
        
        await update.message.reply_text(
            "✅ Todos os seus dados foram apagados com sucesso.\n"
            "Você pode começar a registrar novos dados quando quiser."
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao apagar dados: {str(e)}")
    
    return ConversationHandler.END

async def cancelar_limpeza(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela o processo de limpeza de dados"""
    user = update.effective_user
    if user and user.id in codigos_confirmacao:
        del codigos_confirmacao[user.id]
    
    await update.message.reply_text("✅ Processo de limpeza cancelado. Seus dados estão seguros.")
    return ConversationHandler.END

def main():
    # Inicializa banco de dados
    try:
        db.init_db()
    except Exception:
        # Não interrompe a inicialização do bot se houver problema no DB
        pass

    # Lê o token do ambiente para segurança; se não definido, usa o token embutido (fallback)
    token = os.environ.get('TELEGRAM_TOKEN')
    if token:
        print('[INFO] Usando TELEGRAM_TOKEN da variável de ambiente.')
    else:
        # Fallback para compatibilidade retroativa (recomendado: definir TELEGRAM_TOKEN no sistema)
        token = "8299762062:AAGPXqwgPciG07T896tso4RWOg7dges58fg"
        print('[WARN] TELEGRAM_TOKEN não definido; usando token embutido no código. Considere definir a variável de ambiente para maior segurança.')

    app = Application.builder().token(token).build()

    # Registra comandos visíveis no cliente Telegram (ajuda rápida ao digitar '/').
    # Evita usar asyncio.run() aqui porque pode fechar o event loop e causar erros
    # com a camada HTTP (httpx/anyio) ao inicializar o Application.
    try:
        import json
        import urllib.request

        cmds = [
            {"command": "start", "description": "Iniciar o bot / ver status"},
            {"command": "ajuda", "description": "Ver instruções de uso e formatos"},
            {"command": "resumo", "description": "Resumo geral ou de mês (/resumo mes MM/YYYY)"},
            {"command": "extrato", "description": "Extrato por mês ou período"},
            {"command": "limpar", "description": "Apagar todos os seus dados (confirmação)"}
        ]

        # Faz uma chamada HTTP síncrona para setMyCommands usando urllib (evita criar/fechar loops asyncio)
        if token:
            url = f"https://api.telegram.org/bot{token}/setMyCommands"
            data = json.dumps({"commands": cmds}).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    # não precisamos usar o retorno, apenas garantir que a chamada foi feita
                    resp.read()
            except Exception:
                # Não falhar o startup se não for possível registrar comandos
                pass
            # Tenta remover webhook (se existir) para evitar conflito com polling local
            try:
                url_del = f"https://api.telegram.org/bot{token}/deleteWebhook"
                data_del = json.dumps({"drop_pending_updates": True}).encode('utf-8')
                req_del = urllib.request.Request(url_del, data=data_del, headers={"Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(req_del, timeout=5) as resp_del:
                        resp_del.read()
                        print('[INFO] deleteWebhook enviado (drop_pending_updates=True)')
                except Exception:
                    # não bloquear inicialização se não for possível remover webhook
                    pass
            except Exception:
                # não bloquear inicialização caso a construção do request falhe
                pass
    except Exception:
        # Segurança: não deixar que problemas na tentativa de registrar comandos
        # interrompam a inicialização do bot.
        pass
    
    # Handler para limpar dados com confirmação
    limpar_handler = ConversationHandler(
        entry_points=[CommandHandler("limpar", limpar_dados)],
        states={
            CONFIRMAR_CODIGO: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirmar_limpeza)]
        },
        fallbacks=[CommandHandler("cancelar", cancelar_limpeza)]
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("resumo", resumo))
    app.add_handler(CommandHandler("extrato", extrato))
    app.add_handler(limpar_handler)
    # Handler para fotos/documentos de imagem: processa recibos
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, process_receipt))
    # Callback handlers para interação (escolha de valor e confirmação de tipo)
    app.add_handler(CallbackQueryHandler(callback_choose_value, pattern=r'^choose:'))
    app.add_handler(CallbackQueryHandler(callback_confirm_type, pattern=r'^confirm:'))
    app.add_handler(CallbackQueryHandler(callback_cancel_receipt, pattern=r'^cancel_receipt$'))
    app.add_handler(CallbackQueryHandler(callback_add_receipt, pattern=r'^add_receipt$'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_valor))
    app.run_polling()

if __name__ == "__main__":
    main()
