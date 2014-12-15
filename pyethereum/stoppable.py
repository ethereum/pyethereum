import threading
from pyethereum.slogging import get_logger
log = get_logger('net')


class StoppableLoopThread(threading.Thread):

    def __init__(self):
        super(StoppableLoopThread, self).__init__()
        self._stopped = False
        self.lock = threading.Lock()

    def stop(self):
        with self.lock:
            self._stopped = True
        log.debug('Thread is requested to stop', name=self)

    def stopped(self):
        with self.lock:
            return self._stopped

    def pre_loop(self):
        log.debug('Thread start to run', name=self)

    def post_loop(self):
        log.debug('Thread stopped', name=self)

    def run(self):
        self.pre_loop()
        while not self.stopped():
            self.loop_body()
        self.post_loop()

    def loop_body(self):
        raise Exception('Not Implemented')
