from telegram import Update, BotCommand, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, ConversationHandler, CallbackQueryHandler, filters
import os
from pathlib import Path
from dotenv import load_dotenv
import asyncpg
import csv
import io


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
# Stati della conversazione
DESCRIZIONE, IMPORTO = range(2)

# Lista globale per memorizzare le spese
spese = []

# Funzione per esportare le spese in CSV
async def esporta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pool = context.application.bot_data["db_pool"]

    transazioni = await pool.fetch(
        "SELECT descrizione, importo, data FROM transazioni WHERE user_id = $1 ORDER BY data DESC",
        user_id
    )

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
        caption="📤 Ecco il tuo file CSV con le transazioni"
    )

# Comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Benvenuto nel Bot di Gestione Finanziaria!* 💰\n\n"
        "Ecco cosa puoi fare:\n"
        "• `/spesa` - Aggiungi una spesa\n"
        "• `/entrata` - Aggiungi un'entrata\n"
        "• `/riepilogo` - Mostra il riepilogo delle tue transazioni\n"
        "• `/gestisci` - Modifica o elimina una transazione\n"
        "• `/annulla` - Annulla l'operazione corrente\n\n"
        "Inizia subito a gestire le tue finanze! 🚀",
        parse_mode="Markdown"
    )

async def set_bot_commands(app):
    commands = [
        BotCommand("start", "Avvia il bot"),
        BotCommand("spesa", "Aggiungi una spesa"),
        BotCommand("entrata", "Aggiungi una entrata"),
        BotCommand("riepilogo", "Mostra il riepilogo delle spese"),
        BotCommand("annulla", "Annulla l'operazione corrente"),
        BotCommand("gestisci", "Gestisci una transazione"),
        BotCommand("esporta", "Esporta le transazioni in CSV"),

    ]
    await app.bot.set_my_commands(commands)

# Conversazione /spesa
async def spesa_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['tipo'] = 'spesa'
    await update.message.reply_text("Scrivi la descrizione della spesa 🤑")
    return DESCRIZIONE

# Conversazione /entrata
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
        importo = float(update.message.text)  # Converte il testo in un numero decimale
        descrizione = context.user_data['descrizione']  # Prendi la descrizione dal contesto
        tipo = context.user_data.get('tipo')  # Tipo (spesa o entrata)
        user_id = update.effective_user.id  # ID dell'utente

        # Se è una spesa, l'importo sarà negativo, altrimenti positivo
        if tipo == 'spesa':
            importo = -abs(importo)  # Imposta l'importo come negativo per una spesa
        else:
            importo = abs(importo)  # Assicura che l'importo sia positivo per un'entrata

        # Connessione al pool DB
        pool = context.application.bot_data["db_pool"]
        # Inserisci la transazione nel DB
        await pool.execute(
            "INSERT INTO transazioni (user_id, descrizione, importo) VALUES ($1, $2, $3)",
            user_id, descrizione, importo
        )

        # Risposta utente
        await update.message.reply_text(
            f"✅ {'Spesa' if tipo == 'spesa' else 'Entrata'} aggiunta: {descrizione} {importo:+.2f} €"
        )

        return ConversationHandler.END  # Termina la conversazione

    except ValueError:
        # Se l'importo non è valido
        await update.message.reply_text("Importo non valido. Per favore, scrivi un numero.")
        return IMPORTO



