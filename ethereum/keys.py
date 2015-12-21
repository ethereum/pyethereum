import os
import pbkdf2
import sys

try:
    scrypt = __import__('scrypt')
except ImportError:
    sys.stderr.write("""
Failed to import scrypt. This is not a fatal error but does
mean that you cannot create or decrypt privkey jsons that use
scrypt

""")
    scrypt = None
try:
    import bitcoin
except ImportError:
    sys.stderr.write("""
Failed to import bitcoin. This is not a fatal error but does
mean that you will not be able to determine the address from
your wallet file.
""")
import binascii
import struct
from math import ceil
from Crypto.Hash import keccak
sha3_256 = lambda x: keccak.new(digest_bits=256, data=x)
from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.Util import Counter

# TODO: make it compatible!


SCRYPT_CONSTANTS = {
    "n": 262144,
    "r": 1,
    "p": 8,
    "dklen": 32
}

PBKDF2_CONSTANTS = {
    "prf": "hmac-sha256",
    "dklen": 32,
    "c": 262144
}


def aes_ctr_encrypt(text, key, params):
    iv = big_endian_to_int(decode_hex(params["iv"]))
    ctr = Counter.new(128, initial_value=iv,  allow_wraparound=True)
    mode = AES.MODE_CTR
    encryptor = AES.new(key, mode, counter=ctr)
    return encryptor.encrypt(text)


def aes_ctr_decrypt(text, key, params):
    iv = big_endian_to_int(decode_hex(params["iv"]))
    ctr = Counter.new(128, initial_value=iv,  allow_wraparound=True)
    mode = AES.MODE_CTR
    encryptor = AES.new(key, mode, counter=ctr)
    return encryptor.decrypt(text)


def aes_mkparams():
    return {"iv": encode_hex(os.urandom(16))}


ciphers = {
    "aes-128-ctr": {
        "encrypt": aes_ctr_encrypt,
        "decrypt": aes_ctr_decrypt,
        "mkparams": aes_mkparams
    }
}


def mk_scrypt_params():
    params = SCRYPT_CONSTANTS.copy()
    params['salt'] = encode_hex(os.urandom(16))
    return params


def scrypt_hash(val, params):
    return scrypt.hash(str(val), decode_hex(params["salt"]), params["n"],
                       params["r"], params["p"], params["dklen"])


def mk_pbkdf2_params():
    params = PBKDF2_CONSTANTS.copy()
    params['salt'] = encode_hex(os.urandom(16))
    return params


def pbkdf2_hash(val, params):
    assert params["prf"] == "hmac-sha256"
    return pbkdf2.PBKDF2(val, decode_hex(params["salt"]), params["c"],
                         SHA256).read(params["dklen"])


kdfs = {
    "pbkdf2": {
        "calc": pbkdf2_hash,
        "mkparams": mk_pbkdf2_params
    }
}

if scrypt is not None:
    kdfs["scrypt"] = {
        "calc": scrypt_hash,
        "mkparams": mk_scrypt_params
    }


def make_keystore_json(priv, pw, kdf="pbkdf2", cipher="aes-128-ctr"):
    # Get the hash function and default parameters
    if kdf not in kdfs:
        raise Exception("Hash algo %s not supported" % kdf)
    kdfeval = kdfs[kdf]["calc"]
    kdfparams = kdfs[kdf]["mkparams"]()
    # Compute derived key
    derivedkey = kdfeval(pw, kdfparams)
    # Get the cipher and default parameters
    if cipher not in ciphers:
        raise Exception("Encryption algo %s not supported" % cipher)
    encrypt = ciphers[cipher]["encrypt"]
    cipherparams = ciphers[cipher]["mkparams"]()
    # Produce the encryption key and encrypt
    enckey = derivedkey[:16]
    c = encrypt(priv, enckey, cipherparams)
    # Compute the MAC
    mac = sha3(derivedkey[16:32] + c)
    # Make a UUID
    u = encode_hex(os.urandom(16))
    uuid = b'-'.join((u[:8], u[8:12], u[12:16], u[16:20], u[20:]))
    # Return the keystore json
    return {
        "crypto": {
            "cipher": cipher,
            "ciphertext": encode_hex(c),
            "cipherparams": cipherparams,
            "kdf": kdf,
            "kdfparams": kdfparams,
            "mac": encode_hex(mac),
            "version": 1
        },
        "id": uuid,
        "version": 3
    }


