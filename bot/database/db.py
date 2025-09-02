from gino import Gino
from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, Numeric
from sqlalchemy.sql import func
from bot.utils.config import Config

db = Gino()

async def init_db():
    await db.set_bind(Config.DB_URL)
    await db.gino.create_all()

async def close_db():
    await db.pop_bind().close()
