import hashlib
import secrets
import hmac
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from sqlalchemy import select
from fastapi import Request
from .db import User, Session, Tenant, now_ms
from .core import DomainError

passwords=PasswordHasher(time_cost=3,memory_cost=65536,parallelism=2)

def new_user(s,tenant,email,password,role='admin'):
    if not 12<=len(password)<=256:
        raise DomainError('Password must contain 12..256 characters')
    email=email.strip().lower()
    if len(email)>254 or '@' not in email:
        raise DomainError('Enter an email address')
    if s.scalar(select(User).where(User.email==email)):
        raise DomainError('Email already registered',409)
    u=User(id=secrets.token_hex(16),tenant_id=tenant,email=email,password_hash=passwords.hash(password),role=role)
    s.add(u)
    return u

def bootstrap(db,settings):
    if not settings.bootstrap_email or not settings.bootstrap_password: return
    with db.lock,db.session.begin() as s:
        if s.scalar(select(User).limit(1)): return
        tenant=Tenant(id=secrets.token_hex(16),name='My OmniLink workspace')
        s.add(tenant)
        new_user(s,tenant.id,settings.bootstrap_email,settings.bootstrap_password)

def login(db,email,password):
    if len(password)>256: raise DomainError('Invalid email or password',401)
    with db.lock,db.session.begin() as s:
        u=s.scalar(select(User).where(User.email==email.strip().lower(),User.enabled==True))
        try:
            valid=u is not None and passwords.verify(u.password_hash,password)
        except (VerificationError,InvalidHashError): valid=False
        if not valid: raise DomainError('Invalid email or password',401)
        from .platform_models import Account
        account=s.get(Account,u.tenant_id)
        if account and not account.enabled:raise DomainError('Account disabled',403)
        token=secrets.token_urlsafe(32)
        session=Session(token_hash=hashlib.sha256(token.encode()).hexdigest(),user_id=u.id,
                        csrf=secrets.token_urlsafe(32),expires_ms=now_ms()+12*3600_000)
        s.add(session)
        return u,token,session.csrf

def resolve(db,token):
    if not token or len(token)>128: raise DomainError('Sign in required',401)
    with db.session() as s:
        session=s.get(Session,hashlib.sha256(token.encode()).hexdigest())
        if not session or session.expires_ms<=now_ms(): raise DomainError('Session expired',401)
        u=s.get(User,session.user_id)
        if not u or not u.enabled: raise DomainError('Sign in required',401)
        from .platform_models import Account
        account=s.get(Account,u.tenant_id)
        if account and not account.enabled:raise DomainError('Account disabled',403)
        return u,session

def user(request:Request):
    runtime=request.app.state.runtime
    header=request.headers.get('authorization','')
    bearer=header.startswith('Bearer ')
    token=header[7:] if bearer else request.cookies.get('omnilink_session')
    u,session=resolve(runtime.db,token)
    if request.method not in ('GET','HEAD','OPTIONS'):
        if u.role=='viewer' and request.url.path!='/api/auth/logout': raise DomainError('Viewer access is read-only',403)
        if not bearer:
            origin=request.headers.get('origin')
            if origin and origin.rstrip('/')!=runtime.settings.public_url.rstrip('/'):
                raise DomainError('Origin rejected',403)
            if not hmac.compare_digest(request.headers.get('x-csrf-token',''),session.csrf):
                raise DomainError('CSRF token required',403)
    request.state.session=session
    request.state.user=u
    return u

def admin(request:Request):
    u=user(request)
    if u.role!='admin': raise DomainError('Administrator access required',403)
    return u

def device_user(request:Request,device_id):
    header=request.headers.get('authorization','')
    if not header.startswith('Device '): raise DomainError('Device credentials required',401)
    return request.app.state.runtime.core.authenticate_device(device_id,header[7:])
