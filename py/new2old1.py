import ast
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

if sys.version_info < (3, 11):
    import tomli as tomllib
else:
    import tomllib


def load_pyproject(root: Path) -> dict[str, Any]:
    path = root / "pyproject.toml"
    if not path.exists():
        print("Error: No pyproject.toml found in this directory.")
        sys.exit(1)
    with path.open("rb") as f:
        return tomllib.load(f)


def get_backend(config: dict[str, Any]) -> str:
    return config.get("build-system", {}).get("build-backend", "")


def get_project(config: dict[str, Any]) -> dict[str, Any]:
    project = config.get("project", {})
    if not project:
        print("Error: No [project] table found in pyproject.toml.")
        sys.exit(1)
    return project


def get_name(project: dict[str, Any], config: dict[str, Any] | None = None) -> str:
    name = project.get("name")
    if not name and config is not None:
        name = config.get("tool", {}).get("poetry", {}).get("name")
    if not name:
        print("Error: Project name is missing from pyproject.toml.")
        sys.exit(1)
    return name


def extract_authors(project: dict[str, Any], config: dict[str, Any] | None = None) -> tuple[str, str]:
    authors_list = project.get("authors") or project.get("maintainers") or []
    if not authors_list and config is not None:
        authors_list = config.get("tool", {}).get("poetry", {}).get("authors", [])
    names: list[str] = []
    emails: list[str] = []
    for a in authors_list:
        if isinstance(a, dict):
            if "name" in a:
                names.append(a["name"])
            if "email" in a:
                emails.append(a["email"])
        elif isinstance(a, str):
            if "<" in a and ">" in a:
                n, e = a.split("<", 1)
                names.append(n.strip())
                emails.append(e.replace(">", "").strip())
            else:
                names.append(a.strip())
    return ", ".join(names), ", ".join(emails)


def extract_readme(project: dict[str, Any], config: dict[str, Any] | None = None) -> str:
    readme = project.get("readme")
    if readme is None and config is not None:
        readme = config.get("tool", {}).get("poetry", {}).get("readme", "")
    if isinstance(readme, dict):
        return readme.get("file", "")
    return readme or ""


def extract_license(project: dict[str, Any], config: dict[str, Any] | None = None) -> str:
    license_val = project.get("license", "")
    if isinstance(license_val, dict):
        return license_val.get("text", "")
    if not license_val and config is not None:
        return config.get("tool", {}).get("poetry", {}).get("license", "")
    return license_val


def extract_dynamic(project: dict[str, Any]) -> list[str]:
    return project.get("dynamic", [])


def extract_dependencies(
    project: dict[str, Any], config: dict[str, Any] | None = None
) -> tuple[list[str], dict[str, list[str]], str]:
    install_requires: list[str] = project.get("dependencies", [])
    extras_require: dict[str, list[str]] = project.get("optional-dependencies", {})
    python_requires: str = project.get("requires-python", "")

    if config is None:
        return install_requires, extras_require, python_requires

    poetry = config.get("tool", {}).get("poetry", {})
    if not install_requires and "dependencies" in poetry:
        poetry_deps = poetry["dependencies"]
        if "python" in poetry_deps:
            python_requires = poetry_deps["python"]
        install_requires = clean_poetry_deps(poetry_deps)
    if "extras" in poetry and not extras_require:
        for group, items in poetry["extras"].items():
            extras_require[group] = [str(i) for i in items]
    return install_requires, extras_require, python_requires


