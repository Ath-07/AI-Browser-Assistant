import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "profiles.db"


async def get_db():
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


async def init_db():
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT DEFAULT '',
                address TEXT DEFAULT '',
                resume_text TEXT DEFAULT ''
            )
        """)
        await db.commit()


async def get_profile(db: aiosqlite.Connection):
    cursor = await db.execute("SELECT * FROM user_profiles WHERE id = 1")
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


async def upsert_profile(db: aiosqlite.Connection, data: dict):
    await db.execute("""
        INSERT INTO user_profiles (id, name, email, phone, address, resume_text)
        VALUES (1, :name, :email, :phone, :address, :resume_text)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            email = excluded.email,
            phone = excluded.phone,
            address = excluded.address,
            resume_text = excluded.resume_text
    """, data)
    await db.commit()
