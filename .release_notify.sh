#!/usr/bin/env sh
PAYLOAD="{\"text\": \"<https://pypi.python.org/pypi/ethereum|ethereum $TRAVIS_TAG> was released on pypi!\"}"
curl -s -X POST --data-urlencode "payload=$PAYLOAD" $SLACK_WEBHOOK_URL

PAYLOAD="{\"text\": \"[ethereum $TRAVIS_TAG](https://pypi.org/project/ethereum) was released on PyPI!\"}"
curl -s -X POST --data-urlencode "payload=$PAYLOAD" $ROCKETCHAT_URL
