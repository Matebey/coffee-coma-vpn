from .db import db
from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, Numeric, ForeignKey
from sqlalchemy.sql import func

class User(db.Model):
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

class VPNConfig(db.Model):
    __tablename__ = 'vpn_configs'
    
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.id'))
    config_data = Column(String(1000))
    created_at = Column(DateTime, server_default=func.now())
    expires_at = Column(DateTime)
    is_active = Column(Boolean, default=True)
    
    def __str__(self):
        return f"VPN Config for user {self.user_id}"

class Payment(db.Model):
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

class Referral(db.Model):
    __tablename__ = 'referrals'
    
    id = Column(BigInteger, primary_key=True)
    referrer_id = Column(BigInteger, ForeignKey('users.id'))
    referred_id = Column(BigInteger, ForeignKey('users.id'))
    created_at = Column(DateTime, server_default=func.now())
    earned = Column(Numeric(10, 2), default=0)
    
    def __str__(self):
        return f"Referral {self.referrer_id} -> {self.referred_id}"
