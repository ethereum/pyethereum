import threading
import logging

logger = logging.getLogger(__name__)


class StoppableLoopThread(threading.Thread):
    def __init__(self):
        super(StoppableLoopThread, self).__init__()
        self._stopped = False
        self.lock = threading.Lock()

    def thread_name(self):
        return self.__class__

    def stop(self):
        with self.lock:
            self._stopped = True
        logger.debug(
            'Thread {0} is requested to stop'.format(self.thread_name()))

    def stopped(self):
        with self.lock:
            return self._stopped

    def run(self):
        logger.debug('Thread {0} start to run'.format(self.thread_name()))
        while not self.stopped():
            self.loop_body()
        logger.debug('Thread {0} stopped'.format(self.thread_name()))

    def loop_body(self):
        pass
