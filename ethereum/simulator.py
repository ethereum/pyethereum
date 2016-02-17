#!/usr/bin/env python
from network import NetworkSimulator, Node
from bet import mk_bet_strategy, genesis, keys
import gevent
import IPython
import IPython.core.shellapp
from IPython.lib.inputhook import inputhook_manager, stdin_ready

GUI_GEVENT = 'gevent'


def inputhook_gevent():
    while not stdin_ready():
        gevent.sleep(0.05)
    return 0


@inputhook_manager.register('gevent')
class GeventInputHook(object):
    def __init__(self, manager):
        self.manager = manager

    def enable(self, app=None):
        """Enable event loop integration with gevent.
        Parameters
        ----------
        app : ignored
            Ignored, it's only a placeholder to keep the call signature of all
            gui activation methods consistent, which simplifies the logic of
            supporting magics.
        Notes
        -----
        This methods sets the PyOS_InputHook for gevent, which allows
        gevent greenlets to run in the background while interactively using
        IPython.
        """
        self.manager.set_inputhook(inputhook_gevent)
        self._current_gui = GUI_GEVENT
        return app

    def disable(self):
        """Disable event loop integration with gevent.
        This merely sets PyOS_InputHook to NULL.
        """
        self.manager.clear_inputhook()

# ipython needs to accept "--gui gevent" option
IPython.core.shellapp.InteractiveShellApp.gui.values += ('gevent',)


def run_dummy():
    net = NetworkSimulator()
    gevent.spawn(net.start)
    console_locals = dict(net=net)
    IPython.start_ipython(argv=['--gui', 'gevent'], user_ns=console_locals)


def run_serenity():
    net = NetworkSimulator(agents=0)
    for i, k in enumerate(keys):
        agent = mk_bet_strategy(genesis, i, k)
        node = Node(agent, reliability=net.reliability)
        net.nodes.append(node)

    # now start network and ipython
    gevent.spawn(net.start)
    console_locals = dict(net=net)
    IPython.start_ipython(argv=['--gui', 'gevent'], user_ns=console_locals)

if __name__ == "__main__":
    run_serenity()
