"""Create an RSA key pair for a Snowflake service user and print the RSA_PUBLIC_KEY value.
Usage (project folder):  python scripts/make_key.py portal_key
Writes snowflake/secrets/<name>.p8 (private, never commit) and <name>.pub; reuses an existing key."""
import base64, hashlib, pathlib, sys
from cryptography.hazmat.primitives import serialization as s
from cryptography.hazmat.primitives.asymmetric import rsa

name = sys.argv[1] if len(sys.argv) > 1 else "portal_key"
folder = pathlib.Path(__file__).resolve().parent.parent / "snowflake" / "secrets"
folder.mkdir(parents=True, exist_ok=True)
priv_file, pub_file = folder / f"{name}.p8", folder / f"{name}.pub"

if priv_file.exists():
    key = s.load_pem_private_key(priv_file.read_bytes(), password=None)
    print(f"Reusing existing private key {priv_file}")
else:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_file.write_bytes(key.private_bytes(s.Encoding.PEM, s.PrivateFormat.PKCS8, s.NoEncryption()))
    print(f"Created private key {priv_file}  (keep secret, never commit)")

pub_pem = key.public_key().public_bytes(s.Encoding.PEM, s.PublicFormat.SubjectPublicKeyInfo)
pub_file.write_bytes(pub_pem)
der = key.public_key().public_bytes(s.Encoding.DER, s.PublicFormat.SubjectPublicKeyInfo)
print("\nRSA_PUBLIC_KEY (paste into Snowflake):\n")
print("".join(l for l in pub_pem.decode().splitlines() if "KEY" not in l))
print("\nFingerprint (must match RSA_PUBLIC_KEY_FP in DESC USER):")
print("SHA256:" + base64.b64encode(hashlib.sha256(der).digest()).decode())
