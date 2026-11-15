#!/usr/bin/env python3
"""Example usage demo script for env-audit."""
import pathlib
import sys
def main():
    print("--- env-audit Demo ---")
    tmp_dir = pathlib.Path("demo_project")
    tmp_dir.mkdir(exist_ok=True)
    # 1. Create sample code reading an unannounced environment variable
    app_py = tmp_dir / "main.py"
    app_py.write_text("""
import os
DATABASE_URL = os.environ["DATABASE_URL"]
API_KEY = os.getenv("API_KEY", "default-key")
""")
    # 2. Create incomplete .env.example
    example_env = tmp_dir / ".env.example"
    example_env.write_text("API_KEY=dummy\n")
    # 3. Create active .env
    active_env = tmp_dir / ".env"
    active_env.write_text("DATABASE_URL=postgres://localhost/db\nAPI_KEY=secret-123\n")
    print(f"Created temporary demo project in {tmp_dir}/")
    print("Running programmatic reconciliation...")
    sys.path.insert(0, str(pathlib.Path(".").resolve()))
    import env_audit
    
    usages = env_audit.scan_python_file(app_py)
    ex_env = env_audit.parse_dotenv(example_env.read_text())
    act_env = env_audit.parse_dotenv(active_env.read_text())
    findings = env_audit.reconcile(
        code_usages=usages,
        example_env=ex_env,
        active_env=act_env,
        ci_keys=set(),
        ignore_keys=env_audit.DEFAULT_IGNORE,
        severity_map={}
    )
    print("\nFindings discovered:")
    for f in findings:
        print(f"  [{f.code}] ({f.severity.upper()}) {f.message}")
    print("\nDemo completed successfully!")
if __name__ == "__main__":
    main()