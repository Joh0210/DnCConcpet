Also grundlegende Idee:

Die Daten mit den Spielinhalten werden ja aus der YAML zu JSONs gemacht, und entsprechend validiert. 
Diese Jsons werden dann zur laufzeit interpretiert.

Um diese Daten dann als Lebende, Funktionstüchtige Objekte, mit Logik und co im System zu nutzen braucht es entsprechend eine Engine.

Grundbaustein einer der Engine ist dabei eine "ComponentDefinition". (Name wurde im Prototyp zu "Instance" umgenannt, kann aber noch überarbeitet werden)
Diese ComponentDefinition stellt dabei jeweis ein Content aus der Datenbank dar. 
Also wird z.B. ein Schwert aus dem JSON eingelsensen und soll nun verwendet werden, dann wird dieses Schwert 
zu einer ComponentDefinition überführt, neben der Definition aus der JSON werden dabei auch entsprechende Speicherdaten übergeben.
Also falls das Schwert z.B. ein Enchantment hat, weil es schon vorher im Spiel vorkam, wird das entsprechend ebenfals mit übergeben.

Der Konstruktur der ComponentDefinition sieht entsprechend ungefähr so aus:

`ComponentDefinition(definition_ID: defintion, data: data)`

Das ComponentDefinition füllt sich dann auf basis der YML Definition anschließend mit "leben".
Aus der definition erfährt es entsprechend welche Properties es besitzt. Diese Properties Instanziiert es entsprechend.
Hierfür hat das Objekt eine entsprechende map, mit Key: id der Property, Value: Propertie Objekt. 
Das Propertie Objekt bekommt entsprechend der Definition einen Datentyp und Startwert, so wie etwaige Flags.

Selbiges entsprechend für unterliegende Container. 

Ganz ganz grob sähe das so aus:
```
constructor(definition_ID: string, data: DbData) {
        this.props = Map<string, Property>
        this.container = Map<string, Container>
        this.id = definition_ID;
        this.sub_ids = string[]
        
        let currentID: string = definition_ID;
        
        while (currentID != null && currentID not in this.sub_ids){
            this.sub_ids.add(currentID);
            const dataObject = getDataDefinitionFromYML(currentID);
            currentID = dataObject.extends;
        }
        
        for (currentID in this.sub_ids starting from last){ //LiFo
            const dataObject = getDataDefinitionFromYML(currentID);
            for prop in dataObject.propertie{
                this.props.add(prop)
            }
            for container in dataObject.container{
                this.container.add(container)
            }
            for set in dataObject.set{
                this.props.adjust(set.id, set.data)
            }
        }

        for i in data{
            setze die daten überall
        }
    }
```

Um entsprechend herauszufinden, ob eine ComponentDefinition in einem anderen Objekt enthalten ist, 
gibt es die get und set containd funktionen, die entsprechend beim Containen aufgerufen, bzw gesetzt werden.
```
public set contained(contained: ICompContainer | null) {
        this.modifiers.removeModifiers();

        this._contained = contained;

        this.remove(); // also calls propertyBuffer.update()

        if (contained !== null) {
            this.modifiers.applyModifiers();
        }
    }

    public get contained(): ICompContainer | null {
        return this.propertyBuffer.readOperation(() => {
            return this._contained;
        });
    }
```

Über eine ähnliche Funktion verfügen die Container, welche mehrere Objkete binhalten können. 
In welchem Objket ein Container liegt, bekommt es beim erzeugen übergeben. Dabei muss ein Objekt perse 
nicht in einem Container liegen, aber ein Container muss immer in einerm Objekt liegen.

Dadurch lässt sich allerdings folgende Funktion erstellen, um das Entity herazufinden, in dem das Objekt ist:

```
 get entity(): Entity | null {
        return bin ich das entity ? this : (this.contained?.container.entity ?? null);
    }
```

Natürlich braucht das Objekt dann noch extra Daten, welceh für die Anzeige und co verwendet werden. Beispielsweise:
```
    public get name(): string {
        return this.id;
    }

    public get description(): string {
        return '';
    }

    public get footer(): string {
        return '';
    }
```

Diese Informationen werden entsprechend aus der YML entnommen (bzw der JSON). Wichtig, diese Informationen können dabei 
referenzen enthalten, wie in dem concept beschrieben.


## Properties
Die Property ist das grundlegende Datenelement. Es repräsnetiert quasi ein Attribut eines Objektes.
Nur hat dieses Attribut erweiterte Logik. Hierbei vor allem das Observer Prinziep.

Aber erstmal zu den Properties selbst. 

