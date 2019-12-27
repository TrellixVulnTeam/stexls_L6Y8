''' Implements the server side of the tagger using the json rpc protocol.
    This module contains the dispatcher which provides the methods
    for a JsonRpcProtocol.
    Furthermore, if this module is run as __main__, it can
    start a server using tcp or read and write json-rpc messages directly
    from stdin/out.
'''
__all__ = ['TaggerServerDispatcher']
from typing import List
import asyncio
import logging
import sys
from stexls.trefier.models.tags import Tag
from stexls.util.cli import Cli, Arg, command
from stexls.util.jsonrpc import dispatcher
from stexls.util.jsonrpc.tcp import start_server
from stexls.util.jsonrpc.hooks import method
from stexls.util.jsonrpc.protocol import JsonRpcProtocol
from stexls.util.jsonrpc.streams import AsyncBufferedReaderStream, AsyncBufferedWriterStream

from stexls.trefier.models.seq2seq import Seq2SeqModel

log = logging.getLogger(__name__)
model = None

class TaggerServerDispatcher(dispatcher.Dispatcher):
    ''' This is the interface the tagger server implements. '''
    @method
    def load_model(self, path: str, force: bool = False):
        ''' Loads a model into global memory.
        Parameters:
            path: Path to the model to load.
            force: Enables replacing an already loaded model.
        Return:
            True. Because a request needs a respose.
            Raises an exception if something goes wrong.
        Raises:
            ValueError if an model is already loaded
            but force is not set.
        '''
        global model
        log.info('load_model(%s, %s)', path, force)
        if not force and model is not None:
            log.debug('Attempt to load a model even though one is already loaded.')
            raise ValueError('Model already loaded.')
        try:
            model = Seq2SeqModel.load(path)
            log.debug(model.settings)
            return True
        except:
            log.exception('Failed to load model from "%s"', path)
            raise
        if model is None:
            log.error('load_model(%s) returned None because of unknown reason.')
            raise ValueError('Failed to load model because of unknown reason.')
    
    @method
    def predict(self, *files: str) -> List[List[Tag]]:
        ''' Creates predictions for every given file or string.
        Parameters:
            files: List of files or strings to create predictions for.
        Returns:
            List of tags for each file provided.
        Raises:
            Value error if no model is loaded.
        '''
        log.info('predict(%s)', files)
        if model is None:
            raise ValueError('No model loaded.')
        try:
            predictions = model.predict(*files)
            log.debug('Predictions: %s', predictions)
            return predictions
        except:
            log.exception('Failed to create predictions.')
            raise

    @method
    def get_info(self) -> dict:
        ' Gets info about loaded model, raise ValueError if no model loaded. '
        log.info('get_info()')
        if model is None:
            raise ValueError('No model loaded.')
        log.debug('Settings are: %s', model.settings)
        return model.settings

if __name__ == '__main__':
    @command(
        host=Arg(default='localhost', help='Hostname to bind server to.'),
        port=Arg(type=int, default=0, help='Port to bind server on.'),
        loglevel=Arg(default='error', choices=['error', 'warning', 'info', 'debug'], help='Logger loglevel.'))
    async def tcp(host: str, port: int, loglevel: str = 'error'):
        ''' Creates a tcp socket server that communicates using json-rcp.
            When the server started accepting messages, a line
            with <hostname>:<port> will be printed to stdout.
        Parameters:
            host: The hostname the server will be launched on.
            port: The port the socket should bind to. 0 for any free port.
            loglevel: Logging loglevel (error, warning, info, debug).
        '''
        logging.basicConfig(level=getattr(logging, loglevel.upper(), logging.WARNING))
        log.info('Creating tcp server at %s:%i.', host, port)
        info, server = await start_server(TaggerServerDispatcher, host, port)
        print('{}:{}'.format(*info), flush=True)
        await server

    @command(
        loglevel=Arg(default='error', choices=['error', 'warning', 'info', 'debug'], help='Logger loglevel.'))
    async def stdio(loglevel: str = 'error'):
        ''' Creates a json-rpc server that listens listens for messages
            using stdin and writes respones to stdout.
            Therefore, only a single client can be connected to this server.
        Parameters:
            loglevel: Logging loglevel (error, warning, info, debug).
        '''
        logging.basicConfig(level=getattr(logging, loglevel.upper(), logging.WARNING))
        log.info('Creating json-rpc server using stdin and stdout streams.')
        connection = JsonRpcProtocol(
            AsyncBufferedReaderStream(sys.stdin.buffer),
            AsyncBufferedWriterStream(sys.stdout.buffer))
        server = TaggerServerDispatcher(connection)
        connection.set_method_provider(server)
        await connection.run_until_finished()
        
    cli = Cli([tcp, stdio], description=__doc__)
    asyncio.run(cli.dispatch())
    log.info('Server stopped.')
