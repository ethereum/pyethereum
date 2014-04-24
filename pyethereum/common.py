import threading
import logging

logger = logging.getLogger(__name__)


class StoppableLoopThread(threading.Thread):

    def __init__(self):
        super(StoppableLoopThread, self).__init__()
        self._stopped = False
        self.lock = threading.Lock()

    def stop(self):
        with self.lock:
            self._stopped = True
        logger.debug(
            'Thread {0} is requested to stop'.format(self))

    def stopped(self):
        with self.lock:
            return self._stopped

    def pre_loop(self):
        logger.debug('Thread {0} start to run'.format(self))

    def post_loop(self):
        logger.debug('Thread {0} stopped'.format(self))

    def run(self):
        self.pre_loop()
        while not self.stopped():
            self.loop_body()
        self.post_loop()

    def loop_body(self):
        raise Exception('Not Implemented')
