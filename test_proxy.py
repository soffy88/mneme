import sys
import importlib.util

installed_path = "/home/soffy/projects/mneme/.venv/lib/python3.12/site-packages/oprim/__init__.py"
spec = importlib.util.spec_from_file_location("installed_oprim", installed_path)
mod = importlib.util.module_from_spec(spec)
sys.modules["installed_oprim"] = mod
spec.loader.exec_module(mod)

print(dir(mod))