def check_keystore_json(jsondata):
    """Check if ``jsondata`` has the structure of a keystore file version 3.

    Note that this test is not complete, e.g. it doesn't check key derivation or cipher parameters.

    :param jsondata: dictionary containing the data from the json file
    :returns: `True` if the data appears to be valid, otherwise `False`
    """
    if 'crypto' not in jsondata and 'Crypto' not in jsondata:
        return False
    if 'version' not in jsondata:
        return False
    if jsondata['version'] != 3:
        return False
    crypto = jsondata.get('crypto', jsondata.get('Crypto'))
    if 'cipher' not in crypto:
        return False
    if 'ciphertext' not in crypto:
        return False
    if 'kdf' not in crypto:
        return False
    if 'mac' not in crypto:
        return False
    return True


def decode_keystore_json(jsondata, pw):
    # Get KDF function and parameters
    if "crypto" in jsondata:
        cryptdata = jsondata["crypto"]
    elif "Crypto" in jsondata:
        cryptdata = jsondata["Crypto"]
    else:
        raise Exception("JSON data must contain \"crypto\" object")
    kdfparams = cryptdata["kdfparams"]
    kdf = cryptdata["kdf"]
    if cryptdata["kdf"] not in kdfs:
        raise Exception("Hash algo %s not supported" % kdf)
    kdfeval = kdfs[kdf]["calc"]
    # Get cipher and parameters
    cipherparams = cryptdata["cipherparams"]
    cipher = cryptdata["cipher"]
    if cryptdata["cipher"] not in ciphers:
        raise Exception("Encryption algo %s not supported" % cipher)
    decrypt = ciphers[cipher]["decrypt"]
    # Compute the derived key
    derivedkey = kdfeval(pw, kdfparams)
    assert len(derivedkey) >= 32, \
        "Derived key must be at least 32 bytes long"
    # print(b'derivedkey: ' + encode_hex(derivedkey))
    enckey = derivedkey[:16]
    # print(b'enckey: ' + encode_hex(enckey))
    ctext = decode_hex(cryptdata["ciphertext"])
    # Decrypt the ciphertext
    o = decrypt(ctext, enckey, cipherparams)
    # Compare the provided MAC with a locally computed MAC
    # print(b'macdata: ' + encode_hex(derivedkey[16:32] + ctext))
    mac1 = sha3(derivedkey[16:32] + ctext)
    mac2 = decode_hex(cryptdata["mac"])
    if mac1 != mac2:
        raise ValueError("MAC mismatch. Password incorrect?")
    return o


# Utility functions (done separately from utils so as to make this a standalone file)

def sha3(seed):
    return sha3_256(seed).digest()


def zpad(x, l):
    return b'\x00' * max(0, l - len(x)) + x


if sys.version_info.major == 2:

    def decode_hex(s):
        if not isinstance(s, (str, unicode)):
            raise TypeError('Value must be an instance of str or unicode')
        return s.decode('hex')

    def encode_hex(s):
        if not isinstance(s, (str, unicode)):
            raise TypeError('Value must be an instance of str or unicode')
        return s.encode('hex')

    def int_to_big_endian(value):
        cs = []
        while value > 0:
            cs.append(chr(value % 256))
            value /= 256
        s = ''.join(reversed(cs))
        return s

    def big_endian_to_int(value):
        if len(value) == 1:
            return ord(value)
        elif len(value) <= 8:
            return struct.unpack('>Q', value.rjust(8, '\x00'))[0]
        else:
            return int(encode_hex(value), 16)


if sys.version_info.major == 3:

    def decode_hex(s):
        if isinstance(s, str):
            return bytes.fromhex(s)
        if isinstance(s, bytes):
            return binascii.unhexlify(s)
        raise TypeError('Value must be an instance of str or bytes')

    def encode_hex(b):
        if isinstance(b, str):
            b = bytes(b, 'utf-8')
        if isinstance(b, bytes):
            return binascii.hexlify(b)
        raise TypeError('Value must be an instance of str or bytes')

    def int_to_big_endian(value):
        byte_length = ceil(value.bit_length() / 8)
        return (value).to_bytes(byte_length, byteorder='big')

    def big_endian_to_int(value):
        return int.from_bytes(value, byteorder='big')


def privtoaddr(x):
    if len(x) > 32:
        x = decode_hex(x)
    return sha3(bitcoin.privtopub(x)[1:])[12:]
