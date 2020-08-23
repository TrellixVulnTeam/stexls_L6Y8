from __future__ import annotations
from typing import Callable, Optional, Tuple, List, Dict, Set
from pathlib import Path
import re

from stexls.util import roman_numerals
from stexls.vscode import *
from stexls.util.latex.parser import Environment, Node, LatexParser, OArgument
from stexls.util.latex.exceptions import LatexException

from .exceptions import *
from .symbols import *
from . import util

__all__ = (
    'IntermediateParser',
    'IntermediateParseTree',
    'TokenWithLocation',
    'ScopeIntermediateParseTree',
    'ModsigIntermediateParseTree',
    'ModnlIntermediateParseTree',
    'ModuleIntermediateParseTree',
    'TrefiIntermediateParseTree',
    'DefiIntermediateParseTree',
    'SymiIntermediateParseTree',
    'SymdefIntermediateParseTree',
    'ImportModuleIntermediateParseTree',
    'GImportIntermediateParseTree',
    'GStructureIntermediateParseTree',
    'ViewIntermediateParseTree',
    'ViewSigIntermediateParseTree',
)


class IntermediateParseTree:
    def __init__(self, location: Location):
        self.location = location
        self.children: List[IntermediateParseTree] = []
        self.parent: IntermediateParseTree = None

    def add_child(self, child: IntermediateParseTree):
        assert child.parent is None
        self.children.append(child)
        child.parent = self

    @property
    def scope(self) -> Optional[IntermediateParseTree]:
        if isinstance(self, (
            ScopeIntermediateParseTree,
            ModsigIntermediateParseTree,
            ModnlIntermediateParseTree,
            ViewIntermediateParseTree,
            ViewSigIntermediateParseTree,
            ModuleIntermediateParseTree)):
            return self
        if self.parent:
            return self.parent.scope
        return None

    @property
    def depth(self) -> int:
        if self.parent:
            return self.parent.depth + 1
        return 0

    def traverse(self, enter, exit=None):
        if enter:
            enter(self)
        for c in self.children:
            c.traverse(enter, exit)
        if exit:
            exit(self)


class IntermediateParser:
    " An object contains information about symbols, locations, imports of an stex source file. "
    def __init__(self, path: Path):
        ' Creates an empty container without actually parsing the file. '
        self.path = Path(path)
        self.roots: List[IntermediateParseTree] = []
        self.errors: Dict[Location, List[Exception]] = {}

    def parse(self, content: str = None) -> IntermediateParser:
        ' Parse the file from the in the constructor given path. '
        if self.roots:
            raise ValueError('File already parsed.')
        try:
            parser = LatexParser(self.path)
            parser.parse(content)
            stack: List[Tuple[Environment, Callable]] = [(None, self.roots.append)]
            parser.walk(
                lambda env: self._enter(env, stack),
                lambda env: self._exit(env, stack))
        except (CompilerError, LatexException, UnicodeError) as ex:
            self.errors.setdefault(self.default_location, []).append(ex)
        return self

    def _enter(self, env, stack_of_add_child_operations: List[Tuple[Environment, Callable]]):
        try:
            tree = next(filter(None, map(
                lambda cls_: cls_.from_environment(env),
                [
                    ScopeIntermediateParseTree,
                    ModsigIntermediateParseTree,
                    ModnlIntermediateParseTree,
                    ModuleIntermediateParseTree,
                    TrefiIntermediateParseTree,
                    DefiIntermediateParseTree,
                    SymiIntermediateParseTree,
                    SymdefIntermediateParseTree,
                    ImportModuleIntermediateParseTree,
                    GImportIntermediateParseTree,
                    GStructureIntermediateParseTree,
                    ViewIntermediateParseTree,
                    ViewSigIntermediateParseTree,
                ]
            )), None)
            if tree:
                if stack_of_add_child_operations[-1]:
                    stack_of_add_child_operations[-1][1](tree)
                stack_of_add_child_operations.append((env, tree.add_child))
                return
        except CompilerError as e:
            self.errors.setdefault(env.location, []).append(e)

    def _exit(self, env, stack_of_add_child_operations: List[Tuple[Environment, Callable]]):
        if stack_of_add_child_operations[-1][0] == env:
            stack_of_add_child_operations.pop()

    @property
    def default_location(self) -> Location:
        """ Returns a location with a range that contains the whole file
            or just the range from 0 to 0 if the file can't be openened.
        """
        try:
            with open(self.path) as fd:
                content = fd.read()
            lines = content.split('\n')
            num_lines = len(lines)
            len_last_line = len(lines[-1])
            return Location(self.path.as_uri(), Range(Position(0, 0), Position(num_lines - 1, len_last_line - 1)))
        except:
            return Location(self.path.as_uri(), Position(0, 0))


