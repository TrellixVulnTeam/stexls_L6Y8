from __future__ import annotations
from typing import Set
from enum import Enum
from stexls.util.location import *

__all__ = [
    'SymbolType',
    'AccessModifier',
    'SymbolIdentifier',
    'Symbol',
    'ModuleSymbol',
    'BindingSymbol',
    'DefSymbol',
]


class SymbolType(Enum):
    SYMBOL='symbol'
    MODULE='module'
    BINDING='binding'
    DIRECTORY='directory'


class AccessModifier(Enum):
    PUBLIC='public'
    PRIVATE='private'


class SymbolIdentifier:
    def __init__(self, identifier: str, symbol_type: SymbolType):
        self.identifier = identifier
        self.symbol_type = symbol_type
    
    @property
    def typed_identifier(self):
        return self.identifier + '/' + self.symbol_type.name
    
    def prepend(self, identifier: str):
        return SymbolIdentifier(identifier + '.' + self.identifier, self.symbol_type)
    
    def append(self, identifier: SymbolIdentifier):
        return identifier.prepend(self.identifier)

    def __hash__(self):
        return hash(self.typed_identifier)

    def __eq__(self, other: SymbolIdentifier):
        if not isinstance(other, SymbolIdentifier):
            return False
        return self.identifier == other.identifier and self.symbol_type == other.symbol_type
    
    def __repr__(self):
        return self.typed_identifier


class Symbol:
    def __init__(self, location: Location, identifier: SymbolIdentifier, parent: SymbolIdentifier):
        """ Initializes a symbol.

        Parameters:
            location: Location of where this symbol is defined.
            identifier: Identifier of this symbol relative to it's parent.
            parent: The identifier of the parent symbol this symbol is scoped to.
        """
        self.identifier: SymbolIdentifier = identifier
        self.parent: SymbolIdentifier = parent
        self.location: Location = location
        self.access_modifier: AccessModifier = AccessModifier.PRIVATE

    @property
    def qualified_identifier(self) -> SymbolIdentifier:
        """ The fully qualified identifier for this symbol.
        
        >>> symbol = Symbol(None, SymbolIdentifier('child', SymbolType.SYMBOL), SymbolIdentifier('parent', SymbolType.MODULE))
        >>> symbol.parent
        'parent/MODULE'
        >>> symbol.identifier'
        'child/SYMBOL'
        >>> symbol.qualified_identifier
        'parent.child/SYMBOL'
        """
        if self.parent is None:
            return self.identifier
        return self.parent.append(self.identifier)

    def __hash__(self):
        return hash(self.qualified_identifier.typed_identifier)
    
    def __eq__(self, other: Symbol):
        if not isinstance(other, Symbol):
            return False
        return self.qualified_identifier == other.qualified_identifier
    
    def __repr__(self):
        return f'[{self.access_modifier.value} Symbol {self.qualified_identifier}]'


class ModuleSymbol(Symbol):
    def __init__(self, location: Location, name: str, full_range: Location):
        super().__init__(location, SymbolIdentifier(name, SymbolType.MODULE), None)
        self.full_range = full_range


class BindingSymbol(Symbol):
    def __init__(self, location: Location, lang: str, module: SymbolIdentifier):
        super().__init__(location, SymbolIdentifier(lang, SymbolType.BINDING), module)
    

class DefSymbol(Symbol):
    def __init__(
        self: DefSymbol,
        location: Location,
        name: str,
        module: SymbolIdentifier,
        noverb: bool = False,
        noverbs: Set[str] = None):
        super().__init__(location, SymbolIdentifier(name, SymbolType.SYMBOL), module)
        self.noverb = noverb
        self.noverbs = noverbs or set()
