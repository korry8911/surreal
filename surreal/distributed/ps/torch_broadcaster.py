from .broadcaster import Broadcaster
import surreal.utils as U


class TorchBroadcaster(Broadcaster):
    def __init__(self,
                 redis_client,
                 name='ps',
                 *, debug=False):
        super().__init__(redis_client=redis_client, name=name)
        self._debug = debug

    def broadcast(self, net, message):
        U.assert_type(net, U.Module)
        binary = net.parameters_to_binary()
        if self._debug:
            print('BROADCAST', message, 'BINARY_HASH', U.binary_hash(binary))
        super().broadcast(binary, message)
