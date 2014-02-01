import cllcompiler
t = open('tests.txt').readlines()
i = 0
while 1:
    o = []
    while i < len(t) and (not len(t[i]) or t[i][0] != '='): 
        o.append(t[i])
        i += 1
    i += 1
    print '================='
    text = '\n'.join(o).replace('\n\n','\n')
    print text
    ast = cllcompiler.parse_lines(o)
    print "AST:",ast
    print ""
    code = cllcompiler.assemble(cllcompiler.compile_stmt(ast))
    print "Output:",' '.join([str(x) for x in code])
    if i >= len(t):
        break
