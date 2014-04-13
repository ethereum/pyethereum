import threading


class StoppableLoopThread(threading.Thread):
    def __init__(self):
        super(StoppableLoopThread, self).__init__()
        self._stopped = False
        self.lock = threading.Lock()

    def stop(self):
        with self.lock:
            self._stopped = True

    def stopped(self):
        with self.lock:
            return self._stopped

    def run(self):
        while not self.stopped():
            self.loop_body()

    def loop_body(self):
        pass
