"""Offline packaged-runtime check, before UI imports or access to user data."""


def check():
    import bz2
    import ctypes
    import hashlib
    import io
    import json
    import lzma
    import sqlite3
    import ssl
    import sys
    import zlib
    from PIL import Image
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import psutil

    sample = b"Cubeon portable runtime check"
    for compress, decompress in ((zlib.compress, zlib.decompress),
                                 (bz2.compress, bz2.decompress),
                                 (lzma.compress, lzma.decompress)):
        if decompress(compress(sample)) != sample:
            raise RuntimeError("Compression runtime check failed")
    buffer = io.BytesIO()
    Image.new("RGBA", (4, 4), (12, 34, 56, 255)).save(buffer, format="PNG")
    buffer.seek(0)
    with Image.open(buffer) as picture:
        if picture.getpixel((0, 0)) != (12, 34, 56, 255):
            raise RuntimeError("Image runtime check failed")
    cipher = AESGCM(bytes(range(32)))
    nonce = bytes(range(12))
    if cipher.decrypt(nonce, cipher.encrypt(nonce, sample, None), None) != sample:
        raise RuntimeError("Encryption runtime check failed")
    with sqlite3.connect(":memory:") as database:
        if database.execute("select 1").fetchone() != (1,):
            raise RuntimeError("SQLite runtime check failed")
    ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctypes.create_string_buffer(sample)
    psutil.Process().memory_info()
    print(json.dumps({"status": "ok", "python": sys.version.split()[0],
                      "frozen": bool(getattr(sys, "frozen", False)),
                      "sha256": hashlib.sha256(sample).hexdigest()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(check())
