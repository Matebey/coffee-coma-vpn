from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, Numeric, ForeignKey
from sqlalchemy.sql import func
from bot.utils.config import Config

Base = declarative_base()

# Database engine and session factory
engine = None
async_session = None

async def init_db():
    global engine, async_session
    engine = create_async_engine(Config.DB_URL, echo=True)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def close_db():
    if engine:
        await engine.dispose()

# Database models
class User(Base):
    __tablename__ = 'users'
    
    id = Column(BigInteger, primary_key=True)
    username = Column(String(100))
    first_name = Column(String(100))
    last_name = Column(String(100))
    join_date = Column(DateTime, server_default=func.now())
    is_admin = Column(Boolean, default=False)
    balance = Column(Numeric(10, 2), default=0)
    
    def __str__(self):
        return f"User {self.id} ({self.username})"

class VPNConfig(Base):
    __tablename__ = 'vpn_configs'
    
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.id'))
    config_data = Column(String(1000))
    created_at = Column(DateTime, server_default=func.now())
    expires_at = Column(DateTime)
    is_active = Column(Boolean, default=True)
    
    def __str__(self):
        return f"VPN Config for user {self.user_id}"

class Payment(Base):
    __tablename__ = 'payments'
    
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.id'))
    amount = Column(Numeric(10, 2))
    currency = Column(String(3), default='RUB')
    status = Column(String(20), default='pending')
    payment_id = Column(String(100))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    def __str__(self):
        return f"Payment {self.id} - {self.amount} {self.currency}"

class Referral(Base):
    __tablename__ = 'referrals'
    
    id = Column(BigInteger, primary_key=True)
    referrer_id = Column(BigInteger, ForeignKey('users.id'))
    referred_id = Column(BigInteger, ForeignKey('users.id'))
    created_at = Column(DateTime, server_default=func.now())
    earned = Column(Numeric(10, 2), default=0)
    
    def __str__(self):
        return f"Referral {self.referrer_id} -> {self.referred_id}"

# Database helper functions
async def get_user(user_id: int) -> User:
    async with async_session() as session:
        result = await session.get(User, user_id)
        return result

async def create_user(user_data: dict) -> User:
    async with async_session() as session:
        user = User(**user_data)
        session.add(user)
        await session.commit()
        return user

async def get_vpn_config(user_id: int) -> VPNConfig:
    async with async_session() as session:
        from sqlalchemy import select
        stmt = select(VPNConfig).where(
            (VPNConfig.user_id == user_id) & 
            (VPNConfig.is_active == True)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
