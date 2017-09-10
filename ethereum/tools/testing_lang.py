import re

class TestLang:
    def __init__(self, test=""):
        self.test = test

    def parse(self):
        for token in self.test.split(' '):
            letters, numbers = re.match('([A-Za-z]*)([0-9]*)', token).groups()
            if letters+numbers != token:
                raise Exception("Bad token: %s" % token)
            if numbers != '':
                numbers = int(numbers)