def clean_poetry_deps(deps_dict: dict[str, Any]) -> list[str]:
    reqs: list[str] = []
    if not deps_dict:
        return reqs
    for pkg, constraint in deps_dict.items():
        if pkg.lower() == "python":
            continue
        if isinstance(constraint, dict):
            version_str = constraint.get("version", "")
            if constraint.get("optional", False):
                continue
        else:
            version_str = constraint

        if isinstance(version_str, str):
            if version_str.startswith("^"):
                ver = version_str[1:]
                parts = ver.split(".")
                if parts[0] == "0":
                    next_minor = int(parts[1]) + 1 if len(parts) > 1 else 1
                    version_str = f">={ver}, <0.{next_minor}.0"
                else:
                    next_major = int(parts[0]) + 1
                    version_str = f">={ver}, <{next_major}.0.0"
            elif version_str.startswith("~"):
                ver = version_str[1:]
                parts = ver.split(".")
                next_minor = int(parts[1]) + 1 if len(parts) > 1 else 1
                version_str = f">={ver}, <{parts[0]}.{next_minor}.0"

        reqs.append(f"{pkg} {version_str}".strip())
    return reqs


def extract_version_from_lines(path: Path, keys: tuple[str, ...] = ("__version__",)) -> str | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                for key in keys:
                    if stripped.startswith(key):
                        try:
                            return ast.literal_eval(stripped.split("=", 1)[1].strip())
                        except Exception:
                            pass
    except Exception:
        pass
    return None


def git_describe() -> str | None:
    try:
        out = subprocess.check_output(["git", "describe", "--tags", "--always"]).decode("utf-8").strip()
        return out or None
    except Exception:
        return None


def normalize_name(name: str) -> str:
    return name.replace("-", "_")


def build_setup_module(
    name: str,
    version_expr: str,
    description_expr: str,
    author_name: str,
    author_email: str,
    readme_path: str,
    license_str: str,
    python_requires: str,
    classifiers: list[str],
    install_requires: list[str],
    extras_require: dict[str, list[str]],
    packages_expr: str,
    package_dir_expr: str,
    py_modules: list[str],
    dynamic_extraction: str,
) -> str:
    return f"""import os
import sys
from setuptools import setup, find_packages

{description_expr}
version = {version_expr}

{dynamic_extraction}

setup(
    name={name!r},
    version=version,
    author={author_name!r},
    author_email={author_email!r},
    description=description,
    long_description=open({readme_path!r}).read() if {readme_path!r} and os.path.exists({readme_path!r}) else "",
    long_description_content_type="text/markdown" if str({readme_path!r}).endswith(".md") else "text/x-rst",
    license={license_str!r},
    python_requires={python_requires!r},
    classifiers={classifiers!r},
    install_requires={install_requires!r},
    extras_require={extras_require!r},
    packages={packages_expr},
    package_dir={package_dir_expr},
    py_modules={py_modules!r},
    zip_safe=False,
)
"""


def handle_flit(config: dict[str, Any], root: Path, project: dict[str, Any], name: str) -> str:
    backend = get_backend(config)
    if "flit_core" not in backend:
        print(f"Warning: This project uses '{backend}', not flit_core. Proceeding anyway...")

    import_name = config.get("tool", {}).get("flit", {}).get("module", {}).get("name", name)
    author_name, author_email = extract_authors(project)
    dynamic_fields = extract_dynamic(project)
    readme_path = extract_readme(project)
    license_str = extract_license(project)
    install_requires, extras_require, _ = extract_dependencies(project)
    classifiers = project.get("classifiers", [])
    python_requires = project.get("requires-python", "")

    dynamic_extraction = f"""
def extract_metadata():
    global version, description
    import ast
    target = None
    if os.path.exists({import_name + ".py"!r}):
        target = {import_name + ".py"!r}
    elif os.path.exists(os.path.join({import_name!r}, "__init__.py")):
        target = os.path.join({import_name!r}, "__init__.py")
    if not target:
        return
    with open(target, "r", encoding="utf-8") as f:
        content = f.read()
    if "description" in {dynamic_fields!r}:
        try:
            doc = ast.get_docstring(ast.parse(content))
            if doc:
                description = doc.split("\\n")[0].strip()
        except Exception:
            pass
    if "version" in {dynamic_fields!r}:
        try:
            for line in content.splitlines():
                if line.startswith("__version__"):
                    version = ast.literal_eval(line.split("=", 1)[1].strip())
                    break
        except Exception:
            pass

extract_metadata()
"""

    return build_setup_module(
        name=name,
        version_expr='"0.1.0"',
        description_expr='description = ""',
        author_name=author_name,
        author_email=author_email,
        readme_path=readme_path,
        license_str=license_str,
        python_requires=python_requires,
        classifiers=classifiers,
        install_requires=install_requires,
        extras_require=extras_require,
        packages_expr="find_packages()",
        package_dir_expr="{}",
        py_modules=[import_name],
        dynamic_extraction=dynamic_extraction,
    )


