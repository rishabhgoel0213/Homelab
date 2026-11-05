"""Pure policy shared by the privileged gate and its tests."""
import hashlib
import hmac
import math


def fresh_unbricked(observation):
    if not isinstance(observation, dict):
        return False
    age = observation.get('ageSeconds')
    return (observation.get('schema') == 1
            and observation.get('state') == 'unbricked'
            and observation.get('latchedBricked') is False
            and type(age) in (int, float) and math.isfinite(age)
            and 0 <= age <= 3)


def verifier(secret):
    if len(secret) not in (8, 32):
        raise ValueError('Recovery secrets must contain 64 bits (or legacy 256 bits)')
    return hashlib.sha256(b'homelab-brick-admin-v1\0' + secret).hexdigest()


def accepts(secret_hex, stored_verifier):
    try:
        if len(secret_hex) not in (16, 64):
            return False
        value = bytes.fromhex(secret_hex)
        return hmac.compare_digest(verifier(value), stored_verifier)
    except (ValueError, TypeError):
        return False


def may_rotate(observation):
    # Recovery authorization never substitutes for an unbricked observation.
    return fresh_unbricked(observation)
