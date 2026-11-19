"""Private CA for native ONP and MQTT. Caddy handles public HTTPS separately."""
import argparse
import ipaddress
import os
from datetime import datetime,timedelta,timezone
from pathlib import Path
from cryptography import x509
from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa

def save(path,data,mode=0o600):
    path.write_bytes(data)
    try: path.chmod(mode)
    except OSError: pass

def generate(folder,hosts):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    now=datetime.now(timezone.utc)
    if (folder/'ca.key').exists() and (folder/'ca.crt').exists():
        key=serialization.load_pem_private_key((folder/'ca.key').read_bytes(),password=None)
        ca=x509.load_pem_x509_certificate((folder/'ca.crt').read_bytes())
        has_ski=any(isinstance(ext.value,x509.SubjectKeyIdentifier) for ext in ca.extensions)
        if not has_ski:
            ca_ski=x509.SubjectKeyIdentifier.from_public_key(key.public_key())
            ca=(x509.CertificateBuilder().subject_name(ca.subject).issuer_name(ca.issuer)
                .public_key(key.public_key()).serial_number(ca.serial_number)
                .not_valid_before(ca.not_valid_before_utc if hasattr(ca,'not_valid_before_utc') else ca.not_valid_before.replace(tzinfo=timezone.utc))
                .not_valid_after(ca.not_valid_after_utc if hasattr(ca,'not_valid_after_utc') else ca.not_valid_after.replace(tzinfo=timezone.utc))
                .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
                .add_extension(x509.KeyUsage(digital_signature=True,key_encipherment=False,key_cert_sign=True,crl_sign=True,
                    content_commitment=False,data_encipherment=False,key_agreement=False,encipher_only=False,decipher_only=False),critical=True)
                .add_extension(ca_ski,critical=False).sign(key,hashes.SHA256()))
            save(folder/'ca.crt',ca.public_bytes(serialization.Encoding.PEM),0o644)
    else:
        key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'OmniLink private device CA')])
        ca_ski=x509.SubjectKeyIdentifier.from_public_key(key.public_key())
        ca=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5))
            .not_valid_after(now+timedelta(days=3650)).add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True,key_encipherment=False,key_cert_sign=True,crl_sign=True,
                content_commitment=False,data_encipherment=False,key_agreement=False,encipher_only=False,decipher_only=False),critical=True)
            .add_extension(ca_ski,critical=False).sign(key,hashes.SHA256()))
        save(folder/'ca.key',key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        save(folder/'ca.crt',ca.public_bytes(serialization.Encoding.PEM),0o644)
    leaf_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    alternatives=[]
    for host in dict.fromkeys(hosts):
        try: alternatives.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError: alternatives.append(x509.DNSName(host))
    leaf_ski=x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key())
    leaf_aki=x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key())
    leaf=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,hosts[0])]))
          .issuer_name(ca.subject).public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=365))
          .add_extension(x509.SubjectAlternativeName(alternatives),critical=False)
          .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
          .add_extension(leaf_ski,critical=False)
          .add_extension(leaf_aki,critical=False)
          .add_extension(x509.KeyUsage(digital_signature=True,key_encipherment=True,key_cert_sign=False,crl_sign=False,
              content_commitment=False,data_encipherment=False,key_agreement=False,encipher_only=False,decipher_only=False),critical=True)
          .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False).sign(key,hashes.SHA256()))
    save(folder/'server.key',leaf_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    save(folder/'server.crt',leaf.public_bytes(serialization.Encoding.PEM),0o644)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--host',action='append',required=True);parser.add_argument('--folder',default='data/certs')
    args=parser.parse_args();generate(args.folder,args.host+['localhost','127.0.0.1','mosquitto']);print('Device TLS certificate renewed; CA preserved.')