class TokenWithLocation:
    def __init__(self, text: str, range: Range):
        self.text = text
        self.range = range

    def __repr__(self):
        return self.text

    @staticmethod
    def parse_oargs(oargs: List[OArgument]) -> Tuple[List[TokenWithLocation], Dict[str, TokenWithLocation]]:
        unnamed = [
            TokenWithLocation.from_node(oarg.value)
            for oarg in oargs
            if oarg.name is None
        ]
        named = {
            oarg.name.text[:-1]: TokenWithLocation.from_node(oarg.value)
            for oarg in oargs
            if oarg.name is not None
        }
        return unnamed, named

    def split(self, index: int, offset: int = 0) -> Optional[Tuple[TokenWithLocation, TokenWithLocation]]:
        ''' Splits the token at the specified index.

        Arguments:
            index: The index on where to split the token.
            offset: Optional character offset of second split.

        Examples:
            >>> range = Range(Position(1, 5), Position(1, 18))
            >>> text = 'module?symbol'
            >>> token = TokenWithLocation(text, range)
            >>> left, right = token.split(text.index('?'), offset=1)
            >>> left
            'module'
            >>> left.range
            [Range (1 5) (1 11)]
            >>> right
            'symbol'
            >>> right.range
            [Range (1 12) (1 18)]
            >>> _, right = token.split(text.index('?'), offset=0)
            >>> right
            '?symbol'
            >>> right.range
            [Range (1 11) (1 18)]
        '''
        ltext = self.text[:index]
        rtext = self.text[index + offset:]
        lrange, rrange = self.range.split(index)
        return TokenWithLocation(ltext, lrange), TokenWithLocation(rtext, rrange)

    @staticmethod
    def from_node(node: Node) -> TokenWithLocation:
        return TokenWithLocation(node.text_inside, node.location.range)

    @staticmethod
    def from_node_union(nodes: List[Node], separator: str = ',') -> Optional[TokenWithLocation]:
        tags = map(TokenWithLocation.from_node, nodes)
        values, ranges = zip(*((tok.text, tok.range) for tok in tags))
        return TokenWithLocation(separator.join(values), Range.big_union(ranges))


class ScopeIntermediateParseTree(IntermediateParseTree):
    PATTERN = re.compile(r'n?omtext|example|omgroup|frame')
    def __init__(self, location: Location, scope_name: TokenWithLocation):
        super().__init__(location)
        self.scope_name = scope_name

    @classmethod
    def from_environment(cls, e: Environment) -> Optional[ScopeIntermediateParseTree]:
        match = ScopeIntermediateParseTree.PATTERN.fullmatch(e.env_name)
        if not match:
            return
        return ScopeIntermediateParseTree(e.location, TokenWithLocation.from_node(e.name))

    def __repr__(self) -> str:
        return f'[Scope "{self.scope_name.text}"]'


