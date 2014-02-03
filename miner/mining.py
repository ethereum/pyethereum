import sys
sys.path.insert(0,'/usr/local/lib')
import sha3, time

def bin_sha256(x): return sha3.sha3_256(x).digest()

def spread(L): return 16 if L == 9 else 3

def nodes(L): return 2**26 if L == 10 else 2**25 if L == 9 else 8**L

def to_binary(x): return '' if x == 0 else to_binary(int(x / 256)) + chr(x % 256)

def from_binary(x): return 0 if x == '' else 256 * from_binary(x[:-1]) + ord(x[-1])

def mine(root,difficulty,extranonce):
    layers = [[] for x in range(9)]
    layers[0] = [root]
    x = time.time()
    for L in range(1,11):
        prefix = root + to_binary(extranonce) + to_binary(L)
        for i in range(nodes(L)):
            p = []
            h = 0
            slots = len(to_binary(nodes(L) ** spread(L)))
            while slots >= 32:
                h = h * 2**256 + from_binary(bin_sha256(prefix + to_binary(i)))
                slots -= 32
            for k in range(spread(L)):
                ind = h % nodes(L-1)
                h = h / nodes(L-1)
                p.append(layers[L-1][ind])
            output = bin_sha256(to_binary(i)+''.join(p))
            if L < 10:
                layers[L].append(output)
            else:
                if from_binary(output) < 2**256 / difficulty: return i
        print ("Computed level ",L,"time",time.time()-x)
    return None

def verify(root,difficulty,extranonce,nonce):
    layers = [{} for x in range(9)]
    layers[0] = [root]
    def getnode(L,i):
        if i not in layers[L]:
            p = []
            for k in range(spread(L)):
                h = bin_sha256(root + to_binary(extranonce) + to_binary(L) + to_binary(o) + to_binary(k))
                ind = from_binary(h) % nodes(L-1)
                p.append(getnode(L-1,ind))
            layers[L][i] = bin_sha256(''.join(p))
        return layers[L][i]
    p = []
    for k in range(4):
        h = bin_sha256(root + to_binary(extranonce) + to_binary(nonce) + to_binary(k))
        ind = from_binary(h) % nodes(9)
        p.append(getnode(9,ind))
    h = from_binary(bin_sha256(''.join(p)))
    return h * difficulty <= 2**256
