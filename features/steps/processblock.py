from pyethereum import transactions, blocks, processblock, utils

@given(u'a block')
def step_impl(context):
    context.key = utils.sha3('cows')
    context.addr = utils.privtoaddr(context.key)
    context.gen = blocks.genesis({context.addr: 10**60})

@given(u'a contract which returns the result of the SHA3 opcode')
def step_impl(context):
    '''
    serpent: 'return(sha3(msg.data[0]))'
    assembly: ['$begincode_0.endcode_0', 'DUP', 'MSIZE', 'SWAP', 'MSIZE', '$begincode_0', 'CALLDATACOPY', 'RETURN', '~begincode_0', '#CODE_BEGIN', 32, 'MSIZE', 0L, 'CALLDATALOAD', 'MSIZE', 'MSTORE', 'SHA3', 'MSIZE', 'SWAP', 'MSIZE', 'MSTORE', 32, 'SWAP', 'RETURN', '#CODE_END', '~endcode_0']
     byte code: 6011515b525b600a37f260205b6000355b54205b525b54602052f2
    '''
    code = '6011515b525b600a37f260205b6000355b54205b525b54602052f2'.decode('hex')

    tx_contract = transactions.contract(0,10,10**30, 10**30, code).sign(context.key)
    success, context.contract = processblock.apply_transaction(context.gen, tx_contract)
    assert(success)


@when(u'a msg is sent to the contract with msg.data[0] = \'hello\'')
def step_impl(context):
    word = 'hello'
    msg = context.msg = '\x00'*(32-len(word))+word
    tx = transactions.Transaction(1, 100, 10**40, context.contract, 0, msg).sign(context.key)
    success, context.ans = processblock.apply_transaction(context.gen, tx)
    assert(success)


@when(u'a msg is sent to the contract with msg.data[0] = 342156')
def step_impl(context):
    word = 342156
    word = hex(word)[2:]
    if len(word)%2 != 0: word = '0' + word
    msg = context.msg = '\x00'*(32-len(word)/2)+word.decode('hex')
    tx = transactions.Transaction(1, 100, 10**40, context.contract, 0, msg).sign(context.key)
    success, context.ans = processblock.apply_transaction(context.gen, tx)
    assert(success)

@when(u'a msg is sent to the contract with msg.data[0] = \'a5b2cc1f54\'')
def step_impl(context):
    word = 'a5b2cc1f54'
    msg = context.msg = '\x00'*(32-len(word))+word
    tx = transactions.Transaction(1, 100, 10**40, context.contract, 0, msg).sign(context.key)
    success, context.ans = processblock.apply_transaction(context.gen, tx)
    assert(success)

@then(u'the contract should return the result of sha3(msg.data[0])')
def step_impl(context):
    assert (context.ans == utils.sha3(context.msg))
