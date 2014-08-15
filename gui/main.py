import sys
import json
from os.path import dirname, join

#from PySide.QtCore import QApplication
from PySide.QtCore import QObject, Slot, Signal
from PySide.QtGui import QApplication
from PySide.QtWebKit import QWebView, QWebSettings
from PySide.QtNetwork import QNetworkRequest

from pyethereum.ethclient import APIClient, mktx, privtoaddr, DEFAULT_HOST, DEFAULT_PORT, DEFAULT_GASPRICE, DEFAULT_STARTGAS

web     = None
myPage  = None
myFrame = None


class EthClient(QObject):

    def __init__(self, privkey):
        super(EthClient, self).__init__()
        self.privkey = privkey
        self.api = APIClient(DEFAULT_HOST, DEFAULT_PORT)

    @Slot(str)
    def getbalance(self, data):
        print "balance", data
        address = privtoaddr(self.privkey)
        balance = self.api.getbalance(address)
        res = dict(address=address, balance=str(balance))
        print 'response:', res
        self.on_getbalance_cb.emit(json.dumps(res))

    @Slot(str)
    def transact(self, data):
        data = json.loads(data)
        print "transact", data
        res = self.api.quicktx(DEFAULT_GASPRICE, DEFAULT_STARTGAS,
                                data['txto'], int(data['txvalue']), '', self.privkey)
        print 'response:', res
        self.on_transact_cb.emit(json.dumps(res))

    on_getbalance = Signal(str)
    on_getbalance_cb = Signal(str)
    on_transact = Signal(str)
    on_transact_cb = Signal(str)

    on_client_event = Signal(str)
    on_actor_event = Signal(str)


class HTMLApplication(object):

    def show(self):
        #It is IMPERATIVE that all forward slashes are scrubbed out, otherwise QTWebKit seems to be
        # easily confused
        kickOffHTML = join(dirname(__file__).replace('\\', '/'), "templates/index.html").replace('\\', '/')

        #This is basically a browser instance
        self.web = QWebView()

        #Unlikely to matter but prefer to be waiting for callback then try to catch
        # it in time.
        self.web.loadFinished.connect(self.onLoad)
        self.web.load(kickOffHTML)

        self.web.show()

    def onLoad(self):
        #This is the body of a web browser tab
        self.myPage = self.web.page()
        self.myPage.settings().setAttribute(QWebSettings.DeveloperExtrasEnabled, True)
        #This is the actual context/frame a webpage is running in.
        # Other frames could include iframes or such.
        self.myFrame = self.myPage.mainFrame()
        # ATTENTION here's the magic that sets a bridge between Python to HTML
        self.myFrame.addToJavaScriptWindowObject("eth", self.ethclient)

        #Tell the HTML side, we are open for business
        self.myFrame.evaluateJavaScript("ApplicationIsReady()")


if __name__ == '__main__':
    if len(sys.argv) <2:
        print "Usage: %s privkey" % sys.argv[0]
        sys.exit(1)
    privkey = sys.argv[1]

    #Kickoff the QT environment
    app = QApplication(sys.argv)

    myWebApp = HTMLApplication()
    myWebApp.ethclient = EthClient(privkey)
    myWebApp.show()
    sys.exit(app.exec_())