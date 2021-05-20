from __future__ import annotations

import uuid
from enum import Enum, Flag
from typing import Callable, Dict, Iterator, List, Optional, Set, Tuple, Union

from stexls import vscode
from stexls.stex.exceptions import (DuplicateSymbolDefinedError,
                                    InvalidSymbolRedifinitionException)
from stexls.util.format import format_enumeration

from .reference_type import ReferenceType

__all__ = [
    'AccessModifier',
    'ModuleType',
    'DefType',
    'Symbol',
    'ModuleSymbol',
    'BindingSymbol',
    'DefSymbol',
    'RootSymbol',
    'ScopeSymbol',
]


class AccessModifier(Flag):
    PUBLIC = 0
    PROTECTED = 1
    PRIVATE = 3  # private is 3 so that it can be treaded as stronger than protected and public in comparisions


class ModuleType(Enum):
    ' For module symbols: Used to remember which latex environment created this module. '
    MODSIG = 'modsig'
    MODULE = 'module'


class DefType(Enum):
    ' For definitions: Used to remember which latex environment created this module (e.g.: defii{}, symii{}, symdef{} or drefi{}) '
    DEF = 'def'
    DREF = 'dref'
    SYMDEF = 'symdef'
    SYM = 'sym'


class Symbol:
    def __init__(
            self,
            location: vscode.Location,
            name: str):
        """ Initializes a symbol.

        Parameters:
            location: Location of where this symbol is defined.
                The range of this location should only contain the text, which is selected
                when revealing this symbol.
            name: Identifier of this symbol relative to it's parent.
        """
        assert location is not None, "Invalid symbol location"
        assert isinstance(name, str), "Member 'name' is not of type str"
        self.name = name
        self.parent: Optional[Symbol] = None
        self.children: Dict[str, List[Symbol]] = dict()
        self.location = location
        self.access_modifier: AccessModifier = AccessModifier.PUBLIC

    def get_symbols_for_lookup(self) -> Dict[str, Tuple[Symbol, ...]]:
        """ Returns a dictionary of symbol name to tuple of all symbols with that name.
        The returned symbols are all symbols that are available with a lookup operation on
        `self`.

        Returns:
            Dict[str, Tuple[Symbol, ...]]: Dictionary of symbol name to immuatable tuple of all the symbols with that name,
            contained in `self` as a child or as child in any ancestor of `self`.
        """
        values = {
            name: tuple(value)
            for name, value
            in self.children.items()
        }
        if self.parent:
            pname = self.parent.name
            values[pname] = (self.parent, *values.get(pname, ()))
            for new_name, new_values in self.parent.get_symbols_for_lookup().items():
                values[new_name] = values.get(new_name, ()) + new_values
        return values

    def copy(self, parent: Symbol) -> Symbol:
        ' Creates a full copy of this symbol. Including private and not-exported symbols. '
        cpy = self.shallow_copy()
        cpy.parent = parent
        for name, symbols in self.children.items():
            cpy.children[name] = [symbol.copy(self) for symbol in symbols]
        return cpy

    @property
    def reference_type(self) -> ReferenceType:
        ' Returns the valid type of a reference that addresses this symbol. '
        return ReferenceType.UNDEFINED

    def import_from(self, module: Symbol):
        ' Imports the symbols from <source> into this symbol table. '
        cpy = module.shallow_copy()
        self.add_child(cpy)
        for alts in module.children.values():
            # TODO: Import behaviour of 'import scopes' like 'frame' and 'omtext' --> What to do with defis inside these?
            for child in alts:
                if child.access_modifier != AccessModifier.PUBLIC:
                    continue
                if isinstance(child, ModuleSymbol):
                    try:
                        self.import_from(child)
                    except (InvalidSymbolRedifinitionException, DuplicateSymbolDefinedError):
                        # TODO: Make sure these errors can be ignored
                        pass
                elif isinstance(child, DefSymbol):
                    # TODO: Correct add_child behaviour depending on the context the symbol was imported under
                    try:
                        cpy.add_child(child.shallow_copy(), len(alts) > 1)
                    except (InvalidSymbolRedifinitionException, DuplicateSymbolDefinedError):
                        # TODO: What to do in case of error? Should this be impossible?
                        pass

    def get_visible_access_modifier(self) -> AccessModifier:
        ' Gets the access modifier visible from the symbol tree root. '
        if self.parent and self.access_modifier != AccessModifier.PRIVATE:
            return self.parent.get_visible_access_modifier() | self.access_modifier
        return self.access_modifier

    def flat(self) -> Iterator[Symbol]:
        ' Returns a flattened iterator over all symbols inside this symbol table. '
        for alts in self.children.values():
            for child in alts:
                yield child
                yield from child

    def __iter__(self) -> Iterator[Symbol]:
        ' Iterates over all child symbols. '
        # TODO: Remove this because its unsafe -> Add explicit .flat() method
        return self.flat()

    def is_parent_of(self, other: Symbol) -> bool:
        ' Returns true if this symbol is a parent of the other symbol. '
        parent = other.parent
        while parent is not None:
            if self == parent:
                return True
            parent = parent.parent
        return False

    def shallow_copy(self) -> Symbol:
        ' Creates a shallow copy of this symbol and it\'s parameterization. Does not create a copy of the symbol table! '
        raise NotImplementedError

    @property
    def depth(self) -> int:
        if self.parent:
            return self.parent.depth + 1
        return 0

    def traverse(self, enter: Callable[[Symbol], None], exit=None):
        ' Traverse the symbol hierarchy. Executes enter and exit for each symbol. '
        if enter:
            enter(self)
        for child_alternatives in self.children.values():
            for child in child_alternatives:
                child.traverse(enter, exit)
        if exit:
            exit(self)

    @property
    def qualified(self) -> Tuple[str, ...]:
        if self.parent:
            return (*self.parent.qualified, self.name)
        return (self.name,)

    def get_current_module(self) -> Optional[ModuleSymbol]:
        ' Find the first parent ModuleSymbol. '
        if self.parent:
            return self.parent.get_current_module()
        return None

    def get_current_module_name(self) -> Optional[str]:
        module = self.get_current_module()
        if module is not None:
            return module.name
        binding = self.get_current_binding()
        if binding is not None:
            return binding.name
        return None

    def get_current_binding(self) -> Optional[BindingSymbol]:
        ' Find the first parent BindingSymbol. '
        if self.parent:
            return self.parent.get_current_binding()
        return None

    def add_child(self, child: Symbol, alternative: bool = False):
        """ Adds a child symbol.

        Parameters:
            child: Child to add.
            alternative: If set to true, allows for duplicate definitions.

        Raises:
            If the child already has a parent or rises DuplicateSymbolDefinedError
            if a symbol with the same name is already defined and alternatives are not allowed.
            If alternatives are allowed: Raises InvalidSymbolRedifinitionException if the alternative's signature
            does not match all previous definitions (e.g. once with noverb and one time without noverb annotation)
        """
        if child.parent:
            raise ValueError(
                'Attempting to add child symbol which already has a parent.')
        if child.name in self.children:
            for prev_child in self.children[child.name]:
                # TODO: Is the following too broad? In general, we can have symbols of different types with the same name and they should be treated independently.
                if child.reference_type != prev_child.reference_type:
                    continue
                if not alternative:
                    raise DuplicateSymbolDefinedError(
                        child.name, prev_child.location)
                if not isinstance(prev_child, type(child)):
                    raise InvalidSymbolRedifinitionException(
                        child.name, prev_child.location, f'Symbol type mismatch: {type(child)} vs. {type(prev_child)}')
                if isinstance(child, DefSymbol):
                    if child.def_type != prev_child.def_type:
                        raise InvalidSymbolRedifinitionException(
                            child.name, prev_child.location, f'Definition types do not match: {child.def_type} vs. {prev_child.def_type}')
                    if child.noverb != prev_child.noverb:
                        a = 'noverb' if child.noverb else 'not noverb'
                        b = 'noverb' if prev_child.noverb else 'not noverb'
                        raise InvalidSymbolRedifinitionException(
                            child.name, prev_child.location, f'Noverb signatures do not match to previous definition: {a} vs. {b}')
                    if len(child.noverbs) != len(prev_child.noverbs) or not all(a == b for a, b in zip(child.noverbs, prev_child.noverbs)):
                        a = format_enumeration(child.noverbs, last='and')
                        b = format_enumeration(prev_child.noverbs, last='and')
                        raise InvalidSymbolRedifinitionException(
                            child.name, prev_child.location, f'Noverb signatures do not match to previous definition: {a} vs. {b}')
        child.parent = self
        self.children.setdefault(child.name, []).append(child)

    def lookup(
            self,
            identifier: Union[str, List[str], Tuple[str, ...]],
            accepted_ref_type: Optional[ReferenceType] = None) -> List[Symbol]:
        """ Symbol lookup searches for symbols with a given identifier in this symbol's children and all ancestor's children.
        A "lookup" is search operation that can change the root to a parent.

        Parameters:
            identifier (Union[str, List[str], Tuple[str, ...]]): Symbol identifier.
            accepted_ref_type (ReferenceType, optional): Optional reference type. Others will be filtered out.

        Returns:
            All symbols with the specified id.
        """
        # Force id to be a list
        if isinstance(identifier, str):
            identifier = [identifier]
        # Find the other identifiers in the subbranches of the children
        resolved_symbols = [
            symbol
            # Lookup the root identifier
            for resolved_root in self.children.get(identifier[0], [])
            # Resolve the rest of the identifier
            for symbol in resolved_root.find(identifier[1:])
            if not accepted_ref_type or symbol.reference_type in accepted_ref_type
        ]
        # If nothing was resolved yet, try to search for the first symbol inside the parents
        if not resolved_symbols:
            # Lookup the identifier in parent tree
            if self.parent and not isinstance(self, (ModuleSymbol, BindingSymbol)):
                # TODO: Is preventing lookup through modules enough? Or is there a more generic way to describe this lookup behaviour?
                return self.parent.lookup(identifier, accepted_ref_type)
            # This is a failsafe in case the current module is referenced inside itself
            # This is needed because else referencing another module inside the same file might be possible
            # depending on the order of declaration, but not allowed!
            # This also must be the last check else referencing nested symbols with the same name is impossible
            if self.name == identifier[0]:
                return self.find(identifier[1:])
        return resolved_symbols

    def find(self, identifier: Union[str, List[str], Tuple[str, ...]]) -> List[Symbol]:
        """ Searches the identified symbol in sub-trees of this symbols' children.

        Parameters:
            identifier: Identifier of the child symbol.

        Returns:
            All symbols with the specified identifier.
        """
        if not identifier:
            return [self]
        if isinstance(identifier, str):
            identifier = [identifier]
        children = self.children.get(identifier[0], [])
        if len(identifier) > 1:
            return [
                resolved
                for child in children
                for resolved in child.find(identifier[1:])
            ]
        return children

    def __repr__(self):
        return f'[{self.access_modifier.name} Symbol {self.name}]'


