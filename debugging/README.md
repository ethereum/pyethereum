Create traces from tester file:

- with geth:
  1. start `gethrpctest`

    gethrpctest --json tests/BlockchainTests/bcRPC_API_Test.json --test RPC_API_Test

  2. dump traces

    for i in {1..32};
        do curl -XPOST localhost:8545 -d \
            "{\"method\": \"debug_traceBlockByNumber\", \"jsonrpc\": \"2.0\", \
            \"params\": [$i, {}], \"id\": 110}" | python -mjson.tool > debugging/trace-$i.json;
    done
    
- with pyethapp

    pyethapp --log-json -d /tmp/bt -l:trace blocktest \
    tests/BlockchainTests/bcRPC_API_Test.json RPC_API_Test 2>&1 | grep "eth.vm.op"|while IFS=$'\n' read -r line; \
    do python -mjson.tool <<<"$line"; done
