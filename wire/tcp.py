import json
import Queue as queue
import socket
import threading
import time
import traceback, sys

from processor import Session, Dispatcher
from utils import print_log


class TcpSession(Session):

    def __init__(self, dispatcher, connection, address):
        Session.__init__(self, dispatcher)
        self._connection = connection
        self.address = address[0] + ":%d"%address[1]
        self.name = "TCP "
        self.timeout = 1000
        self.response_queue = queue.Queue()
        self.dispatcher.add_session(self)

    def do_handshake(self):
        pass

    def connection(self):
        if self.stopped():
            raise Exception("Session was stopped")
        else:
            return self._connection

    def shutdown(self):
        try:
            self._connection.shutdown(socket.SHUT_RDWR)
        except:
            # print_log("problem shutting down", self.address)
            # traceback.print_exc(file=sys.stdout)
            pass

        self._connection.close()

    def send_response(self, response):
        self.response_queue.put(response)


class TcpClientResponder(threading.Thread):

    def __init__(self, session):
        self.session = session
        threading.Thread.__init__(self)

    def run(self):
        while not self.session.stopped():
            try:
                data = self.session.response_queue.get(timeout=10)
            except queue.Empty:
                continue
            try:
                while data:
                    l = self.session.connection().send(data)
                    data = data[l:]
            except:
                self.session.stop()



class TcpClientRequestor(threading.Thread):

    def __init__(self, dispatcher, session):
        self.shared = dispatcher.shared
        self.dispatcher = dispatcher
        self.message = ""
        self.session = session
        threading.Thread.__init__(self)

    def run(self):
        try:
            self.session.do_handshake()
        except:
            self.session.stop()
            return

        while not self.shared.stopped():

            data = self.receive()
            if not data:
                self.session.stop()
                break

            self.message += data
            self.session.time = time.time()

            while self.parse():
                pass


    def receive(self):
        try:
            return self.session.connection().recv(2048)
        except:
            return ''

    def parse(self):
        import rlp
        import struct

        print  'message %r' % self.message

        magic_token = struct.pack('>i', 0x22400891)

        assert self.message[:4] == magic_token
        size = struct.unpack('>i',self.message[4:8])[0]

        print 'len message:%d len payload:%d' %(len(self.message), size)

        data = rlp.decode(self.message[8:8+size])

        print data

        response = 'winkewinke'

        response = '"@\x08\x91\x00\x00\x00t\xf8r\x80\x08\x80\xa8Ethereum(++)/v0.3.11/brew/Darwin/unknown\x07\x82v_\xb8@j\x99\x1e\xf0r\xad\r\x88h9\xc1|t\xa0-V\xec\nH.\xdc\xac\xcb\x8a\xe3\xd8\x92\x95\xfaU\x1bu<\xc36\xb3\xa4\x92\xade\xb7b\xf4\x1co\xcc\x98\x8f\xe5"24\x01f\x19\x14\xb1\xd3`\x1a6\x92\xd7\xdb'
        self.dispatcher.push_response(self.session, response)

        return True
"""        

        for i in range(len(self.message)):
            print i, rlp.decode(self.message[i:])


        raw_buffer = self.message.find('\n')
        if raw_buffer == -1:
            return False

        raw_command = self.message[0:raw_buffer].strip()
        self.message = self.message[raw_buffer + 1:]
        if raw_command == 'quit':
            self.session.stop()
            return False

        try:
            command = json.loads(raw_command)
        except:
            self.dispatcher.push_response(self.session, {"error": "bad JSON", "request": raw_command})
            return True

        try:
            # Try to load vital fields, and return an error if
            # unsuccessful.
            message_id = command['id']
            method = command['method']
        except KeyError:
            # Return an error JSON in response.
            self.dispatcher.push_response(self.session, {"error": "syntax error", "request": raw_command})
        else:
            self.dispatcher.push_request(self.session, command)
            # sleep a bit to prevent a single session from DOSing the queue
            time.sleep(0.01)

        return True
"""


"""
TCPClient




"""


class TcpClient(threading.Thread):
    def __init__(self, dispatcher, host, port):
        self.shared = dispatcher.shared
        self.dispatcher = dispatcher.request_dispatcher
        threading.Thread.__init__(self)
        self.daemon = True
        self.host = host
        self.port = port
        self.lock = threading.Lock()

    def connect(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        #sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        sock.connect((self.host, self.port))
    
        try:
            session = TcpSession(self.dispatcher, connection, address)
            print_log("New TCP Connection", connection, address)
        except BaseException, e:
            error = str(e)
            print_log("cannot start TCP session", error, address)
            connection.close()

            client_req = TcpClientRequestor(self.dispatcher, session)
            client_req.start()
            responder = TcpClientResponder(session)
            responder.start()


        
    def run(self):
        print_log( ("TCP") + " client started connecting %r" % (self.host, self.port))
    
        while not self.shared.stopped():

            time.sleep(0.1)
                continue

class TcpServer(threading.Thread):

    def __init__(self, dispatcher, host, port):
        self.shared = dispatcher.shared
        self.dispatcher = dispatcher.request_dispatcher
        threading.Thread.__init__(self)
        self.daemon = True
        self.host = host
        self.port = port
        self.lock = threading.Lock()
        
    def run(self):
        print_log( ("TCP") + " server started on port %d"%self.port)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen(5)

        while not self.shared.stopped():

            try:
                connection, address = sock.accept()
            except:
                traceback.print_exc(file=sys.stdout)
                time.sleep(0.1)
                continue

            try:
                session = TcpSession(self.dispatcher, connection, address)
                print_log("New TCP Connection", connection, address)
            except BaseException, e:
                error = str(e)
                print_log("cannot start TCP session", error, address)
                connection.close()
                time.sleep(0.1)
                continue

            client_req = TcpClientRequestor(self.dispatcher, session)
            client_req.start()
            responder = TcpClientResponder(session)
            responder.start()
