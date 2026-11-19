import argparse
import getpass
import os
import secrets
from pathlib import Path
from cryptography.fernet import Fernet
from .certificates import generate,save

def main():
    parser=argparse.ArgumentParser(description='Initialize a local, native VPS, or Docker OmniLink installation.')
    parser.add_argument('--docker',action='store_true')
    parser.add_argument('--domain',help='Public DNS name; point it at your VPS before deployment')
    parser.add_argument('--email')
    parser.add_argument('--host',action='append',default=[],help='Additional device TLS certificate DNS name or IP')
    args=parser.parse_args()
    if Path('.env').exists(): raise SystemExit('.env already exists. Existing secrets preserved; use run.bat/run.sh or docker compose up -d.')
    email=args.email or input('Administrator email: ').strip()
    password=os.getenv('OMNILINK_SETUP_PASSWORD') or getpass.getpass('Administrator password (at least 12 characters): ')
    if '@' not in email or not 12<=len(password)<=256: raise SystemExit('Enter an email and a password of 12..256 characters.')
    if args.domain and any(c in args.domain for c in '/ :\n'):
        raise SystemExit('--domain must be a DNS hostname without a URL scheme.')
    domain=args.domain or 'localhost'
    generate('data/certs',[domain,'localhost','127.0.0.1','mosquitto']+args.host)
    Path('data').mkdir(exist_ok=True)
    values={
        'OMNILINK_ENCRYPTION_KEY':Fernet.generate_key().decode(),
        'OMNILINK_BOOTSTRAP_EMAIL':email,
        'OMNILINK_BOOTSTRAP_PASSWORD':password,
        'OMNILINK_DATABASE_URL':'sqlite:///./data/omnilink.db',
        'OMNILINK_PUBLIC_URL':(('https://'+domain) if args.domain and args.docker else
                               ('https://'+domain+':8000') if args.domain else
                               'http://localhost'+('' if args.docker else ':8000')),
        'OMNILINK_SECURE_COOKIE':'true' if args.domain else 'false',
        'OMNILINK_HTTP_HOST':'0.0.0.0' if args.domain and not args.docker else '127.0.0.1',
        'OMNILINK_HTTP_PORT':'8000',
        'OMNILINK_HTTP_TLS':'true' if args.domain and not args.docker else 'false',
        'OMNILINK_NATIVE_HOST':'0.0.0.0' if args.docker or args.domain else '127.0.0.1',
        'OMNILINK_MQTT_ENABLED':'true' if args.docker else 'false',
        'OMNILINK_MQTT_HOST':'mosquitto' if args.docker else '127.0.0.1',
        'OMNILINK_MQTT_PORT':'1883' if args.docker else '1884',
        'OMNILINK_MQTT_PASSWORD':secrets.token_hex(32),
        'OMNILINK_MQTT_ADMIN_PASSWORD':secrets.token_hex(32),
        'POSTGRES_PASSWORD':secrets.token_hex(32),
        'OMNILINK_SITE_ADDRESS':domain if args.domain else 'http://localhost',
    }
    # Compose interpolation uses raw env values; reject characters with special meaning.
    if any(c in password for c in '\r\n$#\'"\\') or password!=password.strip():
        raise SystemExit('For this setup file, use a password without quotes, $, #, backslashes, or surrounding spaces.')
    save(Path('.env'),('\n'.join(k+'='+v for k,v in values.items())+'\n').encode())
    print('OmniLink initialized. '+('Run: docker compose up -d --build' if args.docker else 'Run: run.bat (Windows) or sh run.sh (Linux)'))

if __name__=='__main__': main()
