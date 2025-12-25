"""
Cryptographic utilities for secure API key storage.
Uses AES-256-GCM for encryption with a master key.
"""
import os
import base64
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def get_master_key() -> bytes:
    """Get or generate the master encryption key from environment."""
    key_hex = os.getenv('ENCRYPTION_MASTER_KEY')
    if not key_hex:
        # Generate a new key if not set (should be set in production!)
        import secrets
        key_hex = secrets.token_hex(32)
        print(f"⚠️ WARNING: No ENCRYPTION_MASTER_KEY set. Generated temporary key.")
        print(f"   Set this in .env for persistence: ENCRYPTION_MASTER_KEY={key_hex}")
    return bytes.fromhex(key_hex)


def encrypt_api_key(plaintext: str, master_key: bytes = None) -> str:
    """
    Encrypt an API key using AES-256-GCM.
    Returns base64-encoded ciphertext with nonce prepended.
    """
    if master_key is None:
        master_key = get_master_key()
    
    # Generate random 12-byte nonce
    nonce = os.urandom(12)
    
    # Encrypt
    aesgcm = AESGCM(master_key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
    
    # Combine nonce + ciphertext and base64 encode
    encrypted = base64.b64encode(nonce + ciphertext).decode('utf-8')
    return encrypted


def decrypt_api_key(encrypted: str, master_key: bytes = None) -> str:
    """
    Decrypt an API key encrypted with encrypt_api_key.
    """
    if master_key is None:
        master_key = get_master_key()
    
    # Decode base64
    data = base64.b64decode(encrypted.encode('utf-8'))
    
    # Split nonce and ciphertext
    nonce = data[:12]
    ciphertext = data[12:]
    
    # Decrypt
    aesgcm = AESGCM(master_key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode('utf-8')


def hash_telegram_id(telegram_id: int) -> str:
    """Create a hash of telegram_id for anonymous lookups."""
    return hashlib.sha256(str(telegram_id).encode()).hexdigest()[:16]
