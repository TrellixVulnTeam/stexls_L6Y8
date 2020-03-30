from __future__ import annotations
from typing import Optional, Tuple, List, Dict, Set
import re
import multiprocessing
from collections import defaultdict
from pathlib import Path
from stexls.util import roman_numerals
from stexls.util.location import Location, Range, Position
from stexls.util.latex.parser import Environment, Node, LatexParser, OArgument
from .exceptions import CompilerException, CompilerWarning
from .symbols import AccessModifier
from stexls.util.latex.exceptions import LatexException

__all__ = (
    'ParsedFile',
    'ParsedEnvironment',
    'parse',
    'TokenWithLocation',
    'Location',
    'Modsig',
    'Modnl',
    'Module',
    'ImportModule',
    'Trefi',
    'Defi',
    'Symi',
    'Symdef',
    'GImport',
    'GStructure',
)

class ParsedFile:
    " An object contains information about symbols, locations, imports of an stex source file. "
    def __init__(self, path: Path):
        self.path = path
        self.modsigs: List[Modsig] = []
        self.modnls: List[Modnl] = []
        self.modules: List[Module] = []
        self.trefis: List[Trefi] = []
        self.defis: List[Defi] = []
        self.syms: List[Symi] = []
        self.symdefs: List[Symdef] = []
        self.importmodules: List[ImportModule] = []
        self.gimports: List[GImport] = []
        self.errors: Dict[Location, List[Exception]] = defaultdict(list)

    @property
    def whole_file(self) -> Location:
        try:
            with open(self.path) as fd:
                content = fd.read()
            lines = content.split('\n')
            num_lines = len(lines)
            len_last_line = len(lines[-1])
            return Location(self.path, Range(Position(0, 0), Position(num_lines - 1, len_last_line - 1)))
        except:
            return Location(self.path, Position(0, 0))


def parse(path: Path) -> ParsedFile:
    parsed_file = ParsedFile(path)
    exceptions: List[Tuple[Location, Exception]] = []
    try:
        parser = LatexParser(path)
        parser.parse()
        exceptions = parser.syntax_errors or []
        parser.walk(lambda env: _visitor(env, parsed_file, exceptions))
    except (CompilerException, LatexException) as ex:
        try:
            with open(path, mode='r') as f:
                lines = f.readlines()
        except:
            lines = []
        last_line = len(lines)
        last_character = len(lines[-1]) if lines else 0
        end_position = Position(last_line, last_character)
        whole_file_range = Range(Position(0, 0), end_position)
        whole_file_location = Location(path, whole_file_range)
        exceptions.append((whole_file_location, ex))
    for loc, e in exceptions:
        parsed_file.errors[loc].append(e)
    return parsed_file

def _visitor(env: Environment, parsed_file: ParsedFile, exceptions: List[Tuple[Location, Exception]]):
    try:
        module = Modsig.from_environment(env)
        if module:
            parsed_file.modsigs.append(module)
            return
        binding = Modnl.from_environment(env)
        if binding:
            parsed_file.modnls.append(binding)
            return
        module = Module.from_environment(env)
        if module:
            parsed_file.modules.append(module)
            return
        trefi = Trefi.from_environment(env)
        if trefi:
            parsed_file.trefis.append(trefi)
            return
        defi = Defi.from_environment(env)
        if defi:
            parsed_file.defis.append(defi)
            return
        sym = Symi.from_environment(env)
        if sym:
            parsed_file.syms.append(sym)
            return
        symdef = Symdef.from_environment(env)
        if symdef:
            parsed_file.symdefs.append(symdef)
            return
        importmodule = ImportModule.from_environment(env)
        if importmodule:
            parsed_file.importmodules.append(importmodule)
            return
        gimport = GImport.from_environment(env)
        if gimport:
            parsed_file.gimports.append(gimport)
            return
    except CompilerException as e:
        exceptions.append((env.location, e))
        return


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


class ParsedEnvironment:
    def __init__(self, location: Location):
        self.location = location


