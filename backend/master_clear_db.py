import asyncio
import asyncpg
import sys

# Configure your DB URL here if it changes
DB_URL = "postgresql://devbrain_user:devbrain_pass@localhost:5432/devbrain_db"

async def master_clear_db():
    print(f"Connecting to {DB_URL}...")
    try:
        conn = await asyncpg.connect(DB_URL)
        
        # Get all tables in the public schema
        tables = await conn.fetch('''
            SELECT tablename 
            FROM pg_catalog.pg_tables 
            WHERE schemaname = 'public'
        ''')
        
        if not tables:
            print("No tables found in public schema.")
            return

        table_names = [t['tablename'] for t in tables]
        # Ignore alembic_version to keep migration history intact
        if 'alembic_version' in table_names:
            table_names.remove('alembic_version')
            
        if not table_names:
            print("No user tables to drop.")
            return

        print(f"Found {len(table_names)} tables to clear: {', '.join(table_names)}")
        
        for table in table_names:
            print(f"Truncating {table}...")
            # Truncate with cascade to handle foreign keys
            await conn.execute(f"TRUNCATE TABLE {table} CASCADE")
        
        print("Database fully cleared successfully!")
        await conn.close()
    except Exception as e:
        print(f"Error clearing database: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(master_clear_db())