# /gestisci
async def gestisci(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pool = context.application.bot_data["db_pool"]

    transazioni = await pool.fetch(
        "SELECT id, descrizione, importo FROM transazioni WHERE user_id = $1 ORDER BY data DESC",
        user_id
    )

    if not transazioni:
        await update.message.reply_text("📂 *Non ci sono transazioni da gestire.*", parse_mode="Markdown")
        return

    context.user_data['transazioni'] = transazioni  # salviamo in memoria per callback successive

    keyboard = [
        [InlineKeyboardButton(f"{t['descrizione']}: {'-' if t['importo'] < 0 else ''}{abs(t['importo']):.2f} €", callback_data=f"gestisci_{i}")]
        for i, t in enumerate(transazioni)
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🛠️ *Seleziona una transazione da gestire:*",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def gestisci_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("gestisci_"):
        indice = int(data.split("_")[1])
        transazioni = context.user_data.get('transazioni')
        if not transazioni or indice >= len(transazioni):
            await query.edit_message_text("⚠️ Errore: transazione non trovata.")
            return

        transazione = transazioni[indice]
        context.user_data['indice'] = indice
        context.user_data['transazione_id'] = transazione['id']

        keyboard = [
            [InlineKeyboardButton("✏️ Modifica", callback_data="modifica"),
             InlineKeyboardButton("🗑️ Elimina", callback_data="elimina")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"🔍 *Hai selezionato:*\n"
            f"• *{transazione['descrizione']}*: {'-' if transazione['importo'] < 0 else ''}{abs(transazione['importo']):.2f} €\n\n"
            "Cosa vuoi fare?",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    elif data == "modifica":
        await query.edit_message_text(
            "✏️ *Scrivi la nuova descrizione e il nuovo importo (o solo il nuovo importo) separati da uno spazio*",
            parse_mode="Markdown"
        )
        return IMPORTO

    elif data == "elimina":
        transazione_id = context.user_data.get('transazione_id')
        if transazione_id:
            pool = context.application.bot_data["db_pool"]
            await pool.execute("DELETE FROM transazioni WHERE id = $1", transazione_id)
            await query.edit_message_text("🗑️ *Transazione eliminata con successo!*", parse_mode="Markdown")
        return ConversationHandler.END


    elif data == "modifica":
        await query.edit_message_text(
            "✏️ *Scrivi la nuova descrizione e il nuovo importo (o solo il nuovo importo) separati da uno spazio*",
            parse_mode="Markdown"
        )
        return IMPORTO

    elif data == "elimina":
        transazione_id = context.user_data.get('transazione_id')
        if transazione_id:
            pool = context.application.bot_data["db_pool"]
            await pool.execute("DELETE FROM transazioni WHERE id = $1", transazione_id)
            await query.edit_message_text("🗑️ *Transazione eliminata con successo!*", parse_mode="Markdown")
        return ConversationHandler.END


# Aggiorna transazione
async def aggiorna_transazione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        dati = update.message.text.split()
        transazione_id = context.user_data.get('transazione_id')
        transazioni = context.user_data.get('transazioni')
        indice = context.user_data.get('indice')

        if transazione_id is None or transazioni is None or indice is None:
            await update.message.reply_text("❌ Errore: Nessuna transazione selezionata per la modifica.")
            return ConversationHandler.END

        pool = context.application.bot_data["db_pool"]

        if len(dati) == 1:
            importo = float(dati[0])
            vecchio_importo = transazioni[indice]['importo']
            importo = -abs(importo) if vecchio_importo < 0 else abs(importo)

            await pool.execute("UPDATE transazioni SET importo = $1 WHERE id = $2", importo, transazione_id)
            await update.message.reply_text(f"✅ Importo aggiornato: {importo:.2f} €")

        elif len(dati) >= 2:
            descrizione = " ".join(dati[:-1])
            importo = float(dati[-1])
            vecchio_importo = transazioni[indice]['importo']
            importo = -abs(importo) if vecchio_importo < 0 else abs(importo)

            await pool.execute(
                "UPDATE transazioni SET descrizione = $1, importo = $2 WHERE id = $3",
                descrizione, importo, transazione_id
            )
            await update.message.reply_text(f"✅ Transazione aggiornata: {descrizione} {importo:.2f} €")

        else:
            raise ValueError("Formato non valido. Mi servono almeno una descrizione e un importo.")

        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text(
            "❌ Formato non valido. Scrivi:\n"
            "• Solo l'importo (es. `50`)\n"
            "• Oppure descrizione e importo separati da uno spazio (es. `Cena 50`)",
            parse_mode="Markdown"
        )
        return IMPORTO



# /annulla
async def annulla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operazione annullata.", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END

# /riepilogo
async def riepilogo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pool = context.application.bot_data["db_pool"]

    transazioni = await pool.fetch(
        "SELECT descrizione, importo FROM transazioni WHERE user_id = $1 ORDER BY data DESC",
        user_id
    )

    if not transazioni:
        await update.message.reply_text("📂 *Nessuna transazione registrata.*", parse_mode="Markdown")
        return

    totale = sum(t['importo'] for t in transazioni)
    lista = "\n".join([
        f"• *{t['descrizione']}*: {'-' if t['importo'] < 0 else ''}{abs(t['importo']):.2f} €"
        for t in transazioni
    ])
    await update.message.reply_text(
        f"📊 *Riepilogo delle tue transazioni:*\n\n{lista}\n\n"
        f"💼 *Totale*: `{totale:.2f} €`",
        parse_mode="Markdown"
    )


# Catch comandi non validi
async def comando_non_riconosciuto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ *Comando non riconosciuto!*\n"
        "Usa un comando valido come `/spesa`, `/entrata` o `/riepilogo`.",
        parse_mode="Markdown"
    )

async def messaggio_generico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚠️ --- Non ho capito. Usa un comando come /spesa, /entrata o /riepilogo --- ⚠️")

from fastapi import FastAPI
from starlette.requests import Request
from telegram.ext import Application

fastapi_app = FastAPI()

@fastapi_app.get("/")
async def root():
    return {"status": "ok", "message": "🤖 Bot attivo!"}

# Main
async def main():
    env_path = Path(__file__).parent / ".env"
    load_dotenv(dotenv_path=env_path)

    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")  # es. https://nome-servizio.onrender.com
    PORT = int(os.getenv("PORT", 8000))  # Render assegna la porta dinamicamente

    if not TOKEN or not RENDER_EXTERNAL_URL:
        raise ValueError("TOKEN o RENDER_EXTERNAL_URL mancante.")

    db_pool = await connect_db()
    await crea_tabella(db_pool)

    app = ApplicationBuilder().token(TOKEN).build()
    app.bot_data["db_pool"] = db_pool

    await set_bot_commands(app)

    # I tuoi handler (non modificare)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("riepilogo", riepilogo))
    app.add_handler(CommandHandler("gestisci", gestisci))
    app.add_handler(CommandHandler("esporta", esporta))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("spesa", spesa_start)],
        states={DESCRIZIONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, descrizione)],
                IMPORTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, importo)]},
        fallbacks=[CommandHandler("annulla", annulla)],
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("entrata", entrata_start)],
        states={DESCRIZIONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, descrizione)],
                IMPORTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, importo)]},
        fallbacks=[CommandHandler("annulla", annulla)],
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(gestisci_callback)],
        states={IMPORTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, aggiorna_transazione)]},
        fallbacks=[CommandHandler("annulla", annulla)],
        per_message=False,
    ))

    # ✅ Esegui con webhook
    print("🤖 Bot in esecuzione con webhook...")
    app.web_app = fastapi_app
    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"{RENDER_EXTERNAL_URL}/webhook",
    )

    if __name__ == "__main__":
        import asyncio
        asyncio.run(main())



