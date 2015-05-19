import scrypt, os
from ethereum import utils
from Crypto.Cipher import AES

# TODO: make it compatible!


def aes_encrypt(text, key, IV=16 * '\x00'):
    mode = AES.MODE_CBC
    encryptor = AES.new(key, mode, IV=IV)
    return encryptor.encrypt(text)


def aes_decrypt(text, key, IV=16 * '\x00'):
    mode = AES.MODE_CBC
    encryptor = AES.new(key, mode, IV=IV)
    return encryptor.decrypt(text)


def make_keystore_json(priv, pw):
    iv = os.urandom(16)
    salt = os.urandom(16)
    N, R, P, DKLEN = 262144, 8, 1, 32
    k = utils.sha3(scrypt.hash(pw, salt, N, R, P, DKLEN)[:16])
    c = aes_encrypt(priv, k[:16], iv)
    mac = utils.sha3(k[16:] + c)
    return {
        "crypto": {
            "cipher": "aes-128-cbc",
            "ciphertext": utils.encode_hex(c),
            "cipherparams": {"iv": utils.encode_hex(iv)},
            "kdf": "scrypt",
            "kdfparams":
                {"dklen": DKLEN, "n": N, "p": P,
                 "r": R, "salt": utils.encode_hex(salt)},
            "mac": utils.encode_hex(mac),
            "version": 1
        },
        "id": "",
        "version": 2
    }


def decode_keystore_json(jsondata, pw):
    iv = utils.decode_hex(jsondata["crypto"]["cipherparams"]["iv"])
    salt = utils.decode_hex(jsondata["crypto"]["kdfparams"]["salt"])
    assert jsondata["crypto"]["kdf"] == "scrypt", \
        "Only scrypt supported"
    assert jsondata["crypto"]["cipher"] == "aes-128-cbc", \
        "Only aes-128-cbc supported"
    N, R, P, DKLEN = 262144, 8, 1, 32
    k = utils.sha3(scrypt.hash(pw, salt, N,
                   R, P, DKLEN)[:16])
    ctext = utils.decode_hex(jsondata["crypto"]["ciphertext"])
    o = aes_decrypt(ctext, k[:16], iv)
    mac1 = utils.sha3(k[16:] + ctext)
    mac2 = utils.decode_hex(jsondata["crypto"]["mac"])
    assert mac1 == mac2
    return o
