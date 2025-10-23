from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Banco de dados simples (poderia ser SQLite depois)
dados = {"ganhos": [], "gastos": []}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Olá! Eu sou seu bot de orçamento pessoal.\n\n"
        "📌 Me envie um valor (positivo = ganho, negativo = gasto).\n"
        "📊 Use /resumo para ver seu saldo mensal."
    )

async def registrar_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        valor = float(update.message.text.replace("R$", "").replace(",", ".").strip())
        if valor >= 0:
            dados["ganhos"].append(valor)
            await update.message.reply_text(f"✅ Ganho de R$ {valor:.2f} registrado!")
        else:
            dados["gastos"].append(abs(valor))
            await update.message.reply_text(f"❌ Gasto de R$ {abs(valor):.2f} registrado!")
    except:
        await update.message.reply_text("⚠️ Não entendi. Mande um número, ex: 1200 ou -250.")

async def resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ganhos = sum(dados["ganhos"])
    gastos = sum(dados["gastos"])
    saldo = ganhos - gastos
    await update.message.reply_text(
        f"📊 Resumo do mês:\n\n"
        f"✅ Ganhos: R$ {ganhos:.2f}\n"
        f"❌ Gastos: R$ {gastos:.2f}\n"
        f"💰 Saldo: R$ {saldo:.2f}"
    )

def main():
    app = Application.builder().token("8299762062:AAGPXqwgPciG07T896tso4RWOg7dges58fg").build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("resumo", resumo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_valor))
    app.run_polling()

if __name__ == "__main__":
    main()
