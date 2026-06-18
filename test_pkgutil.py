import pkgutil
import sys
sys.path.insert(0, ".") # make sure local is first
import oprim
print(oprim.__path__)
print(dir(oprim))