Die Default Properity bekommt einen entsprechenden Datentyp und einen startwert übergeben, 
sowie die konfigurationen aus der YML. Der Startwert ist dabei in form eines Strings angegeben. 
Die Konkrete Evaluierung und Verarbeitung dieses Wertes wird von dem Datentyp übernommen und erfolgt dabei vollständig generisch.   

Alle Werte aus der Definition (`default`, `derive`, `set`, Grenzen von `range`, …) sind dabei VALUEs (siehe unten).
Die Property muss also nicht mehr zwischen Literal und Ausdruck unterscheiden: sie hält nur Knoten und ruft `evaluate` auf.
Werte von außen (eine Wahl, ein `write`, ein Parameter, ein Save) sind dagegen reine Daten und gehen über den Datentyp (`parse`).


## Werte (VALUE)
Der Parser übersetzt die Ausdrücke aus der YML (`"2 * level + 1"`) schon vorher in ihren AST und schreibt ihn in die JSON (concept §4.14).
Die Engine parst also nie selbst, sie baut aus jedem JSON-Knoten 1:1 einen Knoten und wertet ihn aus:

```
VALUE = STATIC_VALUE | OPERATION | PATH

STATIC_VALUE  { "value": "3", "type": "int" }             -> StaticValue
OPERATION     { "op": "add", "args": [VALUE, VALUE] }      -> OperationValue
PATH          { "path": ["level"], "type": "int" }         -> PathValue
```

Alle drei sind `InnerFunction`s (`evaluate(ctx)`, `describe()`, `type`), ein Pfad ist zusätzlich ein `TargetPath`.
Gebaut werden sie an genau einer Stelle (`engine.value.build.build_value`). Der `DefinitionStore` cacht sie, sodass jeder JSON-Knoten
pro Spiel nur einmal gebaut wird und alle Instanzen sich den Baum teilen (die Instanz kommt erst über den Kontext dazu).

- **StaticValue:** der Wert wird beim Bauen einmal vom Datentyp geparst, danach nur noch zurückgegeben.
  Ein nackter JSON-Wert (`4`, `true`, `"Battleaxe"`) ist eine Kurzform davon. Er bekommt den Typ seines Slots (z.B. den der Property)
  oder sonst den seiner JSON-Art.
- **PathValue:** eine flache Liste von Schritten. Jeder Schritt macht aus jedem aktuellen Knoten null bis mehrere neue.
  Verzweigungen (`[*]`, mehrere Keys, `is`- und `where`-Filter) brauchen deshalb kein doppeltes `next`, denn der Rest des Pfads gilt für jeden Zweig.
  Ein verzweigter Pfad liefert eine Liste (`list<T>`). Ein Pfad muss seinen Typ angeben, weil ein fehlender Wert
  oder eine leere Liste zur Laufzeit keinen Typ mehr hat. Derselbe Pfad dient auch als Ziel eines Effekts (`resolve`).
- **OperationValue:** löst die Operation beim Bauen anhand der Typen der Argumente auf. Daraus ergibt sich auch der eigene Typ.

## Datentypen und Operationen
Die Operation ist der Einstiegspunkt, nicht der Datentyp. Sie bekommt beliebige Argumenttypen und entscheidet selbst:

1. eine Methode mit `@signature("int", "int", returns="int")`, deren Typen exakt passen,
2. dasselbe mit Erweiterung (`int` passt auf `number`),
3. `generic(types)` für Regeln über alle Typen (`==`, `atLeast` auf allem Geordneten, `? :`),
4. sonst `UnsupportedOperationError` mit der Liste der unterstützten Signaturen.

Das passiert einmal beim Laden (die Typen sind statisch) und wird pro Typ-Kombination gecacht.
Der Ergebnistyp kommt aus der Überladung: `lt(int, int)` ist `bool`, `div(int, int)` ist `number`.
Ein neuer Datentyp braucht keine Änderung an den Operationen, denn die generischen funktionieren sofort.

`and`, `or`, `??` und `? :` sind *lazy*: sie bekommen die Knoten statt der Werte und werten nur aus, was sie brauchen.
Sonst würde `entity != null and entity.level > 3` ohne Entity scheitern, und der nicht genommene Zweig würde zur Abhängigkeit.

Effekte nutzen dieselben Operationen: `add: 2` ist `add(previous, 2)`. Die Auflösung passiert beim Binden an eine Property,
das Ergebnis wird der Property zugewiesen. Die einzige erlaubte Verengung ist dabei `number -> int` (abrunden), damit ein `mul: 0.5` funktioniert.