import os
import sys
import subprocess
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

envs = [
    ("regex_state_machine", "easy,hard"),
    ("sql_fixed_point", "easy,hard"),
    ("spreadsheet_dataflow", "easy,hard"),
    ("css_state_machine", "easy,hard"),
    ("template_interpreter", "easy,hard"),
    ("ci_dependency_graph", "easy,hard")
]

print("Testing generation and compilation of all 6 Weird Machine environments...\n")

failed = False
for env, diff in envs:
    name = f"smoke_test_wm_{env}"
    print(f"Generating {env} ({diff})...")
    subprocess.run(["rm", "-rf", name], cwd=ROOT)
    
    res = subprocess.run(
        [sys.executable, "generate_env.py", "--env", env, "--name", name, "--difficulty", diff, "--seed", "42"],
        cwd=ROOT,
        capture_output=True,
        text=True
    )
    if res.returncode != 0:
        print(f"❌ Generation failed for {env}!")
        print(res.stderr or res.stdout)
        failed = True
        continue
        
    generated_dir = ROOT / name
    if not generated_dir.exists():
        print(f"❌ Generated directory {name} not found!")
        failed = True
        continue
        
    contents = ""
    for p in generated_dir.rglob("*"):
        if p.is_file():
            contents += p.read_text(errors="ignore") + "\n"
            
    unresolved = re.findall(r"%%[A-Z0-9_]+%%", contents)
    if unresolved:
        print(f"❌ Found unresolved placeholders in {env}: {set(unresolved)}")
        failed = True
        
    py_files = [str(p) for p in generated_dir.rglob("*.py")]
    comp_res = subprocess.run([sys.executable, "-m", "py_compile", *py_files], capture_output=True, text=True)
    if comp_res.returncode != 0:
        print(f"❌ Syntax/Compilation error in {env} Python files!")
        print(comp_res.stderr)
        failed = True
    else:
        print(f"✅ {env} generated and compiled successfully!")
        
    subprocess.run(["rm", "-rf", name], cwd=ROOT)

if failed:
    print("\n❌ One or more tests failed.")
    sys.exit(1)
else:
    print("\n🎉 All 6 Weird Machine environments generated and compiled successfully with ZERO syntax errors and unresolved placeholders!")
