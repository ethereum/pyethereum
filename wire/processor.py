import json
import Queue as queue
import socket
import threading
import time
import traceback
import sys

from utils import random_string, timestr, print_log


class Shared:

    def __init__(self, config):
        self.lock = threading.Lock()
        self._stopped = False
        self.config = config

    def stop(self):
        print_log("Stopping Server")
        with self.lock:
            self._stopped = True

    def stopped(self):
        with self.lock:
            return self._stopped


class Processor(threading.Thread):

    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        self.dispatcher = None
        self.queue = queue.Queue()

    def process(self, session, request):
        pass

    def add_request(self, session, request):
        self.queue.put((session, request))

    def push_response(self, session, response):
        #print "response", response
        self.dispatcher.request_dispatcher.push_response(session, response)

    def close(self):
        pass

    def run(self):
        while not self.shared.stopped():
            try:
                request, session = self.queue.get(True, timeout=1)
            except:
                continue
            try:
                self.process(request, session)
            except:
                traceback.print_exc(file=sys.stdout)

        self.close()


class Dispatcher:

    def __init__(self, config):
        self.shared = Shared(config)
        self.request_dispatcher = RequestDispatcher(self.shared)
        self.request_dispatcher.start()
        self.response_dispatcher = \
            ResponseDispatcher(self.shared, self.request_dispatcher)
        self.response_dispatcher.start()

    def register(self, prefix, processor):
        processor.dispatcher = self
        processor.shared = self.shared
        processor.start()
        self.request_dispatcher.processors[prefix] = processor


class RequestDispatcher(threading.Thread):

    def __init__(self, shared):
        self.shared = shared
        threading.Thread.__init__(self)
        self.daemon = True
        self.request_queue = queue.Queue()
        self.response_queue = queue.Queue()
        self.lock = threading.Lock()
        self.idlock = threading.Lock()
        self.sessions = {}
        self.processors = {}

    def push_response(self, session, item):
        self.response_queue.put((session, item))

    def pop_response(self):
        return self.response_queue.get()

    def push_request(self, session, item):
        self.request_queue.put((session, item))

    def pop_request(self):
        return self.request_queue.get()

    def get_session_by_address(self, address):
        for x in self.sessions.values():
            if x.address == address:
                return x

    def run(self):
        if self.shared is None:
            raise TypeError("self.shared not set in Processor")

        lastgc = 0 

        while not self.shared.stopped():
            session, request = self.pop_request()
            try:
                self.do_dispatch(session, request)
            except:
                traceback.print_exc(file=sys.stdout)

            if time.time() - lastgc > 60.0:
                self.collect_garbage()
                lastgc = time.time()

        self.stop()

    def stop(self):
        pass

    def do_dispatch(self, session, request):
        """ dispatch request to the relevant processor """

        print 'do_dispatch', session, request


        method = request['method']
        params = request.get('params', [])
        suffix = method.split('.')[-1]

        if session is not None:
            if suffix == 'subscribe':
                session.subscribe_to_service(method, params)

        prefix = request['method'].split('.')[0]
        try:
            p = self.processors[prefix]
        except:
            print_log("error: no processor for", prefix)
            return

        p.add_request(session, request)

        if method in ['server.version']:
            try:
                session.version = params[0]
                session.protocol_version = float(params[1])
            except:
                pass


    def get_sessions(self):
        with self.lock:
            r = self.sessions.values()
        return r

    def add_session(self, session):
        key = session.key()
        with self.lock:
            self.sessions[key] = session

    def remove_session(self, session):
        key = session.key()
        with self.lock:
            self.sessions.pop(key)

    def collect_garbage(self):
        now = time.time()
        for session in self.sessions.values():
            if (now - session.time) > session.timeout:
                session.stop()



class Session:

    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        #self.bp = self.dispatcher.processors['blockchain']
        self._stopped = False
        self.lock = threading.Lock()
        self.subscriptions = []
        self.address = ''
        self.name = ''
        self.version = 'unknown'
        self.protocol_version = 0.
        self.time = time.time()
        threading.Timer(2, self.info).start()


    def key(self):
        return self.name + self.address


    # Debugging method. Doesn't need to be threadsafe.
    def info(self):
        for sub in self.subscriptions:
            #print sub
            method = sub[0]
            if method == 'blockchain.address.subscribe':
                addr = sub[1]
                break
        else:
            addr = None

        if self.subscriptions:
            print_log("%4s" % self.name,
                      "%15s" % self.address,
                      "%35s" % addr,
                      "%3d" % len(self.subscriptions),
                      self.version)

    def stop(self):
        with self.lock:
            if self._stopped:
                return
            self._stopped = True

        self.shutdown()
        self.dispatcher.remove_session(self)
        self.stop_subscriptions()


    def shutdown(self):
        pass


    def stopped(self):
        with self.lock:
            return self._stopped


    def subscribe_to_service(self, method, params):
        with self.lock:
            if self._stopped:
                return
            if (method, params) not in self.subscriptions:
                self.subscriptions.append((method,params))
        #self.bp.do_subscribe(method, params, self)


    def stop_subscriptions(self):
        with self.lock:
            s = self.subscriptions[:]
        for method, params in s:
            #self.bp.do_unsubscribe(method, params, self)
            pass
        with self.lock:
            self.subscriptions = []


class ResponseDispatcher(threading.Thread):

    def __init__(self, shared, request_dispatcher):
        self.shared = shared
        self.request_dispatcher = request_dispatcher
        threading.Thread.__init__(self)
        self.daemon = True

    def run(self):
        while not self.shared.stopped():
            session, response = self.request_dispatcher.pop_response()
            session.send_response(response)