class ModsigIntermediateParseTree(IntermediateParseTree):
    PATTERN = re.compile(r'modsig')
    def __init__(self, location: Location, name: TokenWithLocation):
        super().__init__(location)
        self.name = name

    @classmethod
    def from_environment(cls, e: Environment) -> Optional[ModsigIntermediateParseTree]:
        match = ModsigIntermediateParseTree.PATTERN.fullmatch(e.env_name)
        if not match:
            return
        if not e.rargs:
            raise CompilerError('Modsig environment missing required argument: {<module name>}')
        return ModsigIntermediateParseTree(
            e.location,
            TokenWithLocation.from_node(e.rargs[0]))

    def __repr__(self):
        return f'[Modsig name={self.name.text}]'


class ModnlIntermediateParseTree(IntermediateParseTree):
    PATTERN = re.compile(r'(mh)?modnl')
    def __init__(
        self,
        location: Location,
        name: TokenWithLocation,
        lang: TokenWithLocation,
        mh_mode: bool):
        super().__init__(location)
        self.name = name
        self.lang = lang
        self.mh_mode = mh_mode

    @property
    def path(self) -> Path:
        ''' Guesses the path to the file of the attached module.

        Takes the path of the file this language binding is located and
        returns the default path to the attached module.

        Returns:
            Path: Path to module file.

        Examples:
            >>> binding_path = Path('path/to/glossary/repo/source/module/module.lang.tex')
            >>> binding_location = Location(binding_path, None)
            >>> module_name = TokenWithLocation('module', None)
            >>> binding_lang = TokenWithLocation('lang', None)
            >>> binding = Modnl(binding_location, module_name, binding_lang, False)
            >>> binding.path.as_posix()
            'path/to/glossary/repo/source/module/module.tex'
        '''
        return (self.location.path.parents[0] / (self.name.text + '.tex'))

    @classmethod
    def from_environment(cls, e: Environment) -> Optional[ModnlIntermediateParseTree]:
        match = ModnlIntermediateParseTree.PATTERN.fullmatch(e.env_name)
        if not match:
            return
        if len(e.rargs) != 2:
            raise CompilerError(f'Argument count mismatch (expected 2, found {len(e.rargs)}).')
        return ModnlIntermediateParseTree(
            e.location,
            TokenWithLocation.from_node(e.rargs[0]),
            TokenWithLocation.from_node(e.rargs[1]),
            mh_mode=match.group(1) == 'mh',
        )

    def __repr__(self):
        mh = 'mh' if self.mh_mode else ''
        return f'[{mh}Modnl {self.name.text} lang={self.lang.text}]'


class ViewIntermediateParseTree(IntermediateParseTree):
    PATTERN = re.compile(r'mhview|gviewnl')
    def __init__(
        self,
        location: Location,
        env: str,
        module: TokenWithLocation,
        lang: Optional[TokenWithLocation],
        imports: List[TokenWithLocation],
        fromrepos: Optional[TokenWithLocation],
        frompath: Optional[TokenWithLocation]):
        super().__init__(location)
        self.env = env
        self.module = module
        self.lang = lang
        self.imports = imports
        self.fromrepos = fromrepos
        self.frompath = frompath

    @classmethod
    def from_environment(cls, e: Environment) -> Optional[ViewIntermediateParseTree]:
        match = cls.PATTERN.match(e.env_name)
        if not match:
            return None
        _, named = TokenWithLocation.parse_oargs(e.oargs)
        lang = None
        if e.env_name == 'gviewnl':
            if len(e.rargs) < 2:
                raise CompilerError(f'Argument count mismatch: gviewnl requires at least 2 arguments, found {len(e.rargs)}.')
            if 'frompath' in named:
                raise CompilerError('frompath argument not allowed in gviewnl.')
            lang = e.rargs[1]
            imports = e.rargs[2:]
        elif e.env_name == 'mhview':
            if len(e.rargs) < 1:
                raise CompilerError(f'Argument count mismatch: mhview requires at least 1 argument, found {len(e.rargs)}.')
            if 'fromrepos' in named:
                raise CompilerError('fromrepos argument not allowed in mhview.')
            imports = e.rargs[1:]
        else:
            raise CompilerError(f'Invalid environment name "{e.env_name}"')
        module = e.rargs[0]
        return ViewIntermediateParseTree(
            location=e.location,
            env=e.env_name,
            module=module,
            lang=lang,
            imports=imports,
            fromrepos=named.get('fromrepos'),
            frompath=named.get('frompath'))


