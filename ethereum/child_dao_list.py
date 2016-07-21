from ethereum.utils import mk_contract_address, encode_hex
source = '0x4a574510c7014e4ae985403536074abe582adfc8'

L = []
# DAO
L.append('0xbb9bc244d798123fde783fcc1c72d3bb8c189413')
# DAO extrabalance
L.append('0x807640a13483f8ac783c557fcdf27be11ea4ac7a')
# child DAOs (created by DAO creator)
L.extend([b'0x' + encode_hex(mk_contract_address(source, i)) for i in range(1, 58)])
# child extrabalances
L.extend([b'0x' + encode_hex(mk_contract_address(mk_contract_address(source, i), 0)) for i in range(1, 58)])
