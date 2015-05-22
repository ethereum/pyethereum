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
    o = [utils.big_endian_to_int(utils.decode_hex(params["iv"]))]

    def ctr():
        o[0] += 1
        if o[0] > 2**128:
            o[0] -= 2**128
        return utils.zpad(utils.int_to_big_endian(o[0] - 1), 16)
    mode = AES.MODE_CTR
    encryptor = AES.new(key, mode, counter=ctr)
    return encryptor.encrypt(text)


def aes_decrypt(text, key, params):
    o = [utils.big_endian_to_int(utils.decode_hex(params["iv"]))]

    def ctr():
        o[0] += 1
        if o[0] > 2**128:
            o[0] -= 2**128
        return utils.zpad(utils.int_to_big_endian(o[0] - 1), 16)
    mode = AES.MODE_CTR
    encryptor = AES.new(key, mode, counter=ctr)
    return encryptor.decrypt(text)


def aes_mkparams():
    return {"iv": utils.encode_hex(os.urandom(16))}


ciphers = {
    "aes-128-ctr": {
        "encrypt": aes_encrypt,
        "decrypt": aes_decrypt,
        "mkparams": aes_mkparams
    }
}


def mk_scrypt_params():
    return {
        "n": 262144,
        "r": 1,
        "p": 8,
        "dklen": 32,
        "salt": utils.encode_hex(os.urandom(16))
    }


def scrypt_hash(val, params):
    return scrypt.hash(str(val), utils.decode_hex(params["salt"]), params["n"],
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
    mac = utils.sha3(derivedkey[16:32] + c)
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
    assert len(derivedkey) >= 32, \
        "Derived key must be at least 32 bytes long"
    # print 'derivedkey: ' + derivedkey.encode('hex')
    enckey = derivedkey[:16]
    # print 'enckey: ' + enckey.encode('hex')
    ctext = utils.decode_hex(jsondata["crypto"]["ciphertext"])
    # Decrypt the ciphertext
    o = decrypt(ctext, enckey, cipherparams)
    # Compare the provided MAC with a locally computed MAC
    # print 'macdata: ' + (derivedkey[16:32] + ctext).encode('hex')
    mac1 = utils.sha3(derivedkey[-16:] + ctext)
    mac2 = utils.decode_hex(jsondata["crypto"]["mac"])
    assert mac1 == mac2, (mac1, mac2)
    return o
