from telegram import Update, BotCommand, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, ConversationHandler, CallbackQueryHandler, filters
import os
from pathlib import Path
from dotenv import load_dotenv

# Stati della conversazione
DESCRIZIONE, IMPORTO = range(2)

# Lista globale per memorizzare le spese
spese = []

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
        importo = float(update.message.text)
        descrizione = context.user_data['descrizione']
        tipo = context.user_data.get('tipo')
        if tipo == 'spesa':
            spese.append((descrizione, -importo))
            await update.message.reply_text(f"✅ Spesa aggiunta: {descrizione} - {importo:.2f} €")
        else:
            spese.append((descrizione, importo))
            await update.message.reply_text(f"✅ Entrata aggiunta: {descrizione} + {importo:.2f} €")
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Importo non valido. Per favore, scrivi un numero.")
        return IMPORTO

# /gestisci
async def gestisci(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not spese:
        await update.message.reply_text("📂 *Non ci sono transazioni da gestire.*", parse_mode="Markdown")
        return

    keyboard = [
        [InlineKeyboardButton(f"{descrizione}: {'-' if importo < 0 else ''}{abs(importo):.2f} €", callback_data=f"gestisci_{i}")]
        for i, (descrizione, importo) in enumerate(spese)
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🛠️ *Seleziona una transazione da gestire:*",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# Callback
async def gestisci_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("gestisci_"):
        indice = int(data.split("_")[1])
        context.user_data['indice'] = indice

        keyboard = [
            [InlineKeyboardButton("✏️ Modifica", callback_data="modifica"),
             InlineKeyboardButton("🗑️ Elimina", callback_data="elimina")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"🔍 *Hai selezionato:*\n"
            f"• *{spese[indice][0]}*: {'-' if spese[indice][1] < 0 else ''}{abs(spese[indice][1]):.2f} €\n\n"
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
        indice = context.user_data.get('indice')
        if indice is not None:
            transazione = spese.pop(indice)
            await query.edit_message_text(
                f"🗑️ *Transazione eliminata:*\n"
                f"• *{transazione[0]}*: {'-' if transazione[1] < 0 else ''}{abs(transazione[1]):.2f} €",
                parse_mode="Markdown"
            )
        return ConversationHandler.END

# Aggiorna transazione
async def aggiorna_transazione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if 'indice' not in context.user_data:
            await update.message.reply_text("❌ Errore: Nessuna transazione selezionata per la modifica.")
            return ConversationHandler.END

        dati = update.message.text.split()
        indice = context.user_data['indice']

        if len(dati) == 1:
            importo = float(dati[0])
            importo = -abs(importo) if spese[indice][1] < 0 else abs(importo)
            spese[indice] = (spese[indice][0], importo)
            await update.message.reply_text(
                f"✅ Importo aggiornato:\n• *{spese[indice][0]}*: {importo:.2f} €",
                parse_mode="Markdown"
            )
        elif len(dati) >= 2:
            descrizione = " ".join(dati[:-1])
            importo = float(dati[-1])
            importo = -abs(importo) if spese[indice][1] < 0 else abs(importo)
            spese[indice] = (descrizione, importo)
            await update.message.reply_text(
                f"✅ Transazione aggiornata:\n• *{descrizione}*: {importo:.2f} €",
                parse_mode="Markdown"
            )
        else:
            raise ValueError("Formato non valido.")

        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text(
            "❌ Formato non valido. Per favore, scrivi:\n"
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
    if not spese:
        await update.message.reply_text("📂 *Nessuna transazione registrata.*", parse_mode="Markdown")
        return

    totale = sum(importo for _, importo in spese)
    lista = "\n".join([
        f"• *{descrizione}*: {'-' if importo < 0 else ''}{abs(importo):.2f} €"
        for descrizione, importo in spese
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

# Main
async def main():
    env_path = Path(__file__).parent / ".env"
    load_dotenv(dotenv_path=env_path)

    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        raise ValueError("Il token del bot non è stato fornito.")

    app = ApplicationBuilder().token(TOKEN).build()
    await set_bot_commands(app)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("riepilogo", riepilogo))
    app.add_handler(CommandHandler("gestisci", gestisci))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("spesa", spesa_start)],
        states={
            DESCRIZIONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, descrizione)],
            IMPORTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, importo)],
        },
        fallbacks=[CommandHandler("annulla", annulla)],
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("entrata", entrata_start)],
        states={
            DESCRIZIONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, descrizione)],
            IMPORTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, importo)],
        },
        fallbacks=[CommandHandler("annulla", annulla)],
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(gestisci_callback)],
        states={
            IMPORTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, aggiorna_transazione)],
        },
        fallbacks=[CommandHandler("annulla", annulla)],
        per_message=False,
    ))

    app.add_handler(MessageHandler(filters.COMMAND, comando_non_riconosciuto))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, messaggio_generico))

    print("🤖 Bot in esecuzione...")
    await app.run_polling()

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    import asyncio
    asyncio.run(main())
