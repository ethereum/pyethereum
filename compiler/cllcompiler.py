import re, sys
from cllparser import *

optable = { 
    '+': 'ADD',
    '-': 'SUB',
    '*': 'MUL',
    '/': 'DIV',
    '^': 'EXP',
    '%': 'MOD',
    '#/': 'SDIV',
    '#%': 'SMOD',
    '==': 'EQ',
    '<=': 'LE',
    '>=': 'GE',
    '<': 'LT',
    '>': 'GT'
}

funtable = {
    'sha256': ['SHA256', 3],
    'sha3': ['SHA3', 3],
    'ripemd160': ['RIPEMD160', 3],
    'ecsign': ['ECSIGN', 2],
    'ecrecover': ['ECRECOVER', 3],
    'ecvalid': ['ECVALID', 2],
    'ecadd': ['ECADD', 4],
    'ecmul': ['ECMUL', 3],
}

pseudovars = {
    'tx.datan': 'TXDATAN',
    'tx.sender': 'TXSENDER',
    'tx.value': 'TXVALUE',
    'block.timestamp': 'BLK_TIMESTAMP',
    'block.number': 'BLK_NUMBER',
    'block.basefee': 'BASEFEE',
    'block.difficulty': 'BLK_DIFFICULTY',
    'block.coinbase': 'BLK_COINBASE',
    'block.parenthash': 'BLK_PREVHASH'
}

pseudoarrays = {
    'tx.data': 'TXDATA',
    'contract.storage': 'SLOAD',
    'block.address_balance': 'BALANCE',
}

# Left-expressions can either be:
# * variables
# * A[B] where A is a left-expr and B is a right-expr
# * contract.storage[B] where B is a right-expr
def get_left_expr_type(expr):
    if isinstance(expr,str):
        return 'variable'
    elif expr[0] == 'access' and expr[1] == 'contract.storage':
        return 'storage'
    else:
        return 'access'

def compile_left_expr(expr,varhash):
    typ = get_left_expr_type(expr)
    if typ == 'variable':
        if re.match('^[0-9\-]*$',expr):
            raise Exception("Can't set the value of a number! "+expr)
        elif expr in varhash:
            return ['PUSH',varhash[expr]]
        else:
            varhash[expr] = len(varhash)
            return ['PUSH',varhash[expr]]
    elif typ == 'storage':
        return compile_expr(expr[1],varhash)
    elif typ == 'access':
        if get_left_expr_type(expr[1]) == 'storage':
            return compile_left_expr(expr[1],varhash) + 'SLOAD' + compile_expr(expr[2],varhash)
        else:
            return compile_left_expr(expr[1],varhash) + compile_expr(expr[2],varhash) + ['ADD']
    else:
        raise Exception("invalid op: "+expr[0])

# Right-hand-side expressions (ie. the normal kind)
def compile_expr(expr,varhash):
    if isinstance(expr,str):
        if re.match('^[0-9\-]*$',expr):
            return ['PUSH',int(expr)]
        elif expr in varhash:
            return ['PUSH',varhash[expr],'MLOAD']
        elif expr in pseudovars:
            return [pseudovars[expr]]
        else:
            varhash[expr] = len(varhash)
            return ['PUSH',varhash[expr],'MLOAD']
    elif expr[0] in optable:
        if len(expr) != 3:
            raise Exception("Wrong number of arguments: "+str(expr)) 
        f = compile_expr(expr[1],varhash)
        g = compile_expr(expr[2],varhash)
        return f + g + [optable[expr[0]]]
    elif expr[0] == 'fun' and expr[1] in funtable:
        if len(expr) != funtable[expr[0]][1] + 1:
            raise Exception("Wrong number of arguments: "+str(expr)) 
        f = sum([compile_expr(e,varhash) for e in expr[2:]],[])
        return f + [funtable[expr[1]][0]]
    elif expr[0] == 'access':
        if expr[1][0] == 'block.contract_storage':
            return compile_expr(expr[2],varhash) + compile_expr(expr[1][1],varhash) + ['EXTRO']
        elif expr[1] == 'contract.storage':
            return compile_expr(expr[2],varhash) + ['SLOAD']
        else:
            return compile_left_expr(expr[1],varhash) + compile_expr(expr[2],varhash) + ['ADD','MLOAD']
    elif expr[0] == 'fun' and expr[1] == 'array':
        return [ 'PUSH', 0, 'PUSH', 1, 'SUB', 'MLOAD', 'PUSH',
                         2, 'PUSH', 160, 'EXP', 'ADD', 'DUP',
                         'PUSH', 0, 'PUSH', 1, 'SUB', 'MSTORE' ]
    elif expr[0] == '!':
        f = compile_expr(expr[1],varhash)
        return f + ['NOT']
    elif expr[0] in pseudoarrays:
        return compile_expr(expr[1],varhash) + pseudoarrays[expr[0]]
    elif expr[0] in ['or', '||']:
        return compile_expr(['!', [ '*', ['!', expr[1] ], ['!', expr[2] ] ] ],varhash)
    elif expr[0] in ['and', '&&']: 
        return compile_expr(['!', [ '+', ['!', expr[1] ], ['!', expr[2] ] ] ],varhash)
    elif expr[0] == 'multi':
        return sum([compile_expr(e,varhash) for e in expr],[])
    elif expr == 'tx.datan':
        return ['DATAN']
    else:
        raise Exception("invalid op: "+expr[0])

