from typing import Union
import logging
import asyncio
import pkg_resources
import sys

from stexls.vscode import *
from stexls.util.workspace import Workspace
from stexls.linter import Linter
from stexls.stex import *
from stexls.util.jsonrpc import Dispatcher, method, alias, notification, request

from .completions import CompletionEngine

log = logging.getLogger(__name__)


class Server(Dispatcher):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.workDoneProgress: bool = None
        self._root: Path = None
        self._initialized: bool = False
        self._workspace: Workspace = None
        self._linter: Linter = None
        self._completion_engine: CompletionEngine = None

    async def __aenter__(self):
        log.debug('Server async enter')

    async def __aexit__(self, *args):
        log.debug('Server async exit args: %s', args)

    @method
    @alias('$/progress')
    def receive_progress(
        self,
        token: ProgressToken,
        value: Union[WorkDoneProgressBegin, WorkDoneProgressReport, WorkDoneProgressEnd]):
        log.info('Progress %s received: %s', token, value)

    @notification
    @alias('$/progress')
    def send_progress(
        self,
        token: ProgressToken,
        value: Union[WorkDoneProgressBegin, WorkDoneProgressReport, WorkDoneProgressEnd]):
        pass

    @method
    def initialize(self, workDoneProgress: ProgressToken = undefined, **params):
        ''' Initializes the serverside.
        This method is called by the client that starts the server.
        The server may only respond to other requests after this method successfully returns.
        '''
        if self._initialized:
            raise RuntimeError('Server already initialized')

        self.workDoneProgress = params.get('capabilities', {}).get('window', {}).get('workDoneProgress', False)
        log.info('Progress information enabled: %s', self.workDoneProgress)

        if 'rootUri' in params and params['rootUri']:
            self._root = Path(urllib.parse.urlparse(params['rootUri']).path)
        elif 'rootPath' in params and params['rootPath']:
            # @rootPath is deprecated and must only be used if @rootUri is not defined
            self._root = Path(params['rootPath'])
        else:
            raise RuntimeError('No root path in initialize.')
        log.info('root at: %s', self._root)

        try:
            version = str(pkg_resources.require('stexls')[0].version)
        except:
            version = 'undefined'
        log.info('stexls version: %s', version)

        return {
            'capabilities': {
                'textDocumentSync': {
                    'openClose': True,
                    'change': 1, # TODO: full=1, incremental=2
                    'save': True,
                },
                'completionProvider': {
                    'triggerCharacters': ['?', '[', '{', ',', '='],
                    'allCommitCharacters': [']', '}', ','],
                },
                'definitionProvider': True,
                'referencesProvider': True,
                'workspace': {
                    'workspaceFolders': {
                        'supported': True,
                        'changeNotifications': True
                    }
                }
            },
            'serverInfo': {
                'name': 'stexls',
                'version': version
            }
        }

    @method
    async def initialized(self):
        ' Event called by the client after it finished initialization. '
        if self._initialized:
            raise RuntimeError('Server already initialized')
        outdir = self._root / '.stexls' / 'objects'
        self._workspace = Workspace(self._root)
        self._linter = Linter(
            workspace=self._workspace,
            outdir=outdir,
            enable_global_validation=False,
            num_jobs=1)
        self._completion_engine = CompletionEngine(None)
        await self._update(all=True)
        log.info('Initialized')
        self._initialized = True

    @method
    def shutdown(self):
        log.info('Shutting down server...')

    @method
    def exit(self):
        log.info('exit')
        sys.exit()

    @notification
    @alias('window/showMessage')
    def show_message(self, type: MessageType, message: str):
        pass

    @request
    @alias('window/showMessageRequest')
    def show_message_request(self, type: MessageType, message: str, actions: List[MessageActionItem]):
        pass

    @request
    @alias('window/logMessage')
    def log_message(self, type: MessageType, message: str):
        pass

    @request
    @alias('window/workDoneProgress/create')
    def window_work_done_progress_create(self, token: ProgressToken):
        pass

    @method
    @alias('window/workDoneProgress/cancel')
    def window_work_done_progress_cancel(self, token: ProgressToken):
        log.warning('Client attempted to cancel token %s, but canceling is not implemented yet', token)

    @method
    @alias('textDocument/definition')
    def definition(
        self,
        textDocument: TextDocumentIdentifier,
        position: Position,
        workDoneToken: ProgressToken = undefined,
        **params):
        # TODO
        log.debug('definitions(%s, %s)', textDocument.path, position.format())
        return []

    @method
    @alias('textDocument/references')
    def references(
        self,
        textDocument: TextDocumentIdentifier,
        position: Position,
        workDoneToken: ProgressToken = undefined,
        context = undefined,
        **params):
        # TODO
        log.debug('references(%s, %s)', textDocument.path, position.format())
        return []

    @method
    @alias('textDocument/completion')
    def completion(
        self,
        textDocument: TextDocumentIdentifier,
        position: Position,
        context: CompletionContext = undefined,
        workDoneToken: ProgressToken = undefined):
        log.debug('completion(%s, %s, context=%s)', textDocument.path, position.format(), context)
        return []

    @notification
    @alias('textDocument/publishDiagnostics')
    def publish_diagnostics(self, uri: DocumentUri, diagnostics: List[Diagnostic]):
        pass

    @method
    @alias('textDocument/didOpen')
    async def text_document_did_open(self, textDocument: TextDocumentItem):
        log.debug('didOpen(%s)', textDocument)
        self._workspace.open_file(textDocument.path, textDocument.text, textDocument.version)
        flag = False
        async with self._compile_lock:
            if self._workspace.open_file(textDocument.path, textDocument.text):
                log.info('didOpen: %s', textDocument.uri)
                flag = True
        if flag:
            await self._request_file_update(textDocument.path)
        else:
            log.debug('Received didOpen event for invalid file: %s', textDocument.uri)

    @method
    @alias('textDocument/didChange')
    async def text_document_did_change(self, textDocument: VersionedTextDocumentIdentifier, contentChanges: List[TextDocumentContentChangeEvent]):
        log.debug('updating file "%s" with version %i', textDocument.path, textDocument.version)
        log.debug('changes: ', contentChanges)
        for item in contentChanges:
            status = self._workspace.update_file(textDocument.path, textDocument.version, item.text)
            if not status:
                log.warning('Failed to patch file with: %s', item)


    @method
    @alias('textDocument/didClose')
    async def text_document_did_close(self, textDocument: TextDocumentIdentifier):
        log.debug('Closing document: "%s"', textDocument.path)
        status = self._workspace.close_file(textDocument.path)
        if not status:
            log.warning('Failed to close file "%s"', textDocument.path)

    @method
    @alias('textDocument/didSave')
    async def text_document_did_save(self, textDocument: TextDocumentIdentifier, text: str = undefined):
        if self._workspace.is_open(textDocument.path):
            log.info('didSave: %s', textDocument.uri)
        else:
            log.debug('Received didSave event for invalid file: %s', textDocument.uri)