def handle_hatch(config: dict[str, Any], root: Path, project: dict[str, Any], name: str) -> str:
    backend = get_backend(config)
    if "hatchling" not in backend:
        print(f"Warning: This project uses '{backend}', not hatchling. Proceeding anyway...")

    author_name, author_email = extract_authors(project)
    dynamic_fields = extract_dynamic(project)
    readme_path = extract_readme(project)
    license_str = extract_license(project)
    install_requires, extras_require, python_requires = extract_dependencies(project)
    classifiers = project.get("classifiers", [])
    description = project.get("description", "")

    wheel_config = config.get("tool", {}).get("hatch", {}).get("build", {}).get("targets", {}).get("wheel", {})
    custom_packages = wheel_config.get("packages", [])

    if not custom_packages:
        custom_includes = config.get("tool", {}).get("hatch", {}).get("build", {}).get("include", [])
        py_modules = [pkg.replace(".py", "") for pkg in custom_includes if pkg.endswith(".py")]
    else:
        py_modules = []

    hatch_version_path = config.get("tool", {}).get("hatch", {}).get("version", {}).get("path", "")
    uses_vcs = any("hatch-vcs" in req for req in config.get("build-system", {}).get("requires", []))

    norm = normalize_name(name)

    if custom_packages:
        packages_expr = repr(custom_packages)
        package_dir_expr = "{}"
    else:
        packages_expr = 'find_packages(where="src") if os.path.exists("src") else find_packages()'
        package_dir_expr = '{"": "src"} if os.path.exists("src") else {}'

    dynamic_extraction = f"""
def extract_metadata():
    global version
    if "version" not in {dynamic_fields!r}:
        return
    if {uses_vcs}:
        try:
            import subprocess
            v = subprocess.check_output(["git", "describe", "--tags", "--always"]).decode("utf-8").strip()
            if v:
                version = v
                return
        except Exception:
            pass
    explicit = {hatch_version_path!r}
    search = [explicit] if explicit else [
        {norm + "/__about__.py"!r},
        {norm + "/__init__.py"!r},
        {"src/" + norm + "/__about__.py"!r},
        {"src/" + norm + "/__init__.py"!r},
    ]
    import ast
    for path in search:
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("__version__"):
                        try:
                            version = ast.literal_eval(line.split("=", 1)[1].strip())
                            return
                        except Exception:
                            pass

extract_metadata()
"""

    return build_setup_module(
        name=name,
        version_expr='"0.1.0"',
        description_expr=f"description = {description!r}",
        author_name=author_name,
        author_email=author_email,
        readme_path=readme_path,
        license_str=license_str,
        python_requires=python_requires,
        classifiers=classifiers,
        install_requires=install_requires,
        extras_require=extras_require,
        packages_expr=packages_expr,
        package_dir_expr=package_dir_expr,
        py_modules=py_modules,
        dynamic_extraction=dynamic_extraction,
    )


