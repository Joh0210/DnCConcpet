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