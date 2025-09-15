from base64 import b64decode

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key


def verify_signature(
        pem_public_key: str,
        signature_b64: str,
        message_id: str,
        timestamp: str,
        body: bytes,
) -> bool:
        if not signature_b64:
                return False

        pubkey = load_pem_public_key(
                pem_public_key.encode()
                if isinstance(pem_public_key, str)
                else pem_public_key
        )

        signature = b64decode(signature_b64)
        message = message_id.encode() + b"." + timestamp.encode() + b"." + body

        try:
                pubkey.verify(  # type: ignore
                        signature,
                        message,
                        padding.PKCS1v15(),  # type: ignore
                        hashes.SHA256(),  # type: ignore
                )
                return True
        except Exception:  # noqa: BLE001
                return False