class ModuleSymbol(Symbol):
    UNNAMED_MODULE_COUNT = 0

    def __init__(
            self,
            module_type: ModuleType,
            location: vscode.Location,
            name: str = None):
        """ New module signature symbol.

        Parameters:
            module_type: The latex environment type used to define this symbol.
            location: Location at which the module symbol is created.
            name: Name of the module. If no name is provided, a name will be atomatically created.
        """
        super().__init__(
            location, name or f'__MODULESYMBOL#{ModuleSymbol.UNNAMED_MODULE_COUNT}__')
        if not name:
            ModuleSymbol.UNNAMED_MODULE_COUNT += 1
            self.access_modifier = AccessModifier.PRIVATE
        self.module_type = module_type

    @property
    def reference_type(self) -> ReferenceType:
        if ModuleType.MODSIG == self.module_type:
            return ReferenceType.MODSIG
        if ModuleType.MODULE == self.module_type:
            return ReferenceType.MODULE
        raise ValueError(self.module_type)

    def shallow_copy(self) -> ModuleSymbol:
        cpy = ModuleSymbol(self.module_type, self.location.copy(), self.name)
        cpy.access_modifier = self.access_modifier
        return cpy

    def get_current_module(self) -> ModuleSymbol:
        return self

    def __repr__(self):
        return f'[{self.access_modifier.name} ModuleSymbol "{self.name}"/{self.module_type.name} at {self.location.range.start.format()}]'