class Modsig(ParsedEnvironment):
    PATTERN = re.compile(r'\\?modsig')
    def __init__(self, location: Location, name: TokenWithLocation):
        super().__init__(location)
        self.name = name
    
    @classmethod
    def from_environment(cls, e: Environment) -> Optional[Modsig]:
        match = Modsig.PATTERN.fullmatch(e.env_name)
        if not match:
            return
        if not e.rargs:
            raise CompilerException('Modsig environment missing required argument: {<module name>}')
        return Modsig(
            e.location,
            TokenWithLocation.from_node(e.rargs[0]))

    def __repr__(self):
        return f'[Modsig name={self.name.text}]'


class Modnl(ParsedEnvironment):
    PATTERN = re.compile(r'\\?(mh)?modnl')
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
        return (self.location.uri.parents[0] / (self.name.text + '.tex')).absolute()
    
    @classmethod
    def from_environment(cls, e: Environment) -> Optional[Modnl]:
        match = Modnl.PATTERN.fullmatch(e.env_name)
        if not match:
            return
        if len(e.rargs) != 2:
            raise CompilerException(f'Argument count mismatch (expected 2, found {len(e.rargs)}).')
        return Modnl(
            e.location,
            TokenWithLocation.from_node(e.rargs[0]),
            TokenWithLocation.from_node(e.rargs[1]),
            mh_mode=match.group(1) == 'mh',
        )

    def __repr__(self):
        mh = 'mh' if self.mh_mode else ''
        return f'[{mh}Modnl {self.name.text} lang={self.lang.text}]'


class Module(ParsedEnvironment):
    PATTERN = re.compile(r'\\?module(\*)?')
    def __init__(
        self,
        location: Location,
        id: TokenWithLocation):
        super().__init__(location)
        self.id = id

    def __repr__(self):
        return f'[Module id="{self.id.text}"]'

    @classmethod
    def from_environment(cls, e: Environment) -> Optional[Module]:
        match = cls.PATTERN.match(e.env_name)
        if match is None:
            return None
        _, named = TokenWithLocation.parse_oargs(e.oargs)
        if 'id' not in named:
            raise CompilerException('Missing named argument: "id"')
        return Module(
            location=e.location,
            id=named.get('id'),
        )


class Defi(ParsedEnvironment):
    PATTERN = re.compile(r'\\?([ma]*)(d|D)ef([ivx]+)(s)?(\*)?')
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
            raise CompilerException(f'Defi argument count mismatch: Expected {i + int(a)} vs actual {len(tokens)}.')

    @property
    def name(self) -> str:
        if self.name_annotation:
            return self.name_annotation.text
        if self.a:
            return '-'.join(t.text for t in self.tokens[1:])
        return '-'.join(t.text for t in self.tokens)

    @classmethod
    def from_environment(cls, e: Environment) -> Optional[Defi]:
        match = Defi.PATTERN.fullmatch(e.env_name)
        if match is None:
            return None
        if not e.rargs:
            raise CompilerException('Argument count mismatch (expected at least 1, found 0).')
        _, named = TokenWithLocation.parse_oargs(e.oargs)
        return Defi(
            location=e.location,
            tokens=list(map(TokenWithLocation.from_node, e.rargs)),
            name_annotation=named.get('name'),
            m='m' in match.group(1),
            a='a' in match.group(1),
            capital=match.group(2) == 'D',
            i=roman_numerals.roman2int(match.group(3)),
            s=match.group(4) is not None,
            asterisk=match.group(5) is not None)

    def __repr__(self):
        return f'[Defi "{self.name}"]'


