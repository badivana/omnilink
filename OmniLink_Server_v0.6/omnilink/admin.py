"""Host-side administration; no global cross-tenant account exists in the API."""
import argparse
import getpass
import secrets
from sqlalchemy import select
from .settings import Settings
from .db import Database,User,Tenant
from .auth import new_user,passwords

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['create-tenant','reset-password']);p.add_argument('--email',required=True);p.add_argument('--name',default='OmniLink workspace')
    a=p.parse_args();db=Database(Settings.from_env().database_url)
    password=getpass.getpass('New password (12..256 characters): ')
    if not 12<=len(password)<=256: raise SystemExit('Invalid password length')
    with db.lock,db.session.begin() as s:
        if a.action=='create-tenant':
            tenant=Tenant(id=secrets.token_hex(16),name=a.name);s.add(tenant);new_user(s,tenant.id,a.email,password)
        else:
            u=s.scalar(select(User).where(User.email==a.email.strip().lower()))
            if not u: raise SystemExit('User not found')
            u.password_hash=passwords.hash(password)
            from .db import Session
            from sqlalchemy import delete
            s.execute(delete(Session).where(Session.user_id==u.id))
    print('Account updated.')

if __name__=='__main__': main()
