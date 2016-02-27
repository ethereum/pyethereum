import bitcoin as b
import utils

def hash_array(arr):
    o = ''
    for x in arr:
        if isinstance(x, (int, long)):
            x = utils.zpad(utils.encode_int(x), 32)
        o += x
    return utils.big_endian_to_int(utils.sha3(o))

def hash_value(x):
    if isinstance(x, (int, long)):
        x = utils.zpad(utils.encode_int(x), 32)
    return utils.big_endian_to_int(utils.sha3(x))

def hash_to_pubkey(x):
    from bitcoin import A, B, P, encode_pubkey
    x = hash_array(x) if isinstance(x, list) else hash_value(x)
    while 1:
        xcubedaxb = (x*x*x+A*x+B) % P
        beta = pow(xcubedaxb, (P+1)//4, P)
        y = beta if beta % 2 else (P - beta)
        # Return if the result is not a quadratic residue
        if (xcubedaxb - y*y) % P == 0:
            return (x, y)
        x = x + 1

def ringsig_sign_substitute(msg, priv, pubs):
    # Number of pubkeys
    n = len(pubs)
    # My pubkey
    my_pub = b.decode_pubkey(b.privtopub(priv))
    # Compute my index in the pubkey list
    my_index = 0
    while my_index < n:
        if pubs[my_index] == my_pub:
            break
        my_index += 1
    assert my_index < n
    # Compute the signer's I value
    I = b.multiply(hash_to_pubkey(list(my_pub)), priv)
    # Select a random ephemeral key
    k = b.hash_to_int(b.random_key())
    # Store the list of intermediate values in the "ring"
    e = [None] * n
    # Compute the entry in the ring corresponding to the signer's index
    kpub = b.privtopub(k)
    kmulpub = b.multiply(hash_to_pubkey(list(my_pub)), k)
    orig_left = hash_array([msg, kpub[0], kpub[1], kmulpub[0], kmulpub[1]])
    orig_right = hash_value(orig_left)
    e[my_index] = {"left": orig_left, "right": orig_right}
    # Map of intermediate s values (part of the signature)
    s = [None] * n
    for i in list(range(my_index + 1, n)) + list(range(my_index + 1)):
        prev_i = (i - 1) % n
        # In your position in the ring, set the s value based on your private
        # knowledge of k; this lets you "invert" the hash function in order to
        # ensure a consistent ring. At all other positions, select a random s
        if i == my_index:
            s[prev_i] = b.add_privkeys(k, b.mul_privkeys(e[prev_i]["right"], priv))
        else:
            s[prev_i] = b.hash_to_int(b.random_key())
        # Create the next values in the ring based on the chosen s value
        pub1 = b.subtract_pubkeys(b.privtopub(s[prev_i]),
                                  b.multiply(pubs[i], e[prev_i]["right"]))
        pub2 = b.subtract_pubkeys(b.multiply(hash_to_pubkey(list(pubs[i])), s[prev_i]),
                                  b.multiply(I, e[prev_i]["right"]))
        left = hash_array([msg, pub1[0], pub1[1], pub2[0], pub2[1]])
        right = hash_value(left)
        e[i] = {"left": left, "right": right}
    # Check that the ring is consistent
    assert (left, right) == (orig_left, orig_right)
    # Return the first value in the ring, the s values, and the signer's
    # I value in compressed form
    return (e[0]["left"], s, I[0], I[1])


def ringsig_verify_substitute(msghash, x0, s, Ix, Iy, pubs):
    # Number of pubkeys
    n = len(pubs)
    # Create list of pubkeys as (x, y) points
    # Decompress the provided I value
    I = Ix, Iy
    # Store the list of intermediate values in the "ring"
    e = [None] * (n + 1)
    # Set the first value in the ring to that provided in the signature
    e[0] = [x0, hash_value(x0)]
    i = 1
    while i < n + 1:
        # print 'pub', pubs[i % n][0], pubs[i % n][1]
        prev_i = (i - 1) % n
        # Create the next values in the ring based on the provided s value
        pub1 = b.subtract_pubkeys(b.privtopub(s[prev_i]),
                                  b.multiply(pubs[i % n], e[prev_i][1]))
        # print 'pub', pub1[0], pub1[1]
        pub2 = b.subtract_pubkeys(b.multiply(hash_to_pubkey(list(pubs[i % n])), s[prev_i]),
                                  b.multiply(I, e[prev_i][1]))
        # print 'pub', pub2[0], pub2[1]
        left = hash_array([msghash, pub1[0], pub1[1], pub2[0], pub2[1]])
        right = hash_value(left)
        # FOR DEBUGGING
        # if i >= 1:
        #     print 'pre', pubs[i % n]
        #     print 'pub1', pub1
        #     print 'pub2', pub2
        #     print 'left', left
        #     print 'right', right
        e[i] = [left, right]
        # print 'evalues', left, right
        i += 1
    # Check that the ring is consistent
    return(e[n][0] == e[0][0] and e[n][1] == e[0][1])

# Testing
print 'Ringsig python implementation sanity checking'
privs = [b.sha256(str(i)) for i in range(5)]
pubs = [b.decode_pubkey(b.privtopub(k)) for k in privs]
sigs = [ringsig_sign_substitute('\x35' * 32, k, pubs) for k in privs]
vers = [ringsig_verify_substitute('\x35' * 32, x0, s, Ix, Iy, pubs) for x0, s, Ix, Iy in sigs]
assert vers == [True] * len(vers)
print 'Ringsig python implementation sanity check passed'
