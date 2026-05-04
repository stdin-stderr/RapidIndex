import asyncio

from src.storage.db import run_migrations

if __name__ == "__main__":
    asyncio.run(run_migrations())
    print("Migrations complete.")
