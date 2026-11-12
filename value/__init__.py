"""
Expression nodes (VALUEs) built from the JSON AST: the interfaces, the builder
(``value.build``) and the three node kinds.

Deliberately imports nothing: other packages import ``value.InnerFunction``
without loading the node classes, which import ``container`` and ``property``
(that would be an import cycle).
"""