class DefSymbol(Symbol):
    def __init__(
            self,
            def_type: DefType,
            location: vscode.Location,
            name: str,
            noverb: bool = False,
            noverbs: Set[str] = None,
            access_modifier: AccessModifier = AccessModifier.PUBLIC):
        """ New Verb symbol.

        Parameters:
            module:
            def_type: Latex environment used to define this symbol.
            noverb: If True, then this verb symbol should not have any references in any language.
            noverbs: Set of languages this symbol should not be referenced from.
        """
        super().__init__(location, name)
        self.def_type = def_type
        self.noverb = noverb
        self.noverbs = noverbs or set()
        self.access_modifier = access_modifier

    @property
    def reference_type(self) -> ReferenceType:
        if self.def_type == DefType.DEF:
            return ReferenceType.DEF
        if self.def_type == DefType.DREF:
            return ReferenceType.DREF
        if self.def_type == DefType.SYM:
            return ReferenceType.SYM
        if self.def_type == DefType.SYMDEF:
            return ReferenceType.SYMDEF
        raise ValueError(self.def_type)

    def __repr__(self):
        return f'[{self.access_modifier.name} DefSymbol "{self.name}"/{self.def_type.name} at {self.location.range.start.format()}]'

    def shallow_copy(self) -> DefSymbol:
        return DefSymbol(
            self.def_type,
            self.location.copy(),
            self.name,
            self.noverb,
            self.noverbs.copy(),
            self.access_modifier)


