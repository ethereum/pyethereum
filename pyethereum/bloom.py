import utils

BUCKETS_PER_VAL = 5


def bloom_insert(bloom, val):
    h = utils.sha3(val)
    for i in range(BUCKETS_PER_VAL):
        bloom |= 1 << ord(h[i])
    return bloom


def bloom_query(bloom, val):
    bloom2 = bloom_insert(0, val)
    return (bloom & bloom2) == bloom2


def bloom_combine(*args):
    bloom = 0
    for arg in args:
        bloom |= arg
    return bloom


def bloom_from_list(args):
    return bloom_combine(*[bloom_insert(0, arg) for arg in args])
