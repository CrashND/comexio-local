"""Import standalone protocol modules without depending on an installed HA runtime."""
import sys
import types
from pathlib import Path
root = Path(__file__).resolve().parents[1] / 'custom_components' / 'comexio_local'
package = types.ModuleType('comexio_local')
package.__path__ = [str(root)]
sys.modules.setdefault('comexio_local',package)
