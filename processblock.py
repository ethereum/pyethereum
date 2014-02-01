from transactions import Transaction
from blocks import Block
import time
import sys
import rlp
import math
import sha3

scriptcode_map = {
    0: 'STOP',   
    1: 'ADD',
    2: 'SUB',
    3: 'MUL',
    4: 'DIV',
    5: 'SDIV',
    6: 'MOD',
    7: 'SMOD',
    8: 'EXP',
    9: 'NEG',
    10: 'LT',
    11: 'LE',
    12: 'GT',
    13: 'GE',
    14: 'EQ',
    15: 'NOT',
    16: 'MYADDRESS',
    17: 'TXSENDER',
    18: 'TXVALUE',
    19: 'TXDATAN',
    20: 'TXDATA',
    21: 'BLK_PREVHASH',
    22: 'BLK_COINBASE',
    23: 'BLK_TIMESTAMP',
    24: 'BLK_NUMBER',
    25: 'BLK_DIFFICULTY',
    26: 'BASEFEE',
    32: 'SHA256',
    33: 'RIPEMD160',
    34: 'ECMUL',
    35: 'ECADD',
    36: 'ECSIGN',
    37: 'ECRECOVER',
    38: 'ECVALID',
    39: 'SHA3',
    48: 'PUSH',
    49: 'POP',
    50: 'DUP',
    51: 'SWAP',
    52: 'MLOAD',
    53: 'MSTORE',
    54: 'SLOAD',
    55: 'SSTORE',
    56: 'JMP',
    57: 'JMPI',
    58: 'IND',
    59: 'EXTRO',
    60: 'BALANCE',
    61: 'MKTX',
    63: 'SUICIDE'
}

params = {
    'stepfee': 1,
    'txfee': 100,
    'newcontractfee': 100,
    'storagefee': 0,
    'datafee': 20,
    'cryptofee': 20,
    'extrofee': 40,
    'blocktime': 60,
    'reward': 10 * 10**18
}

def getfee(block,t):
    if t in ['stepfee','txfee','newcontractfee','storagefee','datafee','cryptofee','extrofee']:
        return int(10**21 / int(block.difficulty ** 0.5)) * params[t]

def process_transactions(block,transactions):
    while len(transactions) > 0:
        tx = transactions.pop(0)
        enc = (tx.value, tx.fee, tx.sender.encode('hex'), tx.to.encode('hex'))
        sys.stderr.write("Attempting to send %d plus fee %d from %s to %s\n" % enc)
        # Grab data about sender, recipient and miner
        sdata = rlp.decode(block.state.get(tx.sender)) or [0,0,0]
        tdata = rlp.decode(block.state.get(tx.to)) or [0,0,0]
        # Calculate fee
        if tx.to == '\x00'*20:
            fee = getfee('newcontractfee')
        else:
            fee = getfee('txfee')
        # Insufficient fee, do nothing
        if fee > tx.fee:
            sys.stderr.write("Insufficient fee\n")
            continue
        # Too much data, do nothing
        if len(tx.data) > 256:
            sys.stderr.write("Too many data items\n")
            continue
        if not sdata or sdata[1] < tx.value + tx.fee:
            sys.stderr.write("Insufficient funds to send fee\n")
            continue
        elif tx.nonce != sdata[2] and sdata[0] == 0:
            sys.stderr.write("Bad nonce\n")
            continue
        # Try to send the tx
        if sdata[0] == 0: sdata[2] += 1
        sdata[1] -= (tx.value + tx.fee)
        block.reward += tx.fee
        if tx.to != '':
            tdata[1] += tx.value
        else:
            addr = tx.hash()[-20:]
            adata = rlp.decode(block.state.get(addr))
            if adata[2] != '':
                sys.stderr.write("Contract already exists\n")
                continue
            block.state.update(addr,rlp.encode([1,tx.value,'']))
            contract = block.get_contract(addr)
            for i in range(len(tx.data)):
                contract.update(encode(i,256,32),tx.data[i])
            block.update_contract(addr)
        print sdata, tdata
        block.state.update(tx.sender,rlp.encode(sdata))
        block.state.update(tx.to,rlp.encode(tdata))
        # Evaluate contract if applicable
        if tdata[0] == 1:
            eval_contract(block,transactions,tx)
        sys.stderr.write("tx processed\n")

def eval(block,transactions,timestamp,coinbase):
    h = block.hash()
    # Process all transactions
    process_transactions(block,transactions)
    # Pay miner fee
    miner_state = rlp.decode(block.state.get(block.coinbase)) or [0,0,0]
    block.number += 1
    reward = params['reward']
    miner_state[1] += reward
    for uncle in block.uncles:
        sib_miner_state = rlp_decode(block.state.get(uncle[3]))
        sib_miner_state[1] += reward*7/8
        block.state.update(uncle[3],sib_miner_state)
        miner_state[1] += reward/8
    block.state.update(block.coinbase,rlp.encode(miner_state))
    # Check timestamp
    if timestamp < block.timestamp or timestamp > int(time.time()) + 3600:
        raise Exception("timestamp not in valid range!")
    # Update difficulty
    if timestamp >= block.timestamp + 42:
        block.difficulty += int(block.difficulty / 1024)
    else:
        block.difficulty -= int(block.difficulty / 1024)
    block.prevhash = h
    block.coinbase = coinbase
    block.transactions = []
    block.uncles = []
    return block

