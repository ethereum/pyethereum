import re, sys

def spaces(ln):
    spaces = 0
    while spaces < len(ln) and ln[spaces] == ' ': spaces += 1
    return spaces

def parse_lines(lns):
    o = []
    i = 0
    while i < len(lns):
        main = lns[i]
        oldi = i+1
        if len(main.strip()) == 0:
            i += 1
            continue
        if spaces(main) > 0:
            raise Exception("Line "+str(i)+" indented too much!")
        spacesmin = 99999999
        i += 1
        while i < len(lns):
            sp = spaces(lns[i])
            if sp == 0: break
            spacesmin = min(sp,spacesmin)
            i += 1
        sub = map(lambda x:x[spacesmin:],lns[oldi:i])
        out = parse_line(main)
        #print 'o',o
        #print 'out',out
        #print 'sub',sub
        if out[0] in ['if', 'else', 'while', 'else if']:
            out.append(parse_lines(sub))
        if out[0] == 'else if':
            u = o[-1]
            while len(u) == 4: u = u[-1]
            #print 'u',u
            u.append(['if'] + out[1:])
        elif out[0] == 'else':
            u = o[-1]
            while len(u) == 4: u = u[-1]
            #print 'u',u
            u.append(out[1])
        else:
            o.append(out)
    return o[0] if len(o) == 1 else ['seq'] + o

def chartype(c):
    if c in 'abcdefhijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.':
        return 'alphanum'
    elif c in '\t ': return 'space'
    elif c in '()[]': return 'brack'
    else: return 'symb'

def tokenize(ln):
    tp = 'space'
    i = 0
    o = []
    global cur
    cur = ''
    def nxt():
        global cur
        if len(cur) >= 2 and cur[-1] == '-':
            o.extend([cur[:-1],'-'])
        elif len(cur.strip()) >= 1:
            o.append(cur)
        cur = ''
    while i < len(ln):
        c = chartype(ln[i])
        if c == 'brack' or tp == 'brack': nxt()
        elif c == 'space': nxt()
        elif c != 'space' and tp == 'space': nxt()
        elif c == 'symb' and tp != 'symb': nxt()
        elif c == 'alphanum' and tp == 'symb': nxt()
        cur += ln[i]
        tp = c
        i += 1
    nxt()
    if o[-1] in [':',':\n','\n']: o.pop()
    return o

precedence = {
    '^': 1,
    '*': 2,
    '/': 3,
    '%': 4,
    '#/': 2,
    '#%': 2,
    '+': 3,
    '-': 3,
    '<': 4,
    '<=': 4,
    '>': 4,
    '>=': 4,
    '==': 5,
    'and': 6,
    'or': 7,
}

functions = {
    'sha256': 1,
    'ripemd160': 1,
    'sha3': 1,
    'balance': 1,
    'tx.contract_balance': 1
}

def toktype(token):
    if token is None: return None
    elif token in ['(','[']: return 'lparen'
    elif token in [')',']']: return 'rparen'
    elif token in functions: return 'fun'
    elif token in ['!']: return 'monop' 
    elif token in precedence: return 'op'
    elif re.match('^[0-9a-z\-]*$',token): return 'alphanum'
    else: raise Exception("Invalid token: "+token)