class Trefi(ParsedEnvironment):
    PATTERN = re.compile(r'\\?([ma]*)(t|T)ref([ivx]+)(s)?(\*)?')
    def __init__(
        self,
        location: Location,
        tokens: List[TokenWithLocation],
        target_annotation: Optional[TokenWithLocation],
        m: bool,
        a: bool,
        capital: bool,
        i: int,
        s: bool,
        asterisk: bool):
        super().__init__(location)
        self.tokens = tokens
        self.target_annotation = target_annotation
        self.m = m
        self.a = a
        self.capital = capital
        self.i = i
        self.s = s
        self.asterisk = asterisk
        if i + int(a) != len(tokens):
            raise CompilerException(f'Trefi argument count mismatch: Expected {i + int(a)} vs. actual {len(tokens)}.')
        has_q = self.target_annotation and '?' in self.target_annotation.text
        if not self.m and has_q:
            raise CompilerException('Question mark syntax "?<symbol>" syntax not allowed in non-mtrefi environments.')
        if self.m and not has_q:
            raise CompilerException('Invalid "mtref" environment: Target symbol must be clarified by using "?<symbol>" syntax.')
    
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
    def from_environment(cls, e: Environment) -> Optional[Trefi]:
        match = Trefi.PATTERN.fullmatch(e.env_name)
        if match is None:
            return None
        if not e.rargs:
            raise CompilerException('Argument count mismatch (expected at least 1, found 0).')
        if len(e.unnamed_args) > 1:
            raise CompilerException(f'Too many unnamed oargs in trefi: Expected are at most 1, found {len(e.unnamed_args)}')
        annotations = (
            TokenWithLocation.from_node(e.unnamed_args[0])
            if e.unnamed_args
            else None
        )
        tokens = list(map(TokenWithLocation.from_node, e.rargs))
        return Trefi(
            location=e.location,
            tokens=tokens,
            target_annotation=annotations,
            m='m' in match.group(1),
            a='a' in match.group(1),
            capital=match.group(2) == 'T',
            i=roman_numerals.roman2int(match.group(3)),
            s=match.group(4) is not None,
            asterisk=match.group(5) is not None,
        )

    def __repr__(self):
        module = f' "{self.module}" ' if self.module else " "
        return f'[Trefi{module}"{self.name}"]'


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


class Symi(ParsedEnvironment):
    PATTERN = re.compile(r'\\?sym([ivx]+)(\*)?')
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
            raise CompilerException(f'Symi argument count mismatch: Expected {i} vs actual {len(tokens)}.')
    
    @property
    def name(self) -> str:
        return '-'.join(token.text for token in self.tokens)

    @classmethod
    def from_environment(cls, e: Environment) -> Optional[Symi]:
        match = Symi.PATTERN.fullmatch(e.env_name)
        if match is None:
            return None
        if not e.rargs:
            raise CompilerException('Argument count mismatch (expected at least 1, found 0).')
        unnamed, named = TokenWithLocation.parse_oargs(e.oargs)
        return Symi(
            location=e.location,
            tokens=list(map(TokenWithLocation.from_node, e.rargs)),
            unnamed_args=unnamed,
            named_args=named,
            i=roman_numerals.roman2int(match.group(1)),
            asterisk=match.group(2) is not None,
        )

    def __repr__(self):
        return f'[Sym{"*"*self.asterisk} "{self.name}"]'


class Symdef(ParsedEnvironment):
    PATTERN = re.compile(r'\\?symdef(\*)?')
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
    def from_environment(cls, e: Environment) -> Optional[Symdef]:
        match = Symdef.PATTERN.fullmatch(e.env_name)
        if match is None:
            return None
        if not e.rargs:
            raise CompilerException('Argument count mismatch: At least one argument required.')
        name = TokenWithLocation.from_node(e.rargs[0])
        unnamed, named = TokenWithLocation.parse_oargs(e.oargs)
        return Symdef(
            location=e.location,
            name=named.get('name', name),
            unnamed_oargs=unnamed,
            named_oargs=named,
            asterisk=match.group(1) is not None,
        )

    def __repr__(self):
        return f'[Symdef{"*"*self.asterisk} "{self.name.text}"]'