def eval_contract(block,transaction_list,tx):
    sys.stderr.write("evaluating contract\n")
    address = tx.to
    # Initialize stack
    stack = []
    index = 0
    stepcounter = 0
    contract = block.get_contract(address)
    if not contract:
        return
    while 1:
        # Convert the data item into a code piece
        val_at_index = decode(contract.get(encode(index,256,32)),256)
        code = [ int(val_at_index / (256**i)) % 256 for i in range(6) ]
        code[0] = scriptcode_map.get(code[0],'INVALID')
        sys.stderr.write("Evaluating: "+ str(code)+"\n")
        # Invalid code instruction or STOP code stops execution sans fee
        if val_at_index >= 256 or code[0] in ['STOP','INVALID']:
            sys.stderr.write("stop code, exiting\n")
            break
        # Calculate fee
        minerfee = 0
        nullfee = 0
        stepcounter += 1
        if stepcounter > 16:
            minerfee += getfee("stepfee")
        c = scriptcode_map[code[0]]
        if c in ['STORE','LOAD']:
            minerfee += getfee("datafee")
        if c in ['EXTRO','BALANCE']:
            minerfee += getfee("extrofee")
        if c in ['SHA256','RIPEMD-160','ECMUL','ECADD','ECSIGN','ECRECOVER']:
            minerfee += getfee("cryptofee")
        if c == 'STORE':
            existing = block.get_contract_state(address,code[2])
            if reg[code[1]] != 0: nullfee += getfee("memoryfee")
            if existing: nullfee -= getfee("memoryfee")

        # If we can't pay the fee, break, otherwise pay it
        if block.get_balance(address) < minerfee + nullfee:
            sys.stderr.write("insufficient fee, exiting\n")
            break
        block.set_balance(address,block.get_balance(address) - nullfee - minerfee)
        block.reward += minerfee
        sys.stderr.write("evaluating operation\n") 
        exit = False
        def stack_pop(n):
            if len(stack) < n:
                sys.stderr.write("Stack height insufficient, exiting")
                exit = True
                return [0] * n
            o = stack[-n:]
            stack = stack[:-n]
            return o
        # Evaluate operations
        if c == 'ADD':
            x,y = stack_pop(2)
            stack.append((x + y) % 2**256)
        elif c == 'MUL':
            x,y = stack_pop(2)
            stack.append((x * y) % 2**256)
        elif c == 'SUB':
            x,y = stack_pop(2)
            stack.append((x - y) % 2**256)
        elif c == 'DIV':
            x,y = stack_pop(2)
            if y == 0: break
            stack.append(int(x / y))
        elif c == 'SDIV':
            x,y = stack_pop(2)
            if y == 0: break
            sign = (1 if x < 2**255 else -1) * (1 if y < 2**255 else -1)
            xx = x if x < 2**255 else 2**256 - x
            yy = y if y < 2**255 else 2**256 - y
            z = int(xx/yy)
            stack.append(z if sign == 1 else 2**256 - z)
        elif code == 'MOD':
            x,y = stack_pop(2)
            if y == 0: break
            stack.append(x % y)
        elif code == 'SMOD':
            x,y = stack_pop(2)
            if y == 0: break
            sign = (1 if x < 2**255 else -1) * (1 if y < 2**255 else -1)
            xx = x if x < 2**255 else 2**256 - x
            yy = y if y < 2**255 else 2**256 - y
            z = xx%yy
            stack.append(z if sign == 1 else 2**256 - z)
        elif code == 'EXP':
            x,y = stack_pop(2)
            stack.append(pow(x,y,2**256))
        elif code == 'NEG':
            stack.append(2**256 - stack.pop(1)[0])
        elif code == 'LT':
            x,y = stack_pop(2)
            stack.append(1 if x < y else 0)
        elif code == 'LE':
            x,y = stack_pop(2)
            stack.append(1 if x <= y else 0)
        elif code == 'GT':
            x,y = stack_pop(2)
            stack.append(1 if x > y else 0)
        elif code == 'GE':
            x,y = stack_pop(2)
            stack.append(1 if x >= y else 0)
        elif code == 'EQ':
            x,y = stack_pop(2)
            stack.append(1 if x == y else 0)
        elif code == 'NOT':
            stack.append(1 if stack.pop(1)[0] == 0 else 0)
        elif code == 'MYADDRESS':
            stack.append(address)
        elif code == 'TXSENDER':
            stack.append(decode(tx.sender,256))
        elif code == 'TXVALUE':
            stack.append(tx.value)
        elif code == 'TXDATAN':
            stack.append(len(tx.data))
        elif code == 'TXDATA':
            x, = stack_pop(1)
            stack.append(0 if x >= len(tx.data) else tx.data[x])
        elif code == 'BLK_PREVHASH':
            stack.append(decode(block.prevhash,256))
        elif code == 'BLK_COINBASE':
            stack.append(decode(block.coinbase,160))
        elif code == 'BLK_TIMESTAMP':
            stack.append(block.timestamp)
        elif code == 'BLK_NUMBER':
            stack.append(block.number)
        elif code == 'BLK_DIFFICULTY':
            stack.append(block.difficulty)
        elif code == 'SHA256':
            L = stack_pop(1)
            hdataitems = stack_pop(math.ceil(L / 32.0))
            hdata = ''.join([encode(x,256,32) for x in hdataitems])[:L]
            stack.append(decode(hashlib.sha256(hdata).digest(),256))
        elif code == 'RIPEMD-160':
            L = stack_pop(1)
            hdataitems = stack_pop(math.ceil(L / 32.0))
            hdata = ''.join([encode(x,256,32) for x in hdataitems])[:L]
            stack.append(decode(hashlib.new('ripemd160',hdata).digest(),256))
        elif code == 'ECMUL':
            n,x,y = stack_pop(3)
            # Point at infinity
            if x == 0 and y == 0:
                stack.extend([0,0])
            # Point not on curve, coerce to infinity
            elif x >= P or y >= P or (x ** 3 + 7 - y ** 2) % P != 0:
                stack.extend([0,0])
            # Legitimate point
            else:
                x2,y2 = base10_multiply((x,y),n)
                stack.extend([x2,y2])
        elif code == 'ECADD':
            x1,y1,x2,y2 = stack_pop(4)
            # Invalid point 1
            if x1 >= P or y1 >= P or (x1 ** 3 + 7 - y1 ** 2) % P != 0:
                stack.extend([0,0])
            # Invalid point 2
            elif x2 >= P or y2 >= P or (x2 ** 3 + 7 - y2 ** 2) % P != 0:
                stack.extend([0,0])
            # Legitimate points
            else:
                x3,y3 = base10_add((x1,y1),(x2,y2))
                stack.extend([x3,y3])
        elif code == 'ECSIGN':
            k,h = stack_pop(2)
            v,r,s = ecdsa_raw_sign(h,k)
            stack.extend([v,r,s])
        elif code == 'ECRECOVER':
            h,v,r,s = stack_pop(4)
            x,y = ecdsa_raw_recover((v,r,s),h)
            stack.extend([x,y])
        elif code == 'SHA3':
            L = stack_pop(1)
            hdataitems = stack_pop(math.ceil(L / 32.0))
            hdata = ''.join([encode(x,256,32) for x in hdataitems])[:L]
            stack.append(decode(sha3.sha3_256(hdata).digest(),256))
        elif code == 'PUSH':
            stack.append(contract.get(encode(index + 1,256,32)))
            index += 1
        elif code == 'POP':
            stack_pop(1)
        elif code == 'DUP':
            x, = stack_pop(1)
            stack.extend([x,x])
        elif code == 'SWAP':
            x,y = stack_pop(2)
            stack.extend([y,x])
        elif code == 'SLOAD':
            stack.append(contract.get(encode(stack_pop(1)[0],256,32)))
        elif code == 'SSTORE':
            x,y = stack_pop(2)
            if exit: break
            contract.update(encode(x,256,32),y)
        elif code == 'JMP':
            index = stack_pop(1)[0]
        elif code == 'JMPI':
            newpos,c = stack_pop(2)
            if c != 0: index = newpos
        elif code == 'IND':
            stack.append(index)
        elif code == 'EXTRO':
            ind,addr = stack_pop(2)
            stack.push(block.get_contract(encode(addr,256,20)).get(encode(ind,256,32)))
        elif code == 'BALANCE':
            stack.push(block.get_balance(encode(stack_pop(1)[0],256,20)))
        elif code == 'MKTX':
            datan,fee,value,to = stack_pop(4)
            if exit:
                break
            elif (value + fee) > block.get_balance(address):
                break
            else:
                data = stack_pop(datan)
                tx = Transaction(0,encode(to,256,20),value,fee,data)
                tx.sender = address
                transaction_list.insert(0,tx)
        elif code == 'SUICIDE':
            sz = contract.get_size()
            negfee = -sz * getfee("memoryfee")
            toaddress = encode(stack_pop(1)[0],256,20)
            block.pay_fee(toaddress,negfee,False)
            contract.root = ''
            break
        if exit: break
    block.update_contract(address,contract)