# Statements (ie. if, while, a = b, a,b,c = d,e,f, [ s1, s2, s3 ], stop, suicide)
def compile_stmt(stmt,varhash={},lc=[0]):
    if stmt[0] == 'if':
        f = compile_expr(stmt[1],varhash)
        g = compile_stmt(stmt[2],varhash,lc)
        h = compile_stmt(stmt[3],varhash,lc) if len(stmt) > 3 else None
        label, ref = 'LABEL_'+str(lc[0]), 'REF_'+str(lc[0])
        lc[0] += 1
        if h: return f + [ 'NOT', ref, 'JMPI' ] + g + [ ref, 'JMP' ] + h + [ label ]
        else: return f + [ 'NOT', ref, 'JMPI' ] + g + [ label ]
    elif stmt[0] == 'while':
        f = compile_expr(stmt[1],varhash)
        g = compile_stmt(stmt[2],varhash,lc)
        beglab, begref = 'LABEL_'+str(lc[0]), 'REF_'+str(lc[0])
        endlab, endref = 'LABEL_'+str(lc[0]+1), 'REF_'+str(lc[0]+1)
        lc[0] += 2
        return [ beglab ] + f + [ 'NOT', endref, 'JMPI' ] + g + [ begref, 'JMP', endlab ]
    elif stmt[0] == 'set':
        lexp = compile_left_expr(stmt[1],varhash)
        rexp = compile_expr(stmt[2],varhash)
        lt = get_left_expr_type(stmt[1])
        return rexp + lexp + ['SSTORE' if lt == 'storage' else 'MSTORE']
    elif stmt[0] == 'mset':
        rexp = compile_expr(stmt[2],varhash)
        exprstates = [get_left_expr_type(e) for e in stmt[1][1:]]
        o = rexp
        for e in stmt[1][1:]:
            o += compile_left_expr(stmt[1])
            o += [ 'SSTORE' if get_left_expr_type(e) == 'storage' else 'MSTORE' ]
        return o
    elif stmt[0] == 'seq':
        o = []
        for s in stmt[1:]:
            o.extend(compile_stmt(s,varhash,lc))
        return o
    elif stmt[0] == 'fun' and stmt[1] == 'mktx':
        to = compile_expr(stmt[2],varhash)
        value = compile_expr(stmt[3],varhash)
        datan = compile_expr(stmt[4],varhash)
        datastart = compile_expr(stmt[5],varhash)
        return datastart + datan + value + to + [ 'MKTX' ]
    elif stmt == 'stop':
        return [ 'STOP' ]
    elif stmt[0] == 'fun' and stmt[1] == 'suicide':
        return compile_expr(stmt[2]) + [ 'SUICIDE' ]
        

# Dereference labels
def assemble(c):
    iq = [x for x in c]
    mq = []
    labelmap = {}
    while len(iq):
        front = iq.pop(0)
        if isinstance(front,str) and front[:6] == 'LABEL_':
            labelmap[front[6:]] = len(mq)
        else:
            mq.append(front)
    oq = []
    for m in mq:
        if isinstance(m,str) and m[:4] == 'REF_':
            oq.append('PUSH')
            oq.append(labelmap[m[4:]])
        else: oq.append(m)
    return oq

def compile(source):
    lines = source.split('\n')
    p = parse_lines(lines)
    print (p)
    return assemble(compile_stmt(p))

if len(sys.argv) >= 2:
    try:
        open(sys.argv[1]).read()
        print (' '.join([str(k) for k in compile(open(sys.argv[1]).read())]))
    except:
        print (' '.join([str(k) for k in compile(sys.argv[1])]))
