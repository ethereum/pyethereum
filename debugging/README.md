Create traces from tester file:

- with geth:
  1. start `gethrpctest`

    gethrpctest --json /home/konrad/Projects/rpc-tests/lib/tests/BlockchainTests/bcRPC_API_Test.json --test RPC_API_Test

  2. dump traces

    for i in {1..32};
        do curl -XPOST localhost:8545 -d \
            "{\"method\": \"debug_traceBlockByNumber\", \"jsonrpc\": \"2.0\", \
            \"params\": [$i, {}], \"id\": 110}" | python -mjson.tool > debugging/trace-$i.json;
    done
    