# https://en.wikipedia.org/wiki/Shunting-yard_algorithm
def shunting_yard(tokens):
    iq = [x for x in tokens]
    oq = []
    stack = []
    prev,tok = None,None
    def popstack(stack,oq):
        tok = stack.pop()
        typ = toktype(tok)
        if typ == 'op':
            a,b = oq.pop(), oq.pop()
            oq.append([ tok, b, a])
        elif typ == 'monop':
            a = oq.pop()
            oq.append([ tok, a ])
        elif typ == 'fun':
            args = []
            #print functions[tok]
            for i in range(functions[tok]): args.insert(0,oq.pop())
            oq.append([ tok ] + args)
    while len(iq) > 0:
        prev = tok
        tok = iq.pop(0)
        typ = toktype(tok)
        if typ == 'alphanum': oq.append(tok)
        elif typ == 'lparen': stack.append(tok)
        elif typ == 'fun': stack.append(tok)
        elif typ == 'rparen':
            while len(stack) and stack[-1] != 'lparen': popstack(stack,oq)
            if len(stack):
                if toktype(stack[-1]) == 'fun': popstack(stack,oq)
                else: stack.pop()
        elif typ == 'monop' or typ == 'op':
            if tok == '-' and toktype(prev) not in [ 'alphanum', 'rparen' ]: oq.append('0')
            prec = precedence[tok]
            while len(stack) and toktype(stack[-1]) == 'op' and precedence[stack[-1]] < prec:
                popstack(stack,oq)
            stack.append(tok)
        #print 'iq',iq,'stack',stack,'oq',oq
    while len(stack):
        popstack(stack,oq)
    return oq[0]
                

def parse_line(ln):
    tokens = tokenize(ln)
    #print tokens
    if tokens[0] == 'if' or tokens[0] == 'while':
        return [ tokens[0], shunting_yard(tokens[1:]) ]
    elif len(tokens) >= 2 and tokens[0] == 'else' and tokens[1] == 'if':
        return [ 'else if', shunting_yard(tokens[2:]) ]
    elif len(tokens) == 1 and tokens[0] == 'else':
        return [ 'else' ]
    else:
        eqplace = tokens.index('=')
        return [ 'set', shunting_yard(tokens[:eqplace]), shunting_yard(tokens[eqplace+1:]) ]

optable = { 
    '+': 'ADD',
    '-': 'SUB',
    '*': 'MUL',
    '/': 'DIV',
    '^': 'EXP',
    '%': 'MOD',
    '#/': 'SDIV',
    '#%': 'SMOD',
    'SHA256': 'SHA256',
    'SHA3': 'SHA3',
    'RIPEMD160': 'RIPEMD160'
}

def compile_left_expr(expr,varhash):
    if isinstance(expr,str):
        if re.match('^[0-9\-]*$',expr):
            return ['PUSH',int(expr)]
        elif expr in varhash:
            return [varhash[expr]]
        else:
            varhash[expr] = len(varhash)
            return [varhash[expr]]
    else:
        raise Exception("invalid op: "+expr[0])

def compile_expr(expr,varhash):
    if isinstance(expr,str):
        if re.match('^[0-9\-]*$',expr):
            return ['PUSH',int(expr)]
        elif expr in varhash:
            return [varhash[expr],'MLOAD']
        else:
            varhash[expr] = len(varhash)
            return [varhash[expr],'MLOAD']
    elif expr[0] in optable:
        f = compile_expr(expr[1],varhash)
        g = compile_expr(expr[2],varhash)
        return f + g + [optable[expr[0]]]
    elif expr[0] == '!':
        f = compile_expr(expr[1],varhash)
        return f + ['NOT']
    elif expr[0] in ['or', '||']:
        return compile_expr(['!', [ '*', ['!', expr[1] ], ['!', expr[2] ] ] ],varhash)
    elif expr[0] in ['and', '&&']: 
        return compile_expr(['!', [ '+', ['!', expr[1] ], ['!', expr[2] ] ] ],varhash)
    else:
        raise Exception("invalid op: "+expr[0])


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
        return rexp + lexp + ['MSTORE']
    elif stmt[0] == 'seq':
        o = []
        for s in stmt[1:]: o.extend(compile_stmt(s,varhash,lc))
        return o

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
            oq.append(labelmap[m[4:]])
        else: oq.append(m)
    return oq

def compile(source):
    lines = source.split('\n')
    return assemble(compile_stmt(parse_lines(lines)))

if len(sys.argv) >= 2:
    print ' '.join([str(k) for k in compile(open(sys.argv[1]).read())])
