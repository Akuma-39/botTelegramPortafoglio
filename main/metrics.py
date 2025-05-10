import datetime
from aiohttp import web

# Tempo di attivita del server
SERVER_UPTIME = datetime.datetime.now()

# Funzione per calcolare le metriche
async def calcola_metriche(pool):
    # Numero di transazioni di oggi (entrate e uscite)
    transazioni_oggi = await pool.fetch("""
        SELECT 
            CASE WHEN importo < 0 THEN 'uscite' ELSE 'entrate' END AS tipo,
            COUNT(*) AS conteggio
        FROM transazioni
        WHERE DATE(data) = CURRENT_DATE
        GROUP BY tipo
    """)
    #Utenti attivi oggi
    utenti_attivi_oggi = await pool.fetchval("""
        SELECT COUNT(DISTINCT user_id) 
        FROM transazioni 
        WHERE DATE(data) = CURRENT_DATE
    """)
    # Percentuale di crescita degli utenti 
    crescita_utenti = await pool.fetchval("""
        WITH utenti_corrente AS (
    SELECT COUNT(DISTINCT user_id) AS totale
    FROM transazioni
    WHERE DATE_PART('month', data) = DATE_PART('month', CURRENT_DATE)
    ),
    utenti_precedente AS (
        SELECT COUNT(DISTINCT user_id) AS totale
        FROM transazioni
        WHERE DATE_PART('month', data) = DATE_PART('month', CURRENT_DATE) - 1
    )
    SELECT 
        (utenti_corrente.totale - utenti_precedente.totale) * 100.0 / NULLIF(utenti_precedente.totale, 0) AS crescita_percentuale
    FROM utenti_corrente, utenti_precedente
                                          """)

    # Transazioni per minuto negli ultimi 2 giorni
    transazioni_per_minuto = await pool.fetch("""
        SELECT 
            DATE_TRUNC('minute', data) AS minuto,
            CASE WHEN importo < 0 THEN 'uscite' ELSE 'entrate' END AS tipo,
            COUNT(*) AS conteggio
        FROM transazioni
        WHERE data >= CURRENT_DATE - INTERVAL '2 days'
        GROUP BY minuto, tipo
        ORDER BY minuto
    """)

   # Prepara i dati per il JSON con totali cumulativi
    transazioni_minuto = []
    totale_entrate = 0
    totale_uscite = 0

    for t in transazioni_per_minuto:
        minuto = t["minuto"].isoformat()
        tipo = t["tipo"]
        conteggio = t["conteggio"]

        # Aggiorna i totali cumulativi
        if tipo == "entrate":
            totale_entrate += conteggio
        elif tipo == "uscite":
            totale_uscite += conteggio

        # Cerca se il minuto esiste già nella lista
        existing_entry = next((entry for entry in transazioni_minuto if entry["timestamp"] == minuto), None)
        if existing_entry:
            existing_entry["entrate"] = totale_entrate
            existing_entry["uscite"] = totale_uscite
        else:
            transazioni_minuto.append({
                "timestamp": minuto,
                "entrate": totale_entrate,
                "uscite": totale_uscite
            })

    # Numero totale di utenti
    utenti_totali = await pool.fetchval("SELECT COUNT(DISTINCT user_id) FROM transazioni")

    # Data e ora attuale
    ora_attuale = datetime.datetime.now().isoformat()

    # Prepara il JSON delle metriche
    metriche = {
        "timestamp": ora_attuale,
        "uptime": str(datetime.datetime.now() - SERVER_UPTIME),
        "transazioni_oggi": {t["tipo"]: t["conteggio"] for t in transazioni_oggi},
        "utenti_attivi_oggi": utenti_attivi_oggi,
        "transazioni_per_minuto": transazioni_minuto,
        "utenti_totali": utenti_totali,
        "crescita_utenti(%)": crescita_utenti,
    }

    return metriche

# Endpoint per le metriche
async def handle_metrics(request):
    pool = request.app["db_pool"]
    metriche = await calcola_metriche(pool)
    return web.json_response(metriche)