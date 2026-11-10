# This is a sample Python script.
from datatype.datatypes.TypeBool import TypeBool
from datatype.datatypes.TypeInt import TypeInt
from datatype.operations.AddOperation import AddOperation
from datatype.operations.MulOperation import MulOperation

# Press Umschalt+F10 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.




# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    print(TypeBool.instance().useOperation(MulOperation().instance(), True, True, True))


