from pathlib import Path
import ast, subprocess
root=Path(__file__).resolve().parents[1]
count=0
for p in root.rglob('*'):
    if any(x in p.parts for x in ('.git','node_modules','.venv','dist','unpackage')): continue
    if p.suffix == '.py': ast.parse(p.read_text(encoding='utf-8'),filename=str(p)); count+=1
    if p.suffix in ('.js','.cjs','.mjs'): subprocess.run(['node','--check',str(p)],check=True,capture_output=True); count+=1
print(f'Syntax checked: {count} files. This does not replace integration tests.')