class ImportModule(ParsedEnvironment):
    PATTERN = re.compile(r'\\?(import|use)(mh)?module(\*)?')
    def __init__(
        self,
        location: Location,
        module: TokenWithLocation,
        mhrepos: Optional[TokenWithLocation],
        dir: Optional[TokenWithLocation],
        load: Optional[TokenWithLocation],
        path: Optional[TokenWithLocation],
        export: bool,
        mh_mode: bool,
        asterisk: bool):
        super().__init__(location)
        self.module = module
        self.mhrepos = mhrepos
        self.dir = dir
        self.load = load
        self.export = export
        self.mh_mode = mh_mode
        self.asterisk = asterisk
        if path:
            raise CompilerException('ImportModule "path" argument not supported.')
        if mh_mode:
            if not dir:
                raise CompilerException('Invalid argument configuration in importmhmodule: "dir" must be specified.')
            elif load:
                raise CompilerException('Invalid argument configuration in importmhmodule: "load" argument must not be specified.')
        elif mhrepos or dir:
            raise CompilerException('Invalid argument configuration in importmodule: "mhrepos" or "dir" must not be specified.')
        elif not load:
            raise CompilerException('Invalid argument configuration in importmodule: Missing "load" argument.')

    @property
    def path(self) -> Path:
        module_filename = self.module.text.strip() + '.tex'
        if self.load:
            return Path(self.load.text.strip()).absolute() / module_filename
        if self.mhrepos:
            source = Path(self.mhrepos.text.strip()).absolute() / 'source'
            if not source.is_dir():
                raise CompilerException(f'Source dir "{source}" is not a directory.')
        else:
            rel = self.location.uri.absolute().relative_to(Path.cwd())
            source = list(rel.parents)[-4].absolute()
            if source.name != 'source':
                raise CompilerException(f'Invalid implicit path of source dir: "{source}"')
        return source / self.dir.text.strip() / module_filename

    def __repr__(self):
        access = AccessModifier.PUBLIC if self.export else AccessModifier.PRIVATE
        return f'[{access.value} ImportModule "{self.module.text}" from "{self.path}"]'

    @classmethod
    def from_environment(cls, e: Environment) -> Optional[ImportModule]:
        match = ImportModule.PATTERN.fullmatch(e.env_name)
        if match is None:
            return None
        if len(e.rargs) != 1:
            raise CompilerException(f'Argument count mismatch: Expected exactly 1 argument but found {len(e.rargs)}')
        module = TokenWithLocation.from_node(e.rargs[0])
        _, named = TokenWithLocation.parse_oargs(e.oargs)
        return ImportModule(
            location=e.location,
            module=module,
            mhrepos=named.get('mhrepos'),
            dir=named.get('dir'),
            path=named.get('path'),
            load=named.get('load'),
            export=match.group(1) == 'import',
            mh_mode=match.group(2) == 'mh',
            asterisk=match.group(3) == '*'
        )


class GImport(ParsedEnvironment):
    PATTERN = re.compile(r'\\?g(import|use)(\*)?')
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

    @property
    def path(self) -> Path:
        ''' Returns the path to the module file this gimport points to. '''
        filename = self.module.text.strip() + '.tex'
        if self.repository is None:
            return self.location.uri.parents[0].absolute() / filename
        source = Path(self.repository.text.strip()) / 'source'
        return source.absolute() / filename

    @classmethod
    def from_environment(cls, e: Environment) -> Optional[GImport]:
        match = GImport.PATTERN.fullmatch(e.env_name)
        if match is None:
            return None
        if len(e.rargs) != 1:
            raise CompilerException(f'Argument count mismatch (expected 1, found {len(e.rargs)}).')
        module = TokenWithLocation.from_node(e.rargs[0])
        unnamed, _ = TokenWithLocation.parse_oargs(e.oargs)
        if len(unnamed) > 1:
            raise CompilerException(f'Optional argument count mismatch (expected at most 1, found {len(e.oargs)})')
        return GImport(
            location=e.location,
            module=module,
            repository=next(iter(unnamed), None),
            export=match.group(1) == 'import',
            asterisk=match.group(2) is not None,
        )

    def __repr__(self):
        access = AccessModifier.PUBLIC if self.export else AccessModifier.PRIVATE
        return f'[{access.value} gimport{"*"*self.asterisk} "{self.module.text}" from "{self.path}"]'


class GStructure(ParsedEnvironment):
    PATTERN = re.compile(r'\\?gstructure(\*)?')
    def __init__(self, location: Location, asterisk: bool):
        super().__init__(location)
        self.asterisk = asterisk

    @classmethod
    def from_environment(cls, e: Environment) -> Optional[GStructure]:
        match = GStructure.PATTERN.fullmatch(e.env_name)
        if match is None:
            return None
        raise NotImplementedError
