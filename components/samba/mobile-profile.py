"""Generate CIFS Documents Provider 2.4.0's credential-free import format.

Matches upstream ConnectionIO, EncryptUtils, DomainMapper and StorageConnection.
The public import password is a format requirement, not a security boundary.
"""
import base64
import json
import sys
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def encrypt(value, password, length):
    data = json.dumps(value, separators=(",", ":")).encode()
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    cipher = Cipher(algorithms.AES(password.ljust(length, "0").encode()), modes.CBC(bytes(16)))
    encryptor = cipher.encryptor()
    return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode()


def profile(host):
    result = []
    for order, share in enumerate(("Downloads", "Remote")):
        identity = "homelab-" + share.lower()
        name = "Homelab " + share
        connection = dict(
            type="com.wa2c.android.cifsdocumentsprovider.data.storage.interfaces.StorageConnection.Cifs",
            id=identity, name=name, storage="SMBJ", host=host, port="445",
            folder=share, user="rishabh", password="", anonymous=False,
            safeTransfer=False, readOnly=(share == "Downloads"), extension=False,
            thumbnailTypes=[], domain="WORKGROUP", enableDfs=False,
            enableEncryption=True,
        )
        result.append(dict(id=identity, name=name, type="SMBJ",
                           uri=f"smb://{host}:445/{share}/",
                           data=encrypt(connection, "com.wa2c.android", 16),
                           sortOrder=order, modifiedDate=0))
    return encrypt(result, "homelab", 32)


if __name__ == "__main__":
    print(profile(sys.argv[1]))
