from ast import Call
from importlib.metadata import EntryPoint
from matplotlib.backend_bases import key_press_handler
from matplotlib.pylab import rand
from telegram import Bot, Update, BotCommand, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, ConversationHandler, CallbackQueryHandler, filters
import os
from pathlib import Path
from dotenv import load_dotenv
import asyncpg
import csv
import io
from aiohttp import web
import asyncio  # Importa asyncio per gestire l'event loop
import nest_asyncio
import matplotlib.pyplot as plt
from metrics import handle_metrics
from datetime import datetime, timedelta


# Applica nest_asyncio per evitare conflitti con l'event loop
nest_asyncio.apply()

async def connect_db():
    return await asyncpg.create_pool(os.getenv("DATABASE_URL"))

async def crea_tabella(pool):
    # Crea la tabella delle transazioni
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS transazioni (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            descrizione TEXT,
            importo NUMERIC,
            data TIMESTAMP DEFAULT NOW(),
            categoria_id INTEGER,
            metodoPagamento INTEGER,
            FOREIGN KEY (metodoPagamento) REFERENCES carte(id) ON DELETE SET NULL,
            FOREIGN KEY (categoria_id) REFERENCES categorie(id) ON DELETE SET NULL
        )
    """)
    # Crea la tabella delle categorie
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS categorie (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            nome TEXT NOT NULL,
            UNIQUE(user_id, nome)  -- Ogni utente può avere categorie uniche
        )
    """)
    # Crea la tabella dei metodi di pagamento
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS carte (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            nome TEXT NOT NULL,
            UNIQUE(user_id, nome)
        )
    """)

# Stati della conversazione
DESCRIZIONE, IMPORTO, CATEGORIA, CARTA = range(4)

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
from telegram.helpers import escape_markdown

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    testo = (
        "👋 *Benvenuto nel Bot di Gestione Finanziaria!* 💰\n\n"
        "Ecco cosa puoi fare:\n"
        "• /spesa - Aggiungi una spesa\n"
        "• /entrata - Aggiungi un'entrata\n"
        "• /riepilogo [giorni] - Mostra il riepilogo delle tue transazioni negli ultimi [giorni] (se non specificato 30gg)\n"
        "• /gestisci - Modifica o elimina una transazione\n"
        "• /esporta - Esporta le tue transazioni\n\n"
        "• /grafico - Visualizza il grafico delle tue finanze\n\n"
        "• /categorie - Per visualizzare tutte le categorie presenti\n\n"
        "Inizia subito a gestire le tue finanze! 🚀"
    )

    # Escapa i caratteri speciali
    testo = escape_markdown(testo, version=2)

    await update.message.reply_text(testo, parse_mode="MarkdownV2")

async def set_bot_commands(app):
    commands = [
        BotCommand("start", "Avvia il bot"),
        BotCommand("annulla", "Annulla l'operazione corrente"),
        BotCommand("spesa", "Aggiungi una spesa"),
        BotCommand("entrata", "Aggiungi una entrata"),
        BotCommand("riepilogo", "Mostra il riepilogo delle spese"),
        BotCommand("aggiungi_categoria", "Aggiungi una nuova categoria"),
        BotCommand("categorie", "Mostra le tue categorie"),
        BotCommand("aggiungi_carta", "Aggiungi un metodo di pagamento"),
        BotCommand("carte", "Mostra i tuoi metodi di pagamento"),
        BotCommand("grafico", "Visualizza il grafico delle finanze"),
        BotCommand("gestisci", "Gestisci una transazione"),
        BotCommand("gestisci_categoria", "Gestisci una categoria"),
        BotCommand("esporta", "Esporta le transazioni in CSV")
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
        context.user_data['importo'] = importo  # Salva l'importo nel contesto

        # Recupera le categorie dal database
        user_id = update.effective_user.id
        pool = context.application.bot_data["db_pool"]
        categorie = await pool.fetch(
            "SELECT id, nome FROM categorie WHERE user_id = $1 ORDER BY nome",
            user_id
        )

        if not categorie:
            await update.message.reply_text(
                "⚠️ Non hai ancora creato categorie. Usa il comando /aggiungi_categoria per crearne una e riprovare."
            )
            return ConversationHandler.END

        # Crea una tastiera inline con le categorie
        keyboard = [
            [InlineKeyboardButton(c['nome'], callback_data=f"categoria_{c['id']}")]
            for c in categorie
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "Seleziona una categoria per questa transazione:",
            reply_markup=reply_markup
        )
        return CATEGORIA

    except ValueError:
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

# Stato per aggiungere una categoria
NOME_CATEGORIA = range(1)

async def gestisci_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # Log per debug
    print(f"Callback data ricevuto: {data}")

    # Gestione delle transazioni
    if data.startswith("gestisci_") and not data.startswith("gestisci_categoria_"):
        try:
            indice = int(data.split("_")[1])  # Ottieni l'indice della transazione
            transazioni = context.user_data.get('transazioni')
            if not transazioni or indice >= len(transazioni):
                await query.edit_message_text("⚠️ Errore: transazione non trovata.")
                return

            transazione = transazioni[indice]
            context.user_data['indice'] = indice
            context.user_data['transazione_id'] = transazione['id']

            keyboard = [
                [InlineKeyboardButton("✏️ Modifica", callback_data="modifica_transazione"),
                 InlineKeyboardButton("🗑️ Elimina", callback_data="elimina_transazione")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"🔍 *Hai selezionato:*\n"
                f"• *{transazione['descrizione']}*: {'-' if transazione['importo'] < 0 else ''}{abs(transazione['importo']):.2f} €\n\n"
                "Cosa vuoi fare?",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        except (IndexError, ValueError):
            await query.edit_message_text("⚠️ Errore: Formato del callback non valido.")
            return

    # Gestione delle categorie
    elif data.startswith("gestisci_categoria_"):
        try:
            categoria_id = int(data.split("_")[2])  # Ottieni l'ID della categoria
            context.user_data['categoria_id'] = categoria_id

            # Recupera il nome della categoria dal database
            pool = context.application.bot_data["db_pool"]
            categoria = await pool.fetchrow(
                "SELECT nome FROM categorie WHERE id = $1",
                categoria_id
            )

            if not categoria:
                await query.edit_message_text("⚠️ Categoria non trovata.")
                return ConversationHandler.END

            context.user_data['categoria_nome'] = categoria['nome']

            # Mostra le opzioni di gestione
            keyboard = [
                [InlineKeyboardButton("✏️ Modifica", callback_data="modifica_categoria"),
                 InlineKeyboardButton("🗑️ Elimina", callback_data="elimina_categoria")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                f"🔍 *Hai selezionato la categoria:* {categoria['nome']}\n\n"
                "Cosa vuoi fare?",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        except (IndexError, ValueError):
            await query.edit_message_text("⚠️ Errore: Formato del callback non valido.")
            return ConversationHandler.END

    # Modifica transazione
    elif data == "modifica_transazione":
        await query.edit_message_text(
            "✏️ *Scrivi la nuova descrizione e il nuovo importo (o solo il nuovo importo) separati da uno spazio*",
            parse_mode="Markdown"
        )
        return IMPORTO

    # Elimina transazione
    elif data == "elimina_transazione":
        transazione_id = context.user_data.get('transazione_id')
        if transazione_id:
            pool = context.application.bot_data["db_pool"]
            await pool.execute("DELETE FROM transazioni WHERE id = $1", transazione_id)
            await query.edit_message_text("🗑️ *Transazione eliminata con successo!*", parse_mode="Markdown")
        return ConversationHandler.END

    # Modifica categoria
    elif data == "modifica_categoria":
        if 'categoria_id' in context.user_data:
            await query.edit_message_text("✏️ Scrivi il nuovo nome della categoria:")
            return NOME_CATEGORIA
        else:
            await query.edit_message_text("⚠️ Errore: Nessuna categoria selezionata per la modifica.")
            return ConversationHandler.END

    # Elimina categoria
    elif data == "elimina_categoria":
        categoria_id = context.user_data.get('categoria_id')
        if categoria_id:
            pool = context.application.bot_data["db_pool"]
            try:
                await pool.execute("DELETE FROM categorie WHERE id = $1", categoria_id)
                await query.edit_message_text("🗑️ Categoria eliminata con successo!")
            except asyncpg.ForeignKeyViolationError:
                await query.edit_message_text("⚠️ Errore: Non puoi eliminare una categoria associata a transazioni.")
        else:
            await query.edit_message_text("⚠️ Errore: Nessuna categoria selezionata per l'eliminazione.")
            return ConversationHandler.END
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
            "• Solo l'importo (es. 50)\n"
            "• Oppure descrizione e importo separati da uno spazio (es. Cena 50)",
            parse_mode="Markdown"
        )
        return IMPORTO

async def seleziona_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Ottieni l'ID della categoria selezionata
    if query.data.startswith("categoria_"):
        categoria_id = int(query.data.split("_")[1])
        context.user_data['categoria_id'] = categoria_id

        # Recupera le carte dal database
        user_id = query.from_user.id
        pool = context.application.bot_data["db_pool"]
        carte = await pool.fetch(
            "SELECT id, nome FROM carte WHERE user_id = $1 ORDER BY nome",
            user_id
        )

        if not carte:
            await query.edit_message_text(
                "⚠️ Non hai ancora aggiunto metodi di pagamento. Usa il comando /aggiungi_carta per crearne uno."
            )
            return ConversationHandler.END

        # Crea una tastiera inline con le carte
        keyboard = [
            [InlineKeyboardButton(c['nome'], callback_data=f"carta_{c['id']}")]
            for c in carte
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "Seleziona una carta per questa transazione:",
            reply_markup=reply_markup
        )
        return CARTA

async def seleziona_carta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Ottieni l'ID della carta selezionata
    if query.data.startswith("carta_"):
        carta_id = int(query.data.split("_")[1])
        context.user_data['carta_id'] = carta_id

        # Salva la transazione nel database
        descrizione = context.user_data['descrizione']
        importo = context.user_data['importo']
        tipo = context.user_data['tipo']
        user_id = query.from_user.id
        categoria_id = context.user_data['categoria_id']

        # Se è una spesa, l'importo sarà negativo, altrimenti positivo
        if tipo == 'spesa':
            importo = -abs(importo)
        else:
            importo = abs(importo)

        pool = context.application.bot_data["db_pool"]
        await pool.execute(
            "INSERT INTO transazioni (user_id, descrizione, importo, categoria_id, metodoPagamento) VALUES ($1, $2, $3, $4, $5)",
            user_id, descrizione, importo, categoria_id, carta_id
        )

        await query.edit_message_text(
            f"✅ {'Spesa' if tipo == 'spesa' else 'Entrata'} aggiunta: {descrizione} {importo:+.2f} €"
        )
        return ConversationHandler.END

# /annulla
async def annulla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operazione annullata.", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END

# /riepilogo
async def riepilogo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 Tutte", callback_data="riepilogo_generale")],
        [InlineKeyboardButton("📊 Categoria", callback_data="riepilogo_categorie")],
        [InlineKeyboardButton("📉 Spese", callback_data="riepilogo_spese")],
        [InlineKeyboardButton("📈 Entrate", callback_data="riepilogo_entrate")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Scegli il tipo di riepilogo che vuoi visualizzare:",
        reply_markup=reply_markup
    )
# Callback per il riepilogo
async def riepilogo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    pool = context.application.bot_data["db_pool"]

    if query.data == "riepilogo_generale":
        # Mostra tutte le transazioni (puoi riutilizzare la logica già presente)
        await query.edit_message_text("📊 Riepilogo di tutte le transazioni in arrivo...")
        await mostra_riepilogo_generale(query, pool, user_id)
    elif query.data == "riepilogo_spese":
        await query.edit_message_text("📉 Riepilogo delle sole spese in arrivo...")
        await mostra_riepilogo_spese(query, pool, user_id)
    elif query.data == "riepilogo_entrate":
        await query.edit_message_text("📈 Riepilogo delle sole entrate in arrivo...")
        await mostra_riepilogo_entrate(query, pool, user_id)
    elif query.data == "riepilogo_categorie":
        # Mostra la tastiera con le categorie
        categorie = await pool.fetch(
            "SELECT id, nome FROM categorie WHERE user_id = $1 ORDER BY nome",
            user_id
        )
        if not categorie:
            await query.edit_message_text("📂 Non hai ancora creato categorie.")
            return
        keyboard = [
            [InlineKeyboardButton(c['nome'], callback_data=f"riepilogo_categoria_{c['id']}")]
            for c in categorie
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "📋 Scegli una categoria:",
            reply_markup=reply_markup
        )
    elif query.data.startswith("riepilogo_categoria_"):
        categoria_id = int(query.data.split("_")[-1])
        await mostra_riepilogo_per_categoria(query, pool, user_id, categoria_id)

async def mostra_riepilogo_generale(query, pool, user_id):
    transazioni = await pool.fetch(
        "SELECT descrizione, importo, data FROM transazioni WHERE user_id = $1 ORDER BY data DESC",
        user_id
    )
    if not transazioni:
        await query.edit_message_text("📂 Nessuna transazione trovata.")
        return
    totale = sum(float(t['importo']) for t in transazioni)
    testo = "\n".join([f"• {t['descrizione']}: {t['importo']:.2f} € ({t['data'].strftime('%d/%m/%Y')})" for t in transazioni])
    await query.edit_message_text(f"📊 Tutte le transazioni:\n\n{testo}\n\n<b>Totale:</b> {totale:.2f} €", parse_mode="HTML")

async def mostra_riepilogo_spese(query, pool, user_id):
    transazioni = await pool.fetch(
        "SELECT descrizione, importo, data FROM transazioni WHERE user_id = $1 AND importo < 0 ORDER BY data DESC",
        user_id
    )
    if not transazioni:
        await query.edit_message_text("📉 Nessuna spesa trovata.")
        return
    totale = sum(float(t['importo']) for t in transazioni)
    testo = "\n".join([f"• {t['descrizione']}: {t['importo']:.2f} € ({t['data'].strftime('%d/%m/%Y')})" for t in transazioni])
    await query.edit_message_text(f"📉 Solo spese:\n\n{testo}\n\n<b>Totale spese:</b> {totale:.2f} €", parse_mode="HTML")

async def mostra_riepilogo_entrate(query, pool, user_id):
    transazioni = await pool.fetch(
        "SELECT descrizione, importo, data FROM transazioni WHERE user_id = $1 AND importo > 0 ORDER BY data DESC",
        user_id
    )
    if not transazioni:
        await query.edit_message_text("📈 Nessuna entrata trovata.")
        return
    totale = sum(float(t['importo']) for t in transazioni)
    testo = "\n".join([f"• {t['descrizione']}: {t['importo']:.2f} € ({t['data'].strftime('%d/%m/%Y')})" for t in transazioni])
    await query.edit_message_text(f"📈 Solo entrate:\n\n{testo}\n\n<b>Totale entrate:</b> {totale:.2f} €", parse_mode="HTML")

async def mostra_riepilogo_per_categoria(query, pool, user_id, categoria_id):
    transazioni = await pool.fetch(
        "SELECT descrizione, importo, data FROM transazioni WHERE user_id = $1 AND categoria_id = $2 ORDER BY data DESC",
        user_id, categoria_id
    )
    if not transazioni:
        await query.edit_message_text("📋 Nessuna transazione trovata per questa categoria.")
        return
    totale = sum(float(t['importo']) for t in transazioni)
    testo = "\n".join([f"• {t['descrizione']}: {t['importo']:.2f} € ({t['data'].strftime('%d/%m/%Y')})" for t in transazioni])
    await query.edit_message_text(f"📋 Transazioni per questa categoria:\n\n{testo}\n\n<b>Totale categoria:</b> {totale:.2f} €", parse_mode="HTML")

# Catch comandi non validi
async def comando_non_riconosciuto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ *Comando non riconosciuto!*\n"
        "Usa un comando valido come /spesa, /entrata o /riepilogo.",
        parse_mode="Markdown"
    )

async def messaggio_generico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚠️ --- Non ho capito. Usa un comando come /spesa, /entrata o /riepilogo --- ⚠️")

# Definisci etichette per grafici
def format_labels(pct, all_vals):
    absolute = int(round(pct / 100. * sum(all_vals)))
    return f"{absolute} €\n({pct:.1f}%)"

# Funzione per generare il grafico a torta
async def grafico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Crea la tastiera inline con le opzioni
    keyboard = [
        [InlineKeyboardButton("📊 Generale", callback_data="grafico_generale")],
        [InlineKeyboardButton("📉 Solo Spese", callback_data="grafico_spese")],
        [InlineKeyboardButton("📈 Solo Entrate", callback_data="grafico_entrate")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Invia il messaggio con la tastiera
    await update.message.reply_text(
        "Scegli il tipo di grafico che vuoi visualizzare:",
        reply_markup=reply_markup
    )
    
# Funzione per generare il grafico a torta
async def grafico_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Rispondi al callback per evitare timeout
    if query.data == "grafico_spese":
        await query.edit_message_text("📉 Generando il grafico delle sole spese per categoria...")
        await grafico_spese(update, context)
    elif query.data == "grafico_entrate":
        await query.edit_message_text("📈 Generando il grafico delle sole entrate per categoria...")
        await grafico_entrate(update, context)
    elif query.data == "grafico_generale":
        await query.edit_message_text("📊 Generando il grafico generale...")
        await grafico_generale(update, context)
 
async def grafico_generale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pool = context.application.bot_data["db_pool"]

    # Recupera le transazioni dal database
    transazioni = await pool.fetch(
        "SELECT descrizione, importo FROM transazioni WHERE user_id = $1",
        user_id
    )

    if not transazioni:
        await update.callback_query.message.reply_text("📊 Nessuna transazione trovata per generare il grafico.")
        return

    # Calcola il totale delle spese e delle entrate (convertendo in float)
    spese = sum(float(t['importo']) for t in transazioni if t['importo'] < 0)
    entrate = sum(float(t['importo']) for t in transazioni if t['importo'] > 0)

    # Dati per il grafico
    labels = ['Spese', 'Entrate']
    valori = [abs(spese), entrate]

    # Genera il grafico a torta
    plt.figure(figsize=(6, 6))
    wedges, texts, autotexts = plt.pie(
        valori,
        labels=labels,
        autopct=lambda pct: format_labels(pct, valori),
        startangle=90,
        colors=['red', 'green']
    )
    plt.title("Andamento delle Finanze")

    # Personalizza lo stile delle etichette
    for text in autotexts:
        text.set_color("white")
        text.set_fontsize(10)

    # Salva il grafico in un buffer
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png')
    buffer.seek(0)
    plt.close()

    # Invia il grafico all'utente
    await update.callback_query.message.reply_photo(photo=buffer, caption="📊 Ecco il grafico delle tue finanze!")

async def grafico_spese(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pool = context.application.bot_data["db_pool"]

    # Recupera le spese dal database, raggruppate per categoria
    spese_per_categoria = await pool.fetch("""
        SELECT c.nome AS categoria, SUM(t.importo) AS totale
        FROM transazioni t
        LEFT JOIN categorie c ON t.categoria_id = c.id
        WHERE t.user_id = $1 AND t.importo < 0
        GROUP BY c.nome
        ORDER BY totale
    """, user_id)

    if not spese_per_categoria:
        await update.callback_query.message.reply_text("📉 Nessuna spesa trovata per generare il grafico.")
        return

    # Prepara i dati per il grafico
    categorie = [s["categoria"] or "Senza Categoria" for s in spese_per_categoria]
    valori = [abs(float(s["totale"])) for s in spese_per_categoria]

    # Genera il grafico a torta
    plt.figure(figsize=(6, 6))
    wedges, texts, autotexts = plt.pie(
        valori,
        labels=categorie,
        autopct=lambda pct: format_labels(pct, valori),
        startangle=90,
        colors=plt.cm.Paired.colors
    )
    plt.title("Spese per Categoria")

    # Personalizza lo stile delle etichette
    for text in autotexts:
        text.set_color("white")
        text.set_fontsize(10)

    # Salva il grafico in un buffer
    buffer = io.BytesIO()
    plt.savefig(buffer, format="png")
    buffer.seek(0)
    plt.close()

    # Invia il grafico all'utente
    await update.callback_query.message.reply_photo(photo=buffer, caption="📉 Ecco il grafico delle tue spese per categoria!")


async def grafico_entrate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pool = context.application.bot_data["db_pool"]

    # Recupera le entrate dal database, raggruppate per categoria
    entrate_per_categoria = await pool.fetch("""
        SELECT c.nome AS categoria, SUM(t.importo) AS totale
        FROM transazioni t
        LEFT JOIN categorie c ON t.categoria_id = c.id
        WHERE t.user_id = $1 AND t.importo > 0
        GROUP BY c.nome
        ORDER BY totale
    """, user_id)

    if not entrate_per_categoria:
        await update.callback_query.message.reply_text("📈 Nessuna entrata trovata per generare il grafico.")
        return

    # Prepara i dati per il grafico
    categorie = [e["categoria"] or "Senza Categoria" for e in entrate_per_categoria]
    valori = [float(e["totale"]) for e in entrate_per_categoria]

    # Genera il grafico a torta
    plt.figure(figsize=(6, 6))
    wedges, texts, autotexts = plt.pie(
        valori,
        labels=categorie,
        autopct=lambda pct: format_labels(pct, valori),
        startangle=90,
        colors=plt.cm.Paired.colors
    )
    plt.title("Entrate per Categoria")

    # Personalizza lo stile delle etichette
    for text in autotexts:
        text.set_color("white")
        text.set_fontsize(10)

    # Salva il grafico in un buffer
    buffer = io.BytesIO()
    plt.savefig(buffer, format="png")
    buffer.seek(0)
    plt.close()

    # Invia il grafico all'utente
    await update.callback_query.message.reply_photo(photo=buffer, caption="📈 Ecco il grafico delle tue entrate per categoria!")

async def aggiungi_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pool = context.application.bot_data["db_pool"]

    # Ottieni il nome della categoria dall'input dell'utente
    if len(context.args) == 0:
        await update.message.reply_text("❌ Per favore, specifica il nome della categoria. Esempio: /aggiungi_categoria Viaggi")
        return

    nome_categoria = " ".join(context.args)

    # Inserisci la categoria nel database
    try:
        await pool.execute(
            "INSERT INTO categorie (user_id, nome) VALUES ($1, $2)",
            user_id, nome_categoria
        )
        await update.message.reply_text(f"✅ Categoria '{nome_categoria}' aggiunta con successo!")
    except asyncpg.UniqueViolationError:
        await update.message.reply_text(f"⚠️ La categoria '{nome_categoria}' esiste già.")

async def lista_categorie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pool = context.application.bot_data["db_pool"]

    # Recupera le categorie dal database
    categorie = await pool.fetch(
        "SELECT nome FROM categorie WHERE user_id = $1 ORDER BY nome",
        user_id
    )

    if not categorie:
        await update.message.reply_text("📂 Non hai ancora creato categorie.")
        return

    elenco = "\n".join([f"• {c['nome']}" for c in categorie])
    await update.message.reply_text(f"📋 *Le tue categorie:*\n\n{elenco}", parse_mode="Markdown")

async def elimina_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pool = context.application.bot_data["db_pool"]

    # Ottieni il nome della categoria dall'input dell'utente
    if len(context.args) == 0:
        await update.message.reply_text("❌ Per favore, specifica il nome della categoria da eliminare. Esempio: /elimina_categoria Viaggi")
        return

    nome_categoria = " ".join(context.args)

    # Elimina la categoria dal database
    result = await pool.execute(
        "DELETE FROM categorie WHERE user_id = $1 AND nome = $2",
        user_id, nome_categoria
    )

    if result == "DELETE 0":
        await update.message.reply_text(f"⚠️ La categoria '{nome_categoria}' non esiste.")
    else:
        await update.message.reply_text(f"✅ Categoria '{nome_categoria}' eliminata con successo!")

async def gestisci_categoria_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pool = context.application.bot_data["db_pool"]
    print(f"sto gestendo le categorie per l'utente {user_id}")
    # Recupera le categorie dal database
    categorie = await pool.fetch(
        "SELECT id, nome FROM categorie WHERE user_id = $1 ORDER BY nome",
        user_id
    )
    if not categorie:
        await update.message.reply_text("📂 Non hai ancora creato categorie. Utilizza il comando aggiungi categoria per crearne!!")
        return ConversationHandler.END

    # Crea una tastiera inline con le categorie
    keyboard = [
        [InlineKeyboardButton(c['nome'], callback_data=f"gestisci_categoria_{c['id']}")]
        for c in categorie
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🛠️ Seleziona una categoria da gestire:",
        reply_markup=reply_markup
    )
    return CATEGORIA


async def aggiungi_categoria_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✏️ Scrivi il nome della categoria che vuoi aggiungere:")
    return NOME_CATEGORIA

async def aggiungi_categoria_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pool = context.application.bot_data["db_pool"]

    nome_categoria = update.message.text.strip()

    # Inserisci la categoria nel database
    try:
        await pool.execute(
            "INSERT INTO categorie (user_id, nome) VALUES ($1, $2)",
            user_id, nome_categoria
        )
        await update.message.reply_text(f"✅ Categoria '{nome_categoria}' aggiunta con successo!")
    except asyncpg.UniqueViolationError:
        await update.message.reply_text(f"⚠️ La categoria '{nome_categoria}' esiste già.")

    return ConversationHandler.END

async def modifica_categoria_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    categoria_id = context.user_data.get('categoria_id')
    nuovo_nome = update.message.text.strip()

    if not categoria_id:
        await update.message.reply_text("⚠️ Errore: Nessuna categoria selezionata per la modifica.")
        return ConversationHandler.END

    pool = context.application.bot_data["db_pool"]
    try:
        # Aggiorna il nome della categoria nel database
        await pool.execute(
            "UPDATE categorie SET nome = $1 WHERE id = $2 AND user_id = $3",
            nuovo_nome, categoria_id, user_id
        )
        await update.message.reply_text(f"✅ Categoria aggiornata con successo, nuovo nome: {nuovo_nome}")
    except asyncpg.UniqueViolationError:
        await update.message.reply_text(f"⚠️ La categoria ccon nome : '{nuovo_nome}' esiste già, sceglie un altro nome.")

    # Resetta il contesto per evitare conflitti
    context.user_data.clear()
    # Esci automaticamente dalla conversazione
    return ConversationHandler.END

#Funzione per aggiungere i metodi di pagamento 
NOME_CARTA = range(1)
async def aggiungi_carta_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✏️ Scrivi il nome della carta che vuoi aggiungere:")
    return NOME_CARTA

# Funzione per aggiungere il nome della carta (vera e propria)
async def aggiungi_carta_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pool = context.application.bot_data["db_pool"]

    nome_carta = update.message.text.strip()
    if nome_carta == "":
        await update.message.reply_text("⚠️ Nome della carta non valido. Riprova.")
        return ConversationHandler.END
    # Inserisci la carta nel database
    try:
        await pool.execute(
            "INSERT INTO carte (user_id, nome) VALUES ($1, $2)",
            user_id, nome_carta
        )
        await update.message.reply_text(f"✅ Carta '{nome_carta}' aggiunta con successo!")
    except asyncpg.UniqueViolationError:
        await update.message.reply_text(f"⚠️ La carta '{nome_carta}' esiste già.")

    return ConversationHandler.END

# Funzione per visualizzare le carte
async def lista_carte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pool = context.application.bot_data["db_pool"]

    # Recupera le carte dal database
    carte = await pool.fetch(
        "SELECT nome FROM carte WHERE user_id = $1 ORDER BY nome",
        user_id
    )

    if not carte:
        await update.message.reply_text("📂 Non hai ancora aggiunto metodi di pagamento.")
        return

    elenco = "\n".join([f"• {c['nome']}" for c in carte])
    await update.message.reply_text(f"💳 *I tuoi metodi di pagamento:*\n\n{elenco}", parse_mode="Markdown")

# Main
async def main():
    db_pool = await connect_db()
    await crea_tabella(db_pool)

    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

    if not TOKEN:
        raise ValueError("Assicurati di aver impostato TELEGRAM_BOT_TOKEN nelle variabili d'ambiente")

    app = ApplicationBuilder().token(TOKEN).build()
    app.bot_data["db_pool"] = db_pool

    await set_bot_commands(app)

    # Aggiungi i gestori
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("riepilogo", riepilogo))
    app.add_handler(CommandHandler("gestisci", gestisci))
    app.add_handler(CommandHandler("esporta", esporta))
    app.add_handler(CommandHandler("grafico", grafico))
    app.add_handler(CommandHandler("gestisci_categoria", gestisci_categoria_start))
    app.add_handler(CommandHandler("categorie", lista_categorie))
    app.add_handler(CommandHandler("carte", lista_carte))
    app.add_handler(CallbackQueryHandler(grafico_callback, pattern="grafico_"))

    app.add_handler(ConversationHandler(
    entry_points=[CommandHandler("spesa", spesa_start)],
    states={
        DESCRIZIONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, descrizione)],
        IMPORTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, importo)],
        CATEGORIA: [CallbackQueryHandler(seleziona_categoria, pattern="categoria_")],
        CARTA: [CallbackQueryHandler(seleziona_carta, pattern="carta_")]
    },
    fallbacks=[CommandHandler("annulla", annulla)],
    ))

    app.add_handler(CallbackQueryHandler(riepilogo_callback, pattern="^riepilogo_"))

    app.add_handler(ConversationHandler(
    entry_points=[CommandHandler("entrata", entrata_start)],
    states={
        DESCRIZIONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, descrizione)],
        IMPORTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, importo)],
        CATEGORIA: [CallbackQueryHandler(seleziona_categoria, pattern="categoria_")],
        CARTA: [CallbackQueryHandler(seleziona_carta, pattern="carta_")]
    },
    fallbacks=[CommandHandler("annulla", annulla)],
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("aggiungi_carta", aggiungi_carta_start)],
        states={
            NOME_CARTA: [MessageHandler(filters.TEXT & ~filters.COMMAND, aggiungi_carta_nome)],
        },
        fallbacks=[CommandHandler("annulla", annulla)],
    ))
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("aggiungi_categoria", aggiungi_categoria_start)],
        states={
            NOME_CATEGORIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, aggiungi_categoria_nome)],
        },
        fallbacks=[CommandHandler("annulla", annulla)],
    ))

    app.add_handler(ConversationHandler(
    entry_points=[CallbackQueryHandler(gestisci_callback)],
    states={
        IMPORTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, aggiorna_transazione)],
        NOME_CATEGORIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, modifica_categoria_nome)],
    },
    fallbacks=[CommandHandler("annulla", annulla)],
    per_message=False,
    ))

    # Avvia il bot con polling
    print("🚀 Avvio del bot in modalità polling...")
    await app.run_polling()

# Server HTTP dummy per Render
async def handle_ping(request):
    return web.Response(text="pong")

async def start_dummy_server():
    PORT = int(os.environ.get("PORT", 8080))  # Porta fornita da Render
    app = web.Application()
    app.router.add_get("/ping", handle_ping)  # Endpoint di test
    app.router.add_get("/metrics", handle_metrics)  # Endpoint per le metriche
    app["db_pool"] = await connect_db()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🌐 Server HTTP dummy avviato su porta {PORT}")

if __name__ == "__main__":
    asyncio.run(start_dummy_server())  # Avvia il server HTTP dummy in parallelo
    asyncio.run(main())  # Avvia il bot in modalità polling