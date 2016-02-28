# TOTALLY NOT TESTED AND LIKELY BROKEN AT THIS POINT; AWAITING A TEST SUITE
data dummy[2**50]
data participants[2**40](x, y)
data participantsCount
data spendsCount
data IValuesConsumed[]

PARTICIPANTS_PER_BUCKET = 5
DENOMINATION = 10**17

Gx = 55066263022277343669578718895168534326250603453777594175500187360389116729240
Gy = 32670510020758816978083085130507043184471273380659243275938904335757337482424
P = -4294968273
ECADD = 5
ECMUL = 6
MODEXP = 7

# Macro to do elliptic curve multiplication; ecmul([x, y], n) -> [x', y']
macro ecmul($p, $n):
    with $x = array(2):
        ~call(msg.gas - 20000, ECMUL, 0, [$p[0], $p[1], $n], 96, $x, 64)
        $x

# Macro to do elliptic curve addition; ecadd([x1, y1], [x2, y2]) -> [x', y']
macro ecadd($a, $b):
    with $x = array(2):
        ~call(msg.gas - 20000, ECADD, 0, [$a[0], $a[1], $b[0], $b[1]], 128, $x, 64)
        $x

# Macro to do elliptic curve subtraction; ecadd([x1, y1], [x2, y2]) -> [x', y']
macro ecsubtract($a, $b):
    with $x = array(2):
        ~call(msg.gas - 20000, ECADD, 0, [$a[0], $a[1], $b[0], P - $b[1]], 128, $x, 64)
        $x

event ValueLogEvent(i:uint256)

event PubkeyLogEvent(x:uint256, y:uint256)

event PubkeyTripleLogEvent(x:uint256, y:uint256, z:uint256)

event Deposit(x:uint256, y:uint256, bucketId:uint256)

event Withdrawal(toaddr:address, bucketId:uint256)
event Progress(index:uint256:indexed)
event Gas(gas:uint256:indexed)
event BadSignature()
event HashResult(x:uint256:indexed, y:uint256:indexed)

# Hash a public key to get a public key
def hash_pubkey_to_pubkey(pub:arr):
    with x = sha3(pub:arr):
        while 1:
            xcubed = mulmod(mulmod(x, x, P), x, P)
            beta = 0
            ~call(msg.gas - 6000, MODEXP, 0, [addmod(xcubed, 7, P), div(P + 1, 4), P], 96, ref(beta), 32)
            y = beta * mod(beta, 2) + (P - beta) * (1 - mod(beta, 2))
            # Return if the result is not a quadratic residue
            if addmod(xcubed, 7, P) == mulmod(y, y, P):
                return([x, y]:arr)
            x = mod(x + 1, P)

# Get the list of public keys for a given bucket ID
def const getPubs(bucketId:uint256):
    pubs = array(2 * PARTICIPANTS_PER_BUCKET)
    i = 0
    while i < PARTICIPANTS_PER_BUCKET:
        pubs[2 * i] = self.participants[bucketId * 5 + i].x
        pubs[2 * i + 1] = self.participants[bucketId * 5 + i].y
        i += 1
    return(pubs:arr)

def const getNextIndex():
    return(self.participantsCount)

def const getSpendsCount():
    return(self.spendsCount)

# Submit ETH into the mixer
def submit(x:uint256, y:uint256):
    if msg.value != DENOMINATION:
        send(msg.sender, msg.value)
        stop
    self.participants[self.participantsCount].x = x
    self.participants[self.participantsCount].y = y
    self.participantsCount += 1
    log(type=Deposit, x, y, bucketId)
    return((self.participantsCount - 1) / PARTICIPANTS_PER_BUCKET)

event EValues(left:uint256:indexed, right:uint256:indexed)
event Pub(x:uint256:indexed, y:uint256:indexed)
event Sub(x:uint256:indexed, y:uint256:indexed)

# Withdraw ETH from the mixer by submitting a ring signature
def withdraw(to:address, x0:uint256, s:uint256[], Ix:uint256, Iy:uint256, bucketId:uint256):
    # Ensure that the bucket is full
    assert self.participantsCount >= (bucketId + 1) * PARTICIPANTS_PER_BUCKET
    # Ensure that this user has not yet withdrawn
    assert not self.IValuesConsumed[sha3([Ix, Iy]:arr)]
    # Number of pubkeys
    n = PARTICIPANTS_PER_BUCKET
    # Decompress the provided I value
    # Iy = self.recover_y(Ix, Iy)
    # Store the list of intermediate values in the "ring"
    e = array(n + 1)
    # Set the first value in the ring to that provided in the signature
    e[0] = [x0, sha3(x0)]
    G = [Gx, Gy]
    i = 1
    while i < n + 1:
        # log(type=Progress, 100 + i)
        prev_i = (i - 1) % n
        # Decompress the public key
        pub_xi = self.participants[bucketId * 5 + (i % n)].x
        pub_yi = self.participants[bucketId * 5 + (i % n)].y
        # Create the point objects
        pub = [pub_xi, pub_yi]
        # log(type=Pub, pub_xi, pub_yi)
        I = [Ix, Iy]
        # Create the next values in the ring based on the provided s value
        k1 = ecmul(G, s[prev_i])
        k2 = ecmul(pub, e[prev_i][1])
        pub1 = ecsubtract(k1, k2)
        # log(type=Pub, pub1[0], pub1[1])
        # log(type=Gas, msg.gas)
        k3 = self.hash_pubkey_to_pubkey(pub, outitems=2)
        # log(type=Sub, k3[0], k3[1])
        k4 = ecmul(k3, s[prev_i])
        k5 = ecmul(I, e[prev_i][1])
        pub2 = ecsubtract(k4, k5)
        # log(type=Pub, pub2[0], pub2[1])
        left = sha3([to, pub1[0], pub1[1], pub2[0], pub2[1]]:arr)
        right = sha3(left)
        e[i] = [left, right]
        # log(type=EValues, left, right)
        # log(type=Gas, msg.gas)
        i += 1
    log(type=Progress, 6)
    # Check that the ring is consistent
    if e[n][0] == e[0][0] and e[n][1] == e[0][1]:
            # Check that this I value has not yet been used
            self.IValuesConsumed[sha3([Ix, Iy]:arr)] = 1
            # Send, taking a 1% fee to pay for gas
            send(to, DENOMINATION * 99 / 100)
            log(type=Withdrawal, to, bucketId)
            self.spendsCount += 1
            # Lazy shim for now: hardcode 25 shannon gas price
            return(25 * 10**9)
    log(type=Progress, 8)
    log(type=BadSignature)
    return(0)
