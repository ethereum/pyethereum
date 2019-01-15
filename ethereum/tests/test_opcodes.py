from ethereum import opcodes

opcode_gas = {
    opcode: gas for (opcode, ins, outs, gas) in opcodes.opcodes.values()
}


def test_eip150_opcode_gascost():
    """Ensure gas prices specified in
    https://github.com/ethereum/eips/issues/150
    """
    assert opcode_gas['EXTCODESIZE'] + \
        opcodes.EXTCODELOAD_SUPPLEMENTAL_GAS == 700
    assert opcode_gas['EXTCODECOPY'] + \
        opcodes.EXTCODELOAD_SUPPLEMENTAL_GAS == 700
    assert opcode_gas['BALANCE'] + opcodes.BALANCE_SUPPLEMENTAL_GAS == 400
    assert opcode_gas['SLOAD'] + opcodes.SLOAD_SUPPLEMENTAL_GAS == 200

    assert opcode_gas['CALL'] + opcodes.CALL_SUPPLEMENTAL_GAS == 700
    assert opcode_gas['DELEGATECALL'] + opcodes.CALL_SUPPLEMENTAL_GAS == 700
    assert opcode_gas['CALLCODE'] + opcodes.CALL_SUPPLEMENTAL_GAS == 700

    assert opcode_gas['SUICIDE'] + opcodes.SUICIDE_SUPPLEMENTAL_GAS == 5000