def handle_maturin(config: dict[str, Any], root: Path, project: dict[str, Any], name: str) -> str:
    backend = get_backend(config)
    if "maturin" not in backend:
        print(f"Warning: This project uses '{backend}', not maturin. Proceeding anyway...")

    author_name, author_email = extract_authors(project)
    dynamic_fields = extract_dynamic(project)
    readme_path = extract_readme(project)
    license_str = extract_license(project)
    install_requires, extras_require, python_requires = extract_dependencies(project)
    classifiers = project.get("classifiers", [])
    description = project.get("description", "")

    python_source = config.get("tool", {}).get("maturin", {}).get("python-source", "")

    dynamic_extraction = f"""
def extract_metadata():
    global version
    if "version" not in {dynamic_fields!r}:
        return
    if os.path.exists("Cargo.toml"):
        try:
            if sys.version_info < (3, 11):
                import tomli as tl
            else:
                import tomllib as tl
            with open("Cargo.toml", "rb") as f:
                cargo = tl.load(f)
            v = cargo.get("package", {{}}).get("version", "")
            if v:
                version = v
                return
        except Exception:
            pass

extract_metadata()

python_root = {python_source!r}
if python_root:
    packages = find_packages(where=python_root)
    package_dir = {{"": python_root}}
elif os.path.exists("src"):
    packages = find_packages(where="src")
    package_dir = {{"": "src"}}
else:
    packages = find_packages()
    package_dir = {{}}
"""

    return build_setup_module(
        name=name,
        version_expr=repr(project.get("version", "0.1.0")),
        description_expr=f"description = {description!r}",
        author_name=author_name,
        author_email=author_email,
        readme_path=readme_path,
        license_str=license_str,
        python_requires=python_requires,
        classifiers=classifiers,
        install_requires=install_requires,
        extras_require=extras_require,
        packages_expr="packages",
        package_dir_expr="package_dir",
        py_modules=[],
        dynamic_extraction=dynamic_extraction,
    )


def handle_meson(config: dict[str, Any], root: Path, project: dict[str, Any], name: str) -> str:
    backend = get_backend(config)
    if "mesonpy" not in backend:
        print(f"Warning: This project uses '{backend}', not mesonpy. Proceeding anyway...")

    author_name, author_email = extract_authors(project)
    dynamic_fields = extract_dynamic(project)
    readme_path = extract_readme(project)
    license_str = extract_license(project)
    install_requires, extras_require, python_requires = extract_dependencies(project)
    classifiers = project.get("classifiers", [])
    description = project.get("description", "")

    meson_tool_meta = config.get("tool", {}).get("meson-python", {}).get("metadata", {})
    version_provider = (
        meson_tool_meta.get("version", {}).get("provider", "")
        if isinstance(meson_tool_meta.get("version"), dict)
        else ""
    )

    dynamic_extraction = f"""
def extract_metadata():
    global version
    if "version" not in {dynamic_fields!r}:
        return
    if os.path.exists("meson.build"):
        try:
            with open("meson.build", "r", encoding="utf-8") as f:
                content = f.read()
            m = re.search(r"project\\s*\\([^)]*version\\s*:\\s*['\\"]([^'\\"]+)['\\"]", content, re.IGNORECASE)
            if m:
                version = m.group(1)
                return
        except Exception:
            pass
    provider = {version_provider!r}
    if provider and "DiscoverVersion" in provider:
        try:
            import subprocess
            v = subprocess.check_output(["git", "describe", "--tags", "--always"]).decode("utf-8").strip()
            if v:
                version = v
                return
        except Exception:
            pass

extract_metadata()
"""

    packages_expr = 'find_packages(where="src") if os.path.exists("src") else find_packages()'
    package_dir_expr = '{"": "src"} if os.path.exists("src") else {}'

    return build_setup_module(
        name=name,
        version_expr=repr(project.get("version", "0.1.0")),
        description_expr=f"description = {description!r}",
        author_name=author_name,
        author_email=author_email,
        readme_path=readme_path,
        license_str=license_str,
        python_requires=python_requires,
        classifiers=classifiers,
        install_requires=install_requires,
        extras_require=extras_require,
        packages_expr=packages_expr,
        package_dir_expr=package_dir_expr,
        py_modules=[],
        dynamic_extraction=dynamic_extraction,
    )


