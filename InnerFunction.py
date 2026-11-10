""" Quasi eine Funktion welche immer genau auf einen Wert resolved.
Diese Funktion bekommt dabei die aktuelle Instanz übergeben. Kann so also auf die Properties der Instanz zugreifen.

Durch die entity Funktion der Instanz kann es auch auf das entity zugreifen, sofern es containd ist.
Hierbei muss allerdings auf None Geachtet werden
"""
class InnerFunction:
    pass


"""
Relevant für auswertungen und bestimmung von Targets bei Manipulationen und co.

Ein TargetPath ist eine Liste von Schritten, die man braucht um vom aktuellen Punkt zum Target zu kommen. 
Ein Target Path führt dabei immer zu zu Properties.

Es ist möglich, dass er zu einer oder auch zu mehreren Properties führt. Hierfür gibt es allerdings verschiedene Path typen.

Der Pfad ist dabei wie folgt aufgebaut: Der Pfad besteht aus dem aktuellen Step, mit Optionen zur verzweigung und co, und einem weiteren Target Path. 
"""
class TargetPath:
    pass


