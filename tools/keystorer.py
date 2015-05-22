#!/usr/bin/python2.7

import sys, json, os
try:
    import keys
except:
    try:
        import ethereum.keys as keys
    except:
        raise Exception("keys module not found")

# Help
if len(sys.argv) < 2:
    print("Use `keystorer.py create <pw> <optional privkey>` to create a key store file, and `keystorer.py decode <filename> <pw>` to decode a key store file")
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
elif sys.argv[1] == 'decode':
    if len(sys.argv) < 3:
        raise Exception("Need filename")
    json = json.loads(open(sys.argv[2]).read())
    if len(sys.argv) < 4:
        raise Exception("Need password")
    pw = sys.argv[3]
    print("Applying hard key derivation function. Wait a little")
    print(keys.encode_hex(keys.decode_keystore_json(json, pw)))
