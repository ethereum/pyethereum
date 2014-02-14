import random
for i in range(30):
    nodes = [3] + [0] * (2**23 - 1)
    
    tc = [0]

    def calc(n):
        if nodes[n]: return nodes[n]
        else:
            tc[0] += 1
            v = random.randrange(2**256)
            L = 2 if n < 2**21 else 11 if n < 2**22 else 3
            for i in range(L):
                p = v%n if i < 2 else v%(2**21)
                calc(p)
                v /= n
            nodes[n] = 1
            return 1

    calc(2**22 + random.randrange(2**22))

    print (tc[0])
    
