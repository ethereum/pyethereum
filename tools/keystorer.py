#!/usr/bin/python2.7

import sys, json, os
from bitcoin import privtopub
try:
    import keys
except:
    try:
        import ethereum.keys as keys
    except:
        raise Exception("keys module not found")


def privtoaddr(x):
    if len(x) > 32:
        x = keys.decode_hex(x)
    return keys.sha3(privtopub(x)[1:])[12:]


# Help
if len(sys.argv) < 2:
    print("Use `keystorer.py create <pw> <optional privkey>` to create a key store file, and `keystorer.py getprivkey <filename> <pw>` or `keystorer.py getaddress <filename> <pw> to get a privkey/address from a key store file, respectively")
# Create a json
elif sys.argv[1] == 'create':
    if len(sys.argv) < 4:
        key = os.urandom(32)
    else:
        key = keys.decode_hex(sys.argv[3])
    pw = sys.argv[2]
    print("Applying hard key derivation function. Wait a little")
    j = keys.make_keystore_json(key, pw)
    print j
    open(j["id"]+'.json', 'w').write(json.dumps(j, indent=4))
    print("Wallet creation successful, file saved at: " + j["id"] + ".json")
# Decode a json
elif sys.argv[1] in ('getprivkey', 'getaddress'):
    if len(sys.argv) < 3:
        raise Exception("Need filename")
    json = json.loads(open(sys.argv[2]).read())
    if len(sys.argv) < 4:
        raise Exception("Need password")
    pw = sys.argv[3]
    print("Applying hard key derivation function. Wait a little")
    k = keys.decode_keystore_json(json, pw)
    if sys.argv[1] == 'getprivkey':
        print(keys.encode_hex(k))
    else:
        print(keys.encode_hex(keys.privtoaddr(k)))