class ViewSigIntermediateParseTree(IntermediateParseTree):
    PATTERN = re.compile('gviewsig')
    def __init__(
        self,
        location: Location,
        fromrepos: Optional[TokenWithLocation],
        module_name: TokenWithLocation,
        imports: List[TokenWithLocation]):
        super().__init__(location)
        self.fromrepos = fromrepos
        self.module_name = module_name
        self.imports = imports

    @classmethod
    def from_environment(cls, e: Environment) -> Optional[ViewSigIntermediateParseTree]:
        match = ViewSigIntermediateParseTree.PATTERN.fullmatch(e.env_name)
        if not match:
            return None
        if len(e.rargs) < 1:
            raise CompilerError('viewsig requires at least one argument, found 0.')
        _, named = TokenWithLocation.parse_oargs(e.oargs)
        return ViewSigIntermediateParseTree(
            location=e.location,
            fromrepos=named.get('fromrepos', None),
            module_name=TokenWithLocation.from_node(e.rargs[0]),
            imports=list(map(TokenWithLocation.from_node, e.rargs[1:]))
        )

    def __repr__(self) -> str:
        return f'[ViewSig "{self.module_name}" from "{self.fromrepos}" imports {self.imports}]'


class ModuleIntermediateParseTree(IntermediateParseTree):
    PATTERN = re.compile(r'module(\*)?')
    def __init__(
        self,
        location: Location,
        id: Optional[TokenWithLocation]):
        super().__init__(location)
        self.id = id

    def __repr__(self):
        module = f'id="{self.id.text}"' if self.id else '<anonymous>'
        return f'[Module {module}]'

    @classmethod
    def from_environment(cls, e: Environment) -> Optional[ModuleIntermediateParseTree]:
        match = cls.PATTERN.match(e.env_name)
        if match is None:
            return None
        _, named = TokenWithLocation.parse_oargs(e.oargs)
        return ModuleIntermediateParseTree(
            location=e.location,
            id=named.get('id'),
        )


class GStructureIntermediateParseTree(IntermediateParseTree):
    PATTERN = re.compile(r'gstructure(\*)?')
    def __init__(self, location: Location, mhrepos: TokenWithLocation, module: TokenWithLocation):
        super().__init__(location)
        self.mhrepos = mhrepos
        self.module = module

    @classmethod
    def from_environment(cls, e: Environment) -> Optional[GStructureIntermediateParseTree]:
        match = cls.PATTERN.match(e.env_name)
        if match is None:
            return None
        if len(e.rargs) != 2:
            raise CompilerError(f'gstructure environment requires at least 2 Arguments but {len(e.rargs)} found.')
        _, named = TokenWithLocation.parse_oargs(e.oargs)
        return GStructureIntermediateParseTree(
            location=e.location,
            mhrepos=named.get('mhrepos'),
            module=TokenWithLocation.from_node(e.rargs[1])
        )

    def __repr__(self) -> str:
        return f'[GStructure "{self.module}"]'


