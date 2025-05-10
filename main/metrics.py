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
        "utenti_totali": utenti_totali,
        "crescita_utenti(%)": crescita_utenti,
    }

    return metriche

# Endpoint per le metriche
async def handle_metrics(request):
    pool = request.app["db_pool"]
    metriche = await calcola_metriche(pool)
    return web.json_response(metriche)