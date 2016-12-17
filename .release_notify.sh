#!/usr/bin/env sh
PAYLOAD="{\"text\": \"<https://pypi.python.org/pypi/ethereum|ethereum $TRAVIS_TAG> was released on pypi!\"}"
curl -s -X POST --data-urlencode "payload=$PAYLOAD" $SLACK_WEBHOOK_URL

PAYLOAD="{\"attachments\":[{\"text\":\"[ethereum $TRAVIS_TAG](https://pypi.org/project/ethereum) was released on PyPI!\",\"color\":\"good\"}]}"
curl -s -X POST --data-urlencode "payload=$PAYLOAD" $ROCKETCHAT_URL