class DefiIntermediateParseTree(IntermediateParseTree):
    PATTERN = re.compile(r'([ma]*)(d|D)ef([ivx]+)(s)?(\*)?')
    def __init__(
        self,
        location: Location,
        tokens: List[TokenWithLocation],
        name_annotation: Optional[TokenWithLocation],
        m: bool,
        a: bool,
        capital: bool,
        i: int,
        s: bool,
        asterisk: bool):
        super().__init__(location)
        self.tokens = tokens
        self.name_annotation = name_annotation
        self.m = m
        self.capital = capital
        self.a = a
        self.i = i
        self.s = s
        self.asterisk = asterisk
        if i + int(a) != len(tokens):
            raise CompilerError(f'Defi argument count mismatch: Expected {i + int(a)} vs actual {len(tokens)}.')

    @property
    def name(self) -> str:
        if self.name_annotation:
            return self.name_annotation.text
        if self.a:
            return '-'.join(t.text for t in self.tokens[1:])
        return '-'.join(t.text for t in self.tokens)

    @classmethod
    def from_environment(cls, e: Environment) -> Optional[DefiIntermediateParseTree]:
        match = DefiIntermediateParseTree.PATTERN.fullmatch(e.env_name)
        if match is None:
            return None
        if not e.rargs:
            raise CompilerError('Argument count mismatch (expected at least 1, found 0).')
        _, named = TokenWithLocation.parse_oargs(e.oargs)
        try:
            i = roman_numerals.roman2int(match.group(3))
        except:
            raise CompilerError(f'Invalid environment (are the roman numerals correct?): {e.env_name}')
        return DefiIntermediateParseTree(
            location=e.location,
            tokens=list(map(TokenWithLocation.from_node, e.rargs)),
            name_annotation=named.get('name'),
            m='m' in match.group(1),
            a='a' in match.group(1),
            capital=match.group(2) == 'D',
            i=i,
            s=match.group(4) is not None,
            asterisk=match.group(5) is not None)

    def __repr__(self):
        return f'[Def{"i"*self.i} "{self.name}"]'


class TrefiIntermediateParseTree(IntermediateParseTree):
    PATTERN = re.compile(r'([ma]*)(d|D|t|T)ref([ivx]+)(s)?(\*)?')
    def __init__(
        self,
        location: Location,
        tokens: List[TokenWithLocation],
        target_annotation: Optional[TokenWithLocation],
        m: bool,
        a: bool,
        capital: bool,
        drefi: bool,
        i: int,
        s: bool,
        asterisk: bool):
        super().__init__(location)
        self.tokens = tokens
        self.target_annotation = target_annotation
        self.m = m
        self.a = a
        self.capital = capital
        self.drefi = drefi
        self.i = i
        self.s = s
        self.asterisk = asterisk
        if i + int(a) != len(tokens):
            raise CompilerError(f'Trefi argument count mismatch: Expected {i + int(a)} vs. actual {len(tokens)}.')

    @property
    def name(self) -> str:
        ''' Parses the targeted symbol's name.

        The target's name is either given in the annotations
        by using the ?<symbol> syntax or else it is generated
        by joining the tokens with a '-' character.
        '''
        if self.target_annotation and '?' in self.target_annotation.text:
            return self.target_annotation.text.split('?')[-1].strip()
        tokens = (t.text for t in self.tokens[int(self.a):])
        generated = '-'.join(tokens)
        return generated.strip()

    @property
    def module(self) -> Optional[TokenWithLocation]:
        ''' Parses the targeted module's name if specified in oargs.

        Returns None if no module is explicitly named.
        '''
        if self.target_annotation:
            if '?' in self.target_annotation.text:
                index = self.target_annotation.text.index('?')
                left, _ = self.target_annotation.split(index, 1)
                if left.text:
                    return left # return left in case of <module>?<symbol>
                return None # return None in case of ?symbol
            return self.target_annotation # return the whole thing in case of [module]
        return None # return None if no oargs are given

    @classmethod
    def from_environment(cls, e: Environment) -> Optional[TrefiIntermediateParseTree]:
        match = TrefiIntermediateParseTree.PATTERN.fullmatch(e.env_name)
        if match is None:
            return None
        if not e.rargs:
            raise CompilerError('Argument count mismatch (expected at least 1, found 0).')
        if len(e.unnamed_args) > 1:
            raise CompilerError(f'Too many unnamed oargs in trefi: Expected are at most 1, found {len(e.unnamed_args)}')
        annotations = (
            TokenWithLocation.from_node(e.unnamed_args[0])
            if e.unnamed_args
            else None
        )
        tokens = list(map(TokenWithLocation.from_node, e.rargs))
        try:
            i = roman_numerals.roman2int(match.group(3))
        except:
            raise CompilerError(f'Invalid environment (are the roman numerals correct?): {e.env_name}')
        return TrefiIntermediateParseTree(
            location=e.location,
            tokens=tokens,
            target_annotation=annotations,
            m='m' in match.group(1),
            a='a' in match.group(1),
            capital=match.group(2) == 'T',
            drefi=match.group(2) in ('d', 'D'),
            i=i,
            s=match.group(4) is not None,
            asterisk=match.group(5) is not None,
        )

    def __repr__(self):
        module = f' from "{self.module}"' if self.module else ""
        return f'[Tref{"i"*self.i} "{self.name}"{module}]'


