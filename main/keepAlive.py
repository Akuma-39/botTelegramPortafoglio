import asyncio
import asyncpg
import os

async def keep_alive():
    try:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise ValueError("DATABASE_URL environment variable not set.")
        
        conn = await asyncpg.connect(db_url)
        await conn.execute("SELECT 1")  # Query semplice per tenere viva la connessione
        await conn.close()
        print("Keep-alive eseguito con successo.")
    except Exception as e:
        print(f"Errore nel keep-alive: {e}")

if __name__ == "__main__":
    asyncio.run(keep_alive())