def handle_setuptools(config: dict[str, Any], root: Path, project: dict[str, Any], name: str) -> str:
    backend = get_backend(config)
    if "setuptools" not in backend:
        print(f"Warning: This project uses '{backend}', not setuptools. Proceeding anyway...")

    author_name, author_email = extract_authors(project)
    dynamic_fields = extract_dynamic(project)
    readme_path = extract_readme(project)
    license_str = extract_license(project)
    install_requires, extras_require, python_requires = extract_dependencies(project)
    classifiers = project.get("classifiers", [])
    description = project.get("description", "")

    setuptools_tool = config.get("tool", {}).get("setuptools", {})
    setuptools_dynamic = setuptools_tool.get("dynamic", {})

    version_attr = ""
    if "version" in dynamic_fields and isinstance(setuptools_dynamic.get("version"), dict):
        version_attr = setuptools_dynamic["version"].get("attr", "")

    packages_find_cfg = setuptools_tool.get("packages", {}).get("find", {})
    find_where_default = "." if not (root / "src").exists() else "src"
    find_where_list = packages_find_cfg.get("where", [find_where_default])
    find_where = find_where_list[0] if find_where_list else find_where_default
    find_include = packages_find_cfg.get("include", ["*"])
    find_exclude = packages_find_cfg.get("exclude", [])

    norm = normalize_name(name)

    dynamic_extraction = f"""
def extract_metadata():
    global version
    if "version" not in {dynamic_fields!r}:
        return
    attr_path = {version_attr!r}
    if attr_path:
        try:
            sys.path.insert(0, os.getcwd())
            if os.path.exists("src"):
                sys.path.insert(0, os.path.join(os.getcwd(), "src"))
            module_name, obj_name = attr_path.rsplit(".", 1)
            import importlib
            mod = importlib.import_module(module_name)
            version = getattr(mod, obj_name)
            return
        except Exception:
            pass
    import ast
    for path in [{norm + "/__init__.py"!r}, {"src/" + norm + "/__init__.py"!r}]:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("__version__"):
                        try:
                            version = ast.literal_eval(line.split("=", 1)[1].strip())
                            return
                        except Exception:
                            pass

extract_metadata()
"""

    packages_expr = f"find_packages(where={find_where!r}, include={find_include!r}, exclude={find_exclude!r})"
    package_dir_expr = f'{{"": {find_where!r}}}' if find_where != "." else "{}"

    return build_setup_module(
        name=name,
        version_expr=repr(project.get("version", "0.1.0")),
        description_expr=f"description = {description!r}",
        author_name=author_name,
        author_email=author_email,
        readme_path=readme_path,
        license_str=license_str,
        python_requires=python_requires,
        classifiers=classifiers,
        install_requires=install_requires,
        extras_require=extras_require,
        packages_expr=packages_expr,
        package_dir_expr=package_dir_expr,
        py_modules=[],
        dynamic_extraction=dynamic_extraction,
    )