class _NoverbHandler:
    def __init__(
        self,
        unnamed: List[TokenWithLocation],
        named: Dict[str, TokenWithLocation]):
        self.unnamed = unnamed
        self.named = named

    @property
    def is_all(self) -> bool:
        return any(arg.text == 'noverb' for arg in self.unnamed)

    @property
    def langs(self) -> Set[str]:
        noverb: TokenWithLocation = self.named.get('noverb')
        if noverb is None:
            return set()
        if (noverb.text[0], noverb.text[-1]) == ('{', '}'):
            return set(noverb.text[1:-1].split(','))
        return set([noverb.text])


class SymiIntermediateParseTree(IntermediateParseTree):
    PATTERN = re.compile(r'sym([ivx]+)(\*)?')
    def __init__(
        self,
        location: Location,
        tokens: List[TokenWithLocation],
        unnamed_args: List[TokenWithLocation],
        named_args: Dict[str, TokenWithLocation],
        i: int,
        asterisk: bool):
        super().__init__(location)
        self.tokens = tokens
        self.noverb = _NoverbHandler(unnamed_args, named_args)
        self.i = i
        self.asterisk = asterisk
        if i != len(tokens):
            raise CompilerError(f'Symi argument count mismatch: Expected {i} vs actual {len(tokens)}.')

    @property
    def name(self) -> str:
        return '-'.join(token.text for token in self.tokens)

    @classmethod
    def from_environment(cls, e: Environment) -> Optional[SymiIntermediateParseTree]:
        match = SymiIntermediateParseTree.PATTERN.fullmatch(e.env_name)
        if match is None:
            return None
        if not e.rargs:
            raise CompilerError('Argument count mismatch (expected at least 1, found 0).')
        unnamed, named = TokenWithLocation.parse_oargs(e.oargs)
        try:
            i = roman_numerals.roman2int(match.group(1))
        except:
            raise CompilerError(f'Invalid environment (are the roman numerals correct?): {e.env_name}')
        return SymiIntermediateParseTree(
            location=e.location,
            tokens=list(map(TokenWithLocation.from_node, e.rargs)),
            unnamed_args=unnamed,
            named_args=named,
            i=i,
            asterisk=match.group(2) is not None,
        )

    def __repr__(self):
        return f'[Sym{"i"*self.i}{"*"*self.asterisk} "{self.name}"]'


