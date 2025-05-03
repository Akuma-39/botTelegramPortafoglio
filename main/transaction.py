from telegram import Update, BotCommand, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes,
    ConversationHandler, CallbackQueryHandler, filters
)
import os
from pathlib import Path
from dotenv import load_dotenv
import asyncpg
import csv
import io

# Stati della conversazione
DESCRIZIONE, IMPORTO = range(2)

# Carica variabili ambiente
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# DB
async def connect_db():
    return await asyncpg.create_pool(os.getenv("DATABASE_URL"))

async def crea_tabella(pool):
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS transazioni (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            descrizione TEXT,
            importo NUMERIC,
            data TIMESTAMP DEFAULT NOW()
        )
    """)

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Benvenuto nel Bot di Gestione Finanziaria!* 💰\n\n"
        "Ecco cosa puoi fare:\n"
        "• /spesa - Aggiungi una spesa\n"
        "• /entrata - Aggiungi un'entrata\n"
        "• /riepilogo - Mostra il riepilogo delle tue transazioni\n"
        "• /gestisci - Modifica o elimina una transazione\n"
        "• /esporta - Esporta in CSV\n"
        "• /annulla - Annulla l'operazione\n",
        parse_mode="Markdown"
    )

async def set_bot_commands(app):
    commands = [
        BotCommand("start", "Avvia il bot"),
        BotCommand("spesa", "Aggiungi una spesa"),
        BotCommand("entrata", "Aggiungi una entrata"),
        BotCommand("riepilogo", "Mostra il riepilogo"),
        BotCommand("gestisci", "Gestisci una transazione"),
        BotCommand("esporta", "Esporta in CSV"),
        BotCommand("annulla", "Annulla operazione")
    ]
    await app.bot.set_my_commands(commands)

# Conversazioni spesa / entrata
async def spesa_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['tipo'] = 'spesa'
    await update.message.reply_text("Scrivi la descrizione della spesa 🤑")
    return DESCRIZIONE

async def entrata_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['tipo'] = 'entrata'
    await update.message.reply_text("Scrivi la descrizione dell'entrata 💵")
    return DESCRIZIONE

async def descrizione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['descrizione'] = update.message.text
    await update.message.reply_text("Scrivi l'importo")
    return IMPORTO

async def importo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        valore = float(update.message.text)
        descrizione = context.user_data['descrizione']
        tipo = context.user_data['tipo']
        user_id = update.effective_user.id
        pool = context.application.bot_data["db_pool"]

        if tipo == 'spesa':
            valore = -abs(valore)
        else:
            valore = abs(valore)

        await pool.execute(
            "INSERT INTO transazioni (user_id, descrizione, importo) VALUES ($1, $2, $3)",
            user_id, descrizione, valore
        )
        await update.message.reply_text(f"✅ {'Spesa' if tipo == 'spesa' else 'Entrata'} aggiunta: {descrizione} {valore:+.2f} €")
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("Importo non valido. Inserisci un numero.")
        return IMPORTO

# /riepilogo
async def riepilogo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pool = context.application.bot_data["db_pool"]
    transazioni = await pool.fetch("SELECT descrizione, importo FROM transazioni WHERE user_id = $1 ORDER BY data DESC", user_id)

    if not transazioni:
        await update.message.reply_text("📂 Nessuna transazione trovata.")
        return

    totale = sum(t["importo"] for t in transazioni)
    lista = "\n".join([
        f"• *{t['descrizione']}*: {'-' if t['importo'] < 0 else ''}{abs(t['importo']):.2f} €"
        for t in transazioni
    ])

    await update.message.reply_text(
        f"📊 *Riepilogo:*\n\n{lista}\n\n💼 *Totale*: {totale:.2f} €",
        parse_mode="Markdown"
    )

# /esporta
async def esporta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pool = context.application.bot_data["db_pool"]
    transazioni = await pool.fetch("SELECT descrizione, importo, data FROM transazioni WHERE user_id = $1 ORDER BY data DESC", user_id)

    if not transazioni:
        await update.message.reply_text("📂 Nessuna transazione da esportare.")
        return

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Descrizione", "Importo", "Data"])
    for t in transazioni:
        writer.writerow([t["descrizione"], float(t["importo"]), t["data"].strftime("%Y-%m-%d %H:%M")])
    output.seek(0)

    await update.message.reply_document(
        document=io.BytesIO(output.getvalue().encode()),
        filename="transazioni.csv",
        caption="📤 Ecco il tuo CSV"
    )

# /gestisci
async def gestisci(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pool = context.application.bot_data["db_pool"]
    transazioni = await pool.fetch("SELECT id, descrizione, importo FROM transazioni WHERE user_id = $1 ORDER BY data DESC", user_id)

    if not transazioni:
        await update.message.reply_text("📂 Nessuna transazione trovata.")
        return

    context.user_data["transazioni"] = transazioni
    keyboard = [[
        InlineKeyboardButton(
            f"{t['descrizione']} {t['importo']:+.2f} €",
            callback_data=f"gestisci_{i}"
        )
    ] for i, t in enumerate(transazioni)]

    await update.message.reply_text(
        "🛠️ Seleziona una transazione:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def gestisci_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("gestisci_"):
        idx = int(data.split("_")[1])
        transazioni = context.user_data.get("transazioni")

        if not transazioni or idx >= len(transazioni):
            await query.edit_message_text("⚠️ Transazione non trovata.")
            return

        t = transazioni[idx]
        context.user_data.update({
            "indice": idx,
            "transazione_id": t["id"]
        })

        await query.edit_message_text(
            f"🔍 Hai selezionato:\n"
            f"*{t['descrizione']}* {t['importo']:+.2f} €\n\n"
            f"Cosa vuoi fare?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ Modifica", callback_data="modifica"),
                 InlineKeyboardButton("🗑️ Elimina", callback_data="elimina")]
            ]),
            parse_mode="Markdown"
        )

    elif data == "elimina":
        pool = context.application.bot_data["db_pool"]
        tid = context.user_data.get("transazione_id")
        await pool.execute("DELETE FROM transazioni WHERE id = $1", tid)
        await query.edit_message_text("🗑️ Transazione eliminata.")
        return ConversationHandler.END

    elif data == "modifica":
        await query.edit_message_text("✏️ Scrivi *descrizione importo* oppure solo *importo*", parse_mode="Markdown")
        return IMPORTO

async def aggiorna_transazione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        input_text = update.message.text.split()
        transazioni = context.user_data["transazioni"]
        idx = context.user_data["indice"]
        tid = context.user_data["transazione_id"]
        pool = context.application.bot_data["db_pool"]

        vecchio_importo = transazioni[idx]["importo"]

        if len(input_text) == 1:
            importo = float(input_text[0])
            importo = -abs(importo) if vecchio_importo < 0 else abs(importo)
            await pool.execute("UPDATE transazioni SET importo = $1 WHERE id = $2", importo, tid)
            await update.message.reply_text(f"✅ Importo aggiornato: {importo:.2f} €")
        else:
            descrizione = " ".join(input_text[:-1])
            importo = float(input_text[-1])
            importo = -abs(importo) if vecchio_importo < 0 else abs(importo)
            await pool.execute("UPDATE transazioni SET descrizione = $1, importo = $2 WHERE id = $3", descrizione, importo, tid)
            await update.message.reply_text(f"✅ Aggiornato: {descrizione} {importo:.2f} €")

        return ConversationHandler.END

    except Exception:
        await update.message.reply_text("❌ Formato non valido. Scrivi ad esempio: *Cena 25*", parse_mode="Markdown")
        return IMPORTO

# /annulla
async def annulla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Operazione annullata.")
    return ConversationHandler.END

# Comando sconosciuto
async def comando_non_riconosciuto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Comando non riconosciuto.")

# MAIN
async def main():
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    PORT = int(os.environ["PORT"])

    if not TOKEN or not WEBHOOK_URL:
        raise ValueError("Manca TELEGRAM_BOT_TOKEN o WEBHOOK_URL")

    db_pool = await connect_db()
    await crea_tabella(db_pool)

    app = ApplicationBuilder().token(TOKEN).build()
    app.bot_data["db_pool"] = db_pool
    await set_bot_commands(app)

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("riepilogo", riepilogo))
    app.add_handler(CommandHandler("gestisci", gestisci))
    app.add_handler(CommandHandler("esporta", esporta))
    app.add_handler(CommandHandler("annulla", annulla))
    app.add_handler(CallbackQueryHandler(gestisci_callback))
    app.add_handler(MessageHandler(filters.COMMAND, comando_non_riconosciuto))

    # Conversation handlers
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("spesa", spesa_start)],
        states={
            DESCRIZIONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, descrizione)],
            IMPORTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, importo)],
        },
        fallbacks=[CommandHandler("annulla", annulla)]
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("entrata", entrata_start)],
        states={
            DESCRIZIONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, descrizione)],
            IMPORTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, importo)],
        },
        fallbacks=[CommandHandler("annulla", annulla)]
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(gestisci_callback)],
        states={
            IMPORTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, aggiorna_transazione)],
        },
        fallbacks=[CommandHandler("annulla", annulla)],
        per_message=False
    ))

    # Avvia il webhook su Render
    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"{WEBHOOK_URL}/{TOKEN}",
    )

# Esegui
if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