def handle_pdm(config: dict[str, Any], root: Path, project: dict[str, Any], name: str) -> str:
    backend = get_backend(config)
    if "pdm.backend" not in backend:
        print(f"Warning: This project uses '{backend}', not pdm.backend. Proceeding anyway...")

    author_name, author_email = extract_authors(project)
    dynamic_fields = extract_dynamic(project)
    readme_path = extract_readme(project)
    license_str = extract_license(project)
    install_requires, extras_require, python_requires = extract_dependencies(project)
    classifiers = project.get("classifiers", [])
    description = project.get("description", "")

    pdm_build = config.get("tool", {}).get("pdm", {}).get("build", {})
    package_dir_src = pdm_build.get("package-dir", "")
    custom_includes = pdm_build.get("includes", [])
    py_modules = [m.replace(".py", "") for m in custom_includes if m.endswith(".py")]

    pdm_version_cfg = config.get("tool", {}).get("pdm", {}).get("version", {})
    version_source = pdm_version_cfg.get("source", "file" if "version" in dynamic_fields else "static")
    version_path = pdm_version_cfg.get("path", "")

    norm = normalize_name(name)

    dynamic_extraction = f"""
def extract_metadata():
    global version
    if "version" not in {dynamic_fields!r}:
        return
    if {version_source!r} == "scm":
        try:
            import subprocess
            v = subprocess.check_output(["git", "describe", "--tags", "--always"]).decode("utf-8").strip()
            if v:
                version = v
                return
        except Exception:
            pass
    explicit = {version_path!r}
    search = [explicit] if explicit else [
        {norm + "/__init__.py"!r},
        {"src/" + norm + "/__init__.py"!r},
    ]
    import ast
    for path in search:
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("__version__") or stripped.startswith("VERSION"):
                        try:
                            version = ast.literal_eval(stripped.split("=", 1)[1].strip())
                            return
                        except Exception:
                            pass

extract_metadata()

pdm_pkg_dir = {package_dir_src!r}
if pdm_pkg_dir:
    packages = find_packages(where=pdm_pkg_dir)
    package_dir = {{"": pdm_pkg_dir}}
elif os.path.exists("src"):
    packages = find_packages(where="src")
    package_dir = {{"": "src"}}
else:
    packages = find_packages()
    package_dir = {{}}
"""

    return build_setup_module(
        name=name,
        version_expr=repr(project.get("version", "0.1.0")),
        description_expr=f"description = {description!r}",
        author_name=author_name,
        author_email=author_email,
        readme_path=readme_path,
        license_str=license_str,
        python_requires=python_requires,
        classifiers=classifiers,
        install_requires=install_requires,
        extras_require=extras_require,
        packages_expr="packages",
        package_dir_expr="package_dir",
        py_modules=py_modules,
        dynamic_extraction=dynamic_extraction,
    )


def handle_poetry(config: dict[str, Any], root: Path, project: dict[str, Any], name: str) -> str:
    backend = get_backend(config)
    if "poetry.core" not in backend:
        print(f"Warning: This project uses '{backend}', not poetry-core. Proceeding anyway...")

    tool_poetry = config.get("tool", {}).get("poetry", {})
    author_name, author_email = extract_authors(project, config)
    dynamic_fields = extract_dynamic(project)
    readme_path = extract_readme(project, config)
    license_str = extract_license(project, config)
    install_requires, extras_require, python_requires = extract_dependencies(project, config)
    classifiers = project.get("classifiers", []) or tool_poetry.get("classifiers", [])
    description = project.get("description") or tool_poetry.get("description", "")
    version_static = project.get("version") or tool_poetry.get("version", "0.1.0")

    uses_dynamic = "tool" in config and "poetry-dynamic-versioning" in config["tool"]

    dynamic_extraction = f"""
def extract_metadata():
    global version
    if {uses_dynamic} or "version" in {dynamic_fields!r}:
        try:
            import subprocess
            v = subprocess.check_output(["git", "describe", "--tags", "--always"]).decode("utf-8").strip()
            if v:
                version = v
                return
        except Exception:
            pass

extract_metadata()
"""

    packages_expr = 'find_packages(where="src") if os.path.exists("src") else find_packages()'
    package_dir_expr = '{"": "src"} if os.path.exists("src") else {}'

    return build_setup_module(
        name=name,
        version_expr=repr(version_static),
        description_expr=f"description = {description!r}",
        author_name=author_name,
        author_email=author_email,
        readme_path=readme_path,
        license_str=license_str,
        python_requires=python_requires,
        classifiers=classifiers,
        install_requires=install_requires,
        extras_require=extras_require,
        packages_expr=packages_expr,
        package_dir_expr=package_dir_expr,
        py_modules=[],
        dynamic_extraction=dynamic_extraction,
    )


