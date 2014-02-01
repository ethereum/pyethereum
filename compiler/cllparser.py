import re

# Number of spaces at the beginning of a line
def spaces(ln):
    spaces = 0
    while spaces < len(ln) and ln[spaces] == ' ': spaces += 1
    return spaces

# Parse the statement-level structure, including if and while statements
def parse_lines(lns):
    o = []
    i = 0
    while i < len(lns):
        main = lns[i]
        # Skip empty lines
        if len(main.strip()) == 0:
            i += 1
            continue
        if spaces(main) > 0:
            raise Exception("Line "+str(i)+" indented too much!")
        # Grab the child block
        start_child_block = i+1
        spacesmin = 99999999
        i += 1
        while i < len(lns):
            sp = spaces(lns[i])
            if sp == 0: break
            spacesmin = min(sp,spacesmin)
            i += 1
        child_block = map(lambda x:x[spacesmin:],lns[start_child_block:i])
        # Calls parse_line to parse the individual line
        out = parse_line(main)
        # Include the child block into the parsed expression
        if out[0] in ['if', 'else', 'while', 'else if']:
            if len(child_block) == 0:
                raise Exception("If/else/while statement must have sub-clause! (%d)" % i)
            else:
                out.append(parse_lines(child_block))
        else:
            if len(child_block) > 0:
                raise Exception("Not an if/else/while statement, can't have sub-clause! (%d)" % i)
        # This is somewhat complicated. Essentially, it converts something like
        # "if c1 then s1 elif c2 then s2 elif c3 then s3 else s4" (with appropriate
        # indenting) to [ if c1 s1 [ if c2 s2 [ if c3 s3 s4 ] ] ]
        if out[0] == 'else if':
            if len(o) == 0: raise Exception("Cannot start with else if! (%d)" % i)
            u = o[-1]
            while len(u) == 4: u = u[-1]
            u.append(['if'] + out[1:])
        elif out[0] == 'else':
            if len(o) == 0: raise Exception("Cannot start with else! (%d)" % i)
            u = o[-1]
            while len(u) == 4: u = u[-1]
            u.append(out[1])
        else:
            # Normal case: just add the parsed line to the output
            o.append(out)
    return o[0] if len(o) == 1 else ['seq'] + o

# Converts something like "b[4] = x+2 > y*-3" to
# [ 'b', '[', '4', ']', '=', 'x', '+', '2', '>', 'y', '*', '-', '3' ]
def chartype(c):
    if c in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.':
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

# This is the part where we turn a token list into an abstract syntax tree
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
    '&&': 6,
    'or': 7,
    '||': 7,
}

def toktype(token):
    if token is None: return None
    elif token in ['(','[']: return 'lparen'
    elif token in [')',']']: return 'rparen'
    elif token == ',': return 'comma'
    elif token in ['!']: return 'monop' 
    elif not isinstance(token,str): return 'compound'
    elif token in precedence: return 'op'
    elif re.match('^[0-9a-z\-\.]*$',token): return 'alphanum'
    else: raise Exception("Invalid token: "+token)

# https://en.wikipedia.org/wiki/Shunting-yard_algorithm
def shunting_yard(tokens):
    iq = [x for x in tokens]
    oq = []
    stack = []
    prev,tok = None,None
    # The normal Shunting-Yard algorithm simply converts expressions into
    # reverse polish notation. Here, we try to be slightly more ambitious
    # and build up the AST directly on the output queue
    # eg. say oq = [ 2, 5, 3 ] and we add "+" then "*"
    # we get first [ 2, [ +, 5, 3 ] ] then [ *, 2, [ +, 5, 3 ] ]
    def popstack(stack,oq):
        tok = stack.pop()
        typ = toktype(tok)
        if typ == 'op':
            a,b = oq.pop(), oq.pop()
            oq.append([ tok, b, a])
        elif typ == 'monop':
            a = oq.pop()
            oq.append([ tok, a ])
        elif typ == 'rparen':
            args = []
            while toktype(oq[-1]) != 'lparen': args.insert(0,oq.pop())
            oq.pop()
            if tok == ']':
                oq.append(['access'] + args)
            elif tok == ')' and len(args) and args[0] != 'id':
                oq.append(['fun'] + args)
            else:
                oq.append(args[1])
    # The main loop
    while len(iq) > 0:
        prev = tok
        tok = iq.pop(0)
        typ = toktype(tok)
        if typ == 'alphanum':
            oq.append(tok)
        elif typ == 'lparen':
            if toktype(prev) != 'alphanum': oq.append('id')
            stack.append(oq.pop())
            oq.append(tok)
            oq.append(stack.pop())
            stack.append(tok)
        elif typ == 'rparen':
            while len(stack) and toktype(stack[-1]) != 'lparen':
                popstack(stack,oq)
            if len(stack):
                stack.pop()
            stack.append(tok)
            popstack(stack,oq)
        elif typ == 'monop' or typ == 'op':
            if tok == '-' and toktype(prev) not in [ 'alphanum', 'rparen' ]:
                oq.append('0')
            prec = precedence[tok]
            while len(stack) and toktype(stack[-1]) == 'op' and precedence[stack[-1]] < prec:
                popstack(stack,oq)
            stack.append(tok)
        elif typ == 'comma':
            while len(stack) and stack[-1] != 'lparen': popstack(stack,oq)
        #print 'iq',iq,'stack',stack,'oq',oq
    while len(stack):
        popstack(stack,oq)
    if len(oq) == 1:
        return oq[0]
    else:
        return [ 'multi' ] + oq

def parse_line(ln):
    tokens = tokenize(ln)
    if tokens[0] == 'if' or tokens[0] == 'while':
        return [ tokens[0], shunting_yard(tokens[1:]) ]
    elif len(tokens) >= 2 and tokens[0] == 'else' and tokens[1] == 'if':
        return [ 'else if', shunting_yard(tokens[2:]) ]
    elif len(tokens) >= 1 and tokens[0] == 'elif':
        return [ 'else if', shunting_yard(tokens[1:]) ]
    elif len(tokens) == 1 and tokens[0] == 'else':
        return [ 'else' ]
    elif tokens[0] in ['mktx','suicide','stop']:
        return shunting_yard(tokens)
    else:
        eqplace = tokens.index('=')
        pre = 0
        i = 0
        while i < eqplace:
            try: nextcomma = i + tokens[i:].index(',')
            except: nextcomma = eqplace
            pre += 1
            i = nextcomma+1
        if pre == 1:
            return [ 'set', shunting_yard(tokens[:eqplace]), shunting_yard(tokens[eqplace+1:]) ]
        else:
            return [ 'mset', shunting_yard(tokens[:eqplace]), shunting_yard(tokens[eqplace+1:]) ]