class SymdefIntermediateParseTree(IntermediateParseTree):
    PATTERN = re.compile(r'symdef(\*)?')
    def __init__(
        self,
        location: Location,
        name: TokenWithLocation,
        unnamed_oargs: List[TokenWithLocation],
        named_oargs: Dict[str, TokenWithLocation],
        asterisk: bool):
        super().__init__(location)
        self.name: TokenWithLocation = name
        self.noverb = _NoverbHandler(unnamed_oargs, named_oargs)
        self.asterisk: bool = asterisk

    @classmethod
    def from_environment(cls, e: Environment) -> Optional[SymdefIntermediateParseTree]:
        match = SymdefIntermediateParseTree.PATTERN.fullmatch(e.env_name)
        if match is None:
            return None
        if not e.rargs:
            raise CompilerError('Argument count mismatch: At least one argument required.')
        name = TokenWithLocation.from_node(e.rargs[0])
        unnamed, named = TokenWithLocation.parse_oargs(e.oargs)
        return SymdefIntermediateParseTree(
            location=e.location,
            name=named.get('name', name),
            unnamed_oargs=unnamed,
            named_oargs=named,
            asterisk=match.group(1) is not None,
        )

    def __repr__(self):
        return f'[Symdef{"*"*self.asterisk} "{self.name.text}"]'


class ImportModuleIntermediateParseTree(IntermediateParseTree):
    PATTERN = re.compile(r'(import|use)(mh)?module(\*)?')
    def __init__(
        self,
        location: Location,
        module: TokenWithLocation,
        mhrepos: Optional[TokenWithLocation],
        repos: Optional[TokenWithLocation],
        dir: Optional[TokenWithLocation],
        load: Optional[TokenWithLocation],
        path: Optional[TokenWithLocation],
        export: bool,
        mh_mode: bool,
        asterisk: bool):
        super().__init__(location)
        self.module = module
        self.mhrepos = mhrepos
        self.repos = repos
        self.dir = dir
        self.load = load
        self.path = path
        self.export = export
        self.mh_mode = mh_mode
        self.asterisk = asterisk
        if len(list(self.location.path.parents)) < 4:
            raise CompilerWarning(f'Unable to compile module with a path depth of less than 4: {self.location.path}')
        if mh_mode:
            # mhimport{}
            # mhimport[dir=..]{}
            # mhimport[path=..]{}
            # mhimport[mhrepos=..,dir=..]{}
            # mhimport[mhrepos=..,path=..]{}
            if dir and path:
                raise CompilerError('Invalid argument configuration in importmhmodule: "dir" and "path" must not be specified at the same time.')
            if mhrepos and not (dir or path):
                raise CompilerError('Invalid argument configuration in importmhmodule: "mhrepos" requires a "dir" or "path" argument.')
            elif load:
                raise CompilerError('Invalid argument configuration in importmhmodule: "load" argument must not be specified.')
        elif mhrepos or dir or path:
            raise CompilerError('Invalid argument configuration in importmodule: "mhrepos", "dir" or "path" must not be specified.')
        elif not load:
            # import[load=..]{}
            raise CompilerError('Invalid argument configuration in importmodule: Missing "load" argument.')

    @staticmethod
    def build_path_to_imported_module(
        root: Path,
        current_file: Path,
        mhrepo: Optional[str],
        path: Optional[str],
        dir: Optional[str],
        load: Optional[str],
        module: str):
        if load:
            return (root / load / (module + '.tex')).expanduser().resolve().absolute()
        if not mhrepo and not path and not dir:
            return (current_file).expanduser().resolve().absolute()
        if mhrepo:
            source: Path = root / mhrepo / 'source'
        else:
            source: Path = util.find_source_dir(root, current_file)
        if dir:
            result = source / dir / (module + '.tex')
        elif path:
            result = source / (path + '.tex')
        else:
            raise ValueError('Invalid arguments: "path" or "dir" must be specified if "mhrepo" is.')
        return result.expanduser().resolve().absolute()

    def path_to_imported_file(self, root: Path) -> Path:
        return ImportModuleIntermediateParseTree.build_path_to_imported_module(
            root,
            self.location.path,
            self.mhrepos.text if self.mhrepos else None,
            self.path.text if self.path else None,
            self.dir.text if self.dir else None,
            self.load.text if self.load else None,
            self.module.text)

    def __repr__(self):
        try:
            from_ = f' from "{self.path_to_imported_file(Path.cwd())}"'
        except:
            from_ = ''
        access = AccessModifier.PUBLIC if self.export else AccessModifier.PRIVATE
        return f'[{access.value} ImportModule "{self.module.text}"{from_}]'

    @classmethod
    def from_environment(cls, e: Environment) -> Optional[ImportModuleIntermediateParseTree]:
        match = ImportModuleIntermediateParseTree.PATTERN.fullmatch(e.env_name)
        if match is None:
            return None
        if len(e.rargs) != 1:
            raise CompilerError(f'Argument count mismatch: Expected exactly 1 argument but found {len(e.rargs)}')
        module = TokenWithLocation.from_node(e.rargs[0])
        _, named = TokenWithLocation.parse_oargs(e.oargs)
        return ImportModuleIntermediateParseTree(
            location=e.location,
            module=module,
            mhrepos=named.get('mhrepos') or named.get('repos'),
            repos=named.get('repos'),
            dir=named.get('dir'),
            path=named.get('path'),
            load=named.get('load'),
            export=match.group(1) == 'import',
            mh_mode=match.group(2) == 'mh',
            asterisk=match.group(3) == '*'
        )