def handle_skbuild(config: dict[str, Any], root: Path, project: dict[str, Any], name: str) -> str:
    backend = get_backend(config)
    if "scikit_build_core" not in backend:
        print(f"Warning: This project uses '{backend}', not scikit_build_core. Proceeding anyway...")

    author_name, author_email = extract_authors(project)
    dynamic_fields = extract_dynamic(project)
    readme_path = extract_readme(project)
    license_str = extract_license(project)
    install_requires, extras_require, python_requires = extract_dependencies(project)
    classifiers = project.get("classifiers", [])
    description = project.get("description", "")

    version_regex_file = ""
    version_regex_pattern = ""
    version_is_scm = False

    dynamic_meta_array = config.get("tool", {}).get("dynamic-metadata", [])
    if isinstance(dynamic_meta_array, list):
        for table in dynamic_meta_array:
            if table.get("field") == "version":
                provider = table.get("provider", "")
                if "regex" in provider:
                    version_regex_file = table.get("input", "")
                    version_regex_pattern = table.get("regex", "")
                elif "setuptools_scm" in provider:
                    version_is_scm = True

    if not version_regex_file and not version_is_scm:
        legacy_meta = config.get("tool", {}).get("scikit-build", {}).get("metadata", {}).get("version", {})
        provider = legacy_meta.get("provider", "")
        if "regex" in provider:
            version_regex_file = legacy_meta.get("input", "")
            version_regex_pattern = legacy_meta.get("regex", "")
        elif "setuptools_scm" in provider:
            version_is_scm = True

    dynamic_extraction = f"""
def extract_metadata():
    global version
    if "version" not in {dynamic_fields!r}:
        return
    if {version_is_scm}:
        try:
            import subprocess
            v = subprocess.check_output(["git", "describe", "--tags", "--always"]).decode("utf-8").strip()
            if v:
                version = v
                return
        except Exception:
            pass
    regex_file = {version_regex_file!r}
    regex_pattern = {version_regex_pattern!r}
    if regex_file and os.path.exists(regex_file):
        pattern_str = regex_pattern if regex_pattern else r'__version__\\s*=\\s*["\\']([^"\\']+)["\\']'
        try:
            with open(regex_file, "r", encoding="utf-8") as f:
                content = f.read()
            m = re.search(pattern_str, content)
            if m:
                version = m.group(1)
                return
        except Exception:
            pass

extract_metadata()
"""

    packages_expr = 'find_packages(where="src") if os.path.exists("src") else find_packages()'
    package_dir_expr = '{"": "src"} if os.path.exists("src") else {}'

    return build_setup_module(
        name=name,
        version_expr=repr(project.get("version", "0.1.0")),
        description_expr=f"description = {description!r}",
        author_name=author_name,
        author_email=author_email,
        readme_path=readme_path,
        license_str=license_str,
        python_requires=python_requires,
        classifiers=classifiers,
        install_requires=install_requires,
        extras_require=extras_require,
        packages_expr=packages_expr,
        package_dir_expr=package_dir_expr,
        py_modules=[],
        dynamic_extraction=dynamic_extraction,
    )


BACKEND_DETECTORS: list[tuple[str, Any]] = [
    ("flit_core", handle_flit),
    ("hatchling", handle_hatch),
    ("maturin", handle_maturin),
    ("mesonpy", handle_meson),
    ("scikit_build_core", handle_skbuild),
    ("pdm.backend", handle_pdm),
    ("poetry.core", handle_poetry),
    ("setuptools", handle_setuptools),
]


def detect_backend(backend: str) -> Any | None:
    for key, handler in BACKEND_DETECTORS:
        if key in backend:
            return handler
    return None


def generate_setup_py() -> None:
    root = Path.cwd()
    config = load_pyproject(root)
    backend = get_backend(config)

    project = config.get("project", {})
    poetry = config.get("tool", {}).get("poetry", {})

    if not project and not poetry:
        print("Error: No [project] table found in pyproject.toml.")
        sys.exit(1)

    name = get_name(project, config) if project else poetry.get("name")
    if not name:
        print("Error: Project name is missing from pyproject.toml.")
        sys.exit(1)

    handler = detect_backend(backend)
    if handler is None:
        print(f"Error: Unsupported build backend '{backend}'.")
        sys.exit(1)

    if not project and handler is handle_poetry:
        project = {}

    setup_code = handler(config, root, project, name)
    out = root / "setup.py"
    out.write_text(setup_code, encoding="utf-8")
    print(f"Successfully generated a legacy fallback setup.py for project: '{name}'")


if __name__ == "__main__":
    generate_setup_py()