class BindingSymbol(Symbol):
    def __init__(self, location: vscode.Location, module: str, lang: str):
        super().__init__(location, module)
        self.lang = lang

    @property
    def reference_type(self) -> ReferenceType:
        return ReferenceType.BINDING

    def get_current_binding(self) -> BindingSymbol:
        return self

    def shallow_copy(self) -> BindingSymbol:
        cpy = BindingSymbol(self.location.copy(), self.name, self.lang)
        cpy.access_modifier = self.access_modifier
        return cpy

    def __repr__(self):
        return f'[{self.access_modifier.name} BindingSymbol {self.name}.{self.lang} at {self.location.range.start.format()}]'


class RootSymbol(Symbol):
    ROOT_NAME = '__root__'

    def __init__(self, location: vscode.Location):
        super().__init__(location, RootSymbol.ROOT_NAME)

    @property
    def qualified(self) -> Tuple[str, ...]:
        return ()

    def shallow_copy(self):
        return RootSymbol(self.location.copy())


class ScopeSymbol(Symbol):
    count = 0

    def __init__(self, location: vscode.Location, name: str = 'UNNAMED_SCOPE'):
        ScopeSymbol.count += 1
        # Add uuid because of duplicate symbols during multiple runs
        # The odds of matching up count and uuid between restarts
        # of the program are low.
        self.uuid = uuid.uuid4().hex
        super().__init__(
            location, f'__{name}#{ScopeSymbol.count}@{self.uuid}__')

    def __repr__(self):
        return f'[{self.access_modifier.name} Scope "{self.name}" at {self.location.range.start.format()}]'

    def shallow_copy(self) -> ScopeSymbol:
        cpy = ScopeSymbol(self.location.copy(), name=self.name)
        cpy.access_modifier = self.access_modifier
        return cpy