class GImportIntermediateParseTree(IntermediateParseTree):
    PATTERN = re.compile(r'g(import|use)(\*)?')
    def __init__(
        self,
        location: Location,
        module: TokenWithLocation,
        repository: Optional[TokenWithLocation],
        export: bool,
        asterisk: bool):
        super().__init__(location)
        self.module = module
        self.repository = repository
        self.export = export
        self.asterisk = asterisk

    @staticmethod
    def build_path_to_imported_module(
        root: Path,
        current_file: Path,
        repo: Optional[Path],
        module: str):
        """ A static helper method to get the targeted filepath by a gimport environment.

        Parameters:
            root: Root of mathhub.
            current_file: File which uses the gimport statement.
            repo: Optional repository specified in gimport statements: gimport[<repository>]{...}
            module: The targeted module in gimport statements: gimport{<module>}

        Returns:
            Path to the file in which the module <module> is located.
        """
        if repo is not None:
            assert current_file.relative_to(root)
            source = root / repo / 'source'
        else:
            source = util.find_source_dir(root, current_file)
        path = source / (module + '.tex')
        return path.expanduser().resolve().absolute()

    def path_to_imported_file(self, root: Path) -> Path:
        ''' Returns the path to the module file this gimport points to. '''
        return GImportIntermediateParseTree.build_path_to_imported_module(
            root=root,
            current_file=self.location.path,
            repo=self.repository.text.strip() if self.repository else None,
            module=self.module.text.strip() if self.module else None)

    @classmethod
    def from_environment(cls, e: Environment) -> Optional[GImportIntermediateParseTree]:
        match = GImportIntermediateParseTree.PATTERN.fullmatch(e.env_name)
        if match is None:
            return None
        if len(e.rargs) != 1:
            raise CompilerError(f'Argument count mismatch (expected 1, found {len(e.rargs)}).')
        module = TokenWithLocation.from_node(e.rargs[0])
        unnamed, _ = TokenWithLocation.parse_oargs(e.oargs)
        if len(unnamed) > 1:
            raise CompilerError(f'Optional argument count mismatch (expected at most 1, found {len(e.oargs)})')
        return GImportIntermediateParseTree(
            location=e.location,
            module=module,
            repository=next(iter(unnamed), None),
            export=match.group(1) == 'import',
            asterisk=match.group(2) is not None,
        )

    def __repr__(self):
        try:
            from_ = f' from "{self.path_to_imported_file(Path.cwd())}"'
        except:
            from_ = ''
        access = AccessModifier.PUBLIC if self.export else AccessModifier.PRIVATE
        return f'[{access.value} gimport{"*"*self.asterisk} "{self.module.text}"{from_}]'
