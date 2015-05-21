import os, pbkdf2, copy, sys
try:
    scrypt = __import__('scrypt')
except:
    sys.stderr.write("""
    Failed to import scrypt. This is not a fatal error but does
    mean that you cannot create or decrypt privkey jsons that use
    scrypt""")
    scrypt = None
from ethereum import utils
from Crypto.Cipher import AES
from Crypto.Hash import SHA256

# TODO: make it compatible!


def aes_encrypt(text, key, params):
    mode = AES.MODE_CBC
    encryptor = AES.new(key, mode, IV=utils.decode_hex(params["iv"]))
    return encryptor.encrypt(text)


def aes_decrypt(text, key, params):
    mode = AES.MODE_CBC
    encryptor = AES.new(key, mode, IV=utils.decode_hex(params["iv"]))
    return encryptor.decrypt(text)


def aes_mkparams():
    return {"iv": utils.encode_hex(os.urandom(16))}


ciphers = {
    "aes-128-cbc": {
        "encrypt": aes_encrypt,
        "decrypt": aes_decrypt,
        "mkparams": aes_mkparams
    }
}


def mk_scrypt_params():
    return {
        "n": 262144,
        "p": 1,
        "r": 8,
        "dklen": 32,
        "salt": utils.encode_hex(os.urandom(16))
    }


def scrypt_hash(val, params):
    return scrypt.hash(val, utils.decode_hex(params["salt"]), params["n"],
                       params["r"], params["p"], params["dklen"])


def mk_pbkdf2_params():
    return {
        "prf": "hmac-sha256",
        "dklen": 32,
        "c": 262144,
        "salt": utils.encode_hex(os.urandom(16))
    }


def pbkdf2_hash(val, params):
    assert params["prf"] == "hmac-sha256"
    return pbkdf2.PBKDF2(val, utils.decode_hex(params["salt"]), params["c"],
                         SHA256).read(params["dklen"])


kdfs = {
    "scrypt": {
        "calc": scrypt_hash,
        "mkparams": mk_scrypt_params
    },
    "pbkdf2": {
        "calc": pbkdf2_hash,
        "mkparams": mk_pbkdf2_params
    }
}


def make_keystore_json(priv, pw, kdf="pbkdf2", cipher="aes-128-cbc"):
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
    k = utils.sha3(derivedkey[:16])[:16]
    c = encrypt(priv, k, cipherparams)
    # Compute the MAC
    mac = utils.sha3(derivedkey[16:] + c)
    # Return the keystore json
    return {
        "crypto": {
            "cipher": cipher,
            "ciphertext": utils.encode_hex(c),
            "cipherparams": cipherparams,
            "kdf": kdf,
            "kdfparams": kdfparams,
            "mac": utils.encode_hex(mac),
            "version": 1
        },
        "id": "",
        "version": 2
    }


def decode_keystore_json(jsondata, pw):
    # Get KDF function and parameters
    kdfparams = jsondata["crypto"]["kdfparams"]
    kdf = jsondata["crypto"]["kdf"]
    if jsondata["crypto"]["kdf"] not in kdfs:
        raise Exception("Hash algo %s not supported" % kdf)
    kdfeval = kdfs[kdf]["calc"]
    # Get cipher and parameters
    cipherparams = jsondata["crypto"]["cipherparams"]
    cipher = jsondata["crypto"]["cipher"]
    if jsondata["crypto"]["cipher"] not in ciphers:
        raise Exception("Encryption algo %s not supported" % cipher)
    decrypt = ciphers[cipher]["decrypt"]
    # Compute the derived key
    derivedkey = kdfeval(pw, kdfparams)
    k = derivedkey
    ctext = utils.decode_hex(jsondata["crypto"]["ciphertext"])
    # Decrypt the ciphertext
    o = decrypt(ctext, k, cipherparams)
    # Compare the provided MAC with a locally computed MAC
    mac1 = utils.sha3(derivedkey[-16:] + ctext)
    mac2 = utils.decode_hex(jsondata["crypto"]["mac"])
    assert mac1 == mac2, (mac1, mac2)
    return o
