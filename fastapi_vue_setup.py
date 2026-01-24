"""FastAPI-Vue Integration Tool

Create new FastAPI+Vue projects or patch existing ones with integrated build/dev systems.

Usage:
    fastapi-vue-setup [project-dir]     Set up or update FastAPI+Vue integration

Options:
    --module-name NAME      Python module name (auto-detected from pyproject.toml)
    --dry-run               Show what would be done without making changes
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from textwrap import indent

import tomlkit

# Template directory
TEMPLATE_DIR = Path(__file__).parent / "template"

# Marker comment indicating file can be auto-upgraded
# Users should remove this line to prevent automatic updates
UPGRADE_MARKER = "auto-upgrade@fastapi-vue-setup"

# pyproject.toml additions for patched projects
PYPROJECT_ADDITIONS = {
    "tool": {
        "hatch": {
            "build": {
                "packages": ["MODULE_NAME"],
                "artifacts": ["MODULE_NAME/frontend-build"],
                "targets": {
                    "sdist": {
                        "hooks": {
                            "custom": {"path": "scripts/fastapi-vue/build-frontend.py"}
                        },
                    }
                },
                "only-packages": True,
            }
        }
    },
}


# Frontend instantiation block for patching existing apps
FRONTEND_BLOCK = """
# Vue Frontend static files
frontend = Frontend(
    Path(__file__).with_name("frontend-build"), spa=True, cached=["/assets/"]
)
"""

# TypeScript health check script for Vue components
TS_HEALTH_CHECK_SCRIPT = """\
import { ref, onMounted } from 'vue'

const backendStatus = ref<'checking' | 'connected' | 'error'>('checking')

onMounted(async () => {
  try {
    const res = await fetch('/api/health')
    backendStatus.value = res.ok ? 'connected' : 'error'
  } catch {
    backendStatus.value = 'error'
  }
})
"""

# JavaScript health check script for Vue components
JS_HEALTH_CHECK_SCRIPT = """\
import { ref, onMounted } from 'vue'

const backendStatus = ref('checking')

onMounted(async () => {
  try {
    const res = await fetch('/api/health')
    backendStatus.value = res.ok ? 'connected' : 'error'
  } catch {
    backendStatus.value = 'error'
  }
})
"""

# Status indicator template for Vue components
STATUS_SPAN_TEMPLATE = """\
    <span style="white-space: nowrap">
      — FastAPI:
      <span v-if="backendStatus === 'checking'">⏳</span>
      <span v-else-if="backendStatus === 'connected'">✅</span>
      <span v-else>❌ not reachable</span>
    </span>
"""

# Setup complete message template
SETUP_COMPLETE_MESSAGE = """
Next steps:

1. Build for production:
   CD_CMDuv build

2. Start development server:
   CD_CMDuv run scripts/devserver.py

3. Run production server:
   CD_CMDuv run SCRIPT_NAME
"""


# =============================================================================
# Utility functions
# =============================================================================


def load_template(path: str) -> str:
    """Load a template file from the template directory."""
    return (TEMPLATE_DIR / path).read_text()


def find_module_name(project_dir: Path) -> str | None:
    """Auto-detect the Python module name from pyproject.toml."""
    pyproject = project_dir / "pyproject.toml"
    if not pyproject.exists():
        return None

    data = tomlkit.parse(pyproject.read_text())

    if "project" in data and "name" in data["project"]:
        name = data["project"]["name"]
        return name.replace("-", "_")

    return None


def find_fastapi_app(
    module_dir: Path, project_dir: Path | None = None
) -> tuple[Path, str] | None:
    """Find the FastAPI app in a module directory.

    Returns (file_path, app_variable_name) or None if not found.

    Search order:
    1. Common app files in module_dir (app.py, main.py, etc.)
    2. All .py files in module_dir
    3. Subpackage indicated by CLI entrypoint in pyproject.toml
    4. Follow re-exports in __init__.py files
    """
    # Common app file names to check first
    candidates = ["app.py", "main.py", "server.py", "api.py", "__init__.py"]

    # Check common names first
    for name in candidates:
        path = module_dir / name
        if path.exists():
            result = _find_app_in_file(path)
            if result:
                return path, result

    # Then check all .py files in module_dir
    for path in module_dir.glob("*.py"):
        if path.name not in candidates:
            result = _find_app_in_file(path)
            if result:
                return path, result

    # Try to find app via CLI entrypoint in pyproject.toml
    if project_dir:
        result = _find_app_via_entrypoint(module_dir, project_dir)
        if result:
            return result

    return None


def _find_app_via_entrypoint(module_dir: Path, project_dir: Path) -> tuple[Path, str] | None:
    """Find FastAPI app by following the CLI entrypoint in pyproject.toml.

    If pyproject.toml has a script like `myapp = "myapp.subpkg.__main__:main"`,
    look in myapp/subpkg/ for the app (checking __init__.py exports and common files).
    """
    pyproject = project_dir / "pyproject.toml"
    if not pyproject.exists():
        return None

    try:
        data = tomlkit.parse(pyproject.read_text())
    except Exception:
        return None

    scripts = data.get("project", {}).get("scripts", {})
    if not scripts:
        return None

    module_name = module_dir.name

    # Find script entries that reference this module
    for script_name, entry in scripts.items():
        if not isinstance(entry, str):
            continue
        # Parse entry like "module.subpkg.__main__:main"
        if ":" not in entry:
            continue
        module_path, _ = entry.rsplit(":", 1)
        parts = module_path.split(".")

        # Check if this entry starts with our module
        if not parts or parts[0] != module_name:
            continue

        # If there's a subpackage (e.g., module.fastapi.__main__), check there
        if len(parts) >= 2:
            # Build path to subpackage (exclude __main__ or similar)
            subpkg_parts = [p for p in parts[1:] if not p.startswith("_")]
            if subpkg_parts:
                subpkg_dir = module_dir / "/".join(subpkg_parts)
                if subpkg_dir.is_dir():
                    result = _find_app_in_subpackage(subpkg_dir)
                    if result:
                        return result

    return None


def _find_app_in_subpackage(subpkg_dir: Path) -> tuple[Path, str] | None:
    """Find FastAPI app in a subpackage, following __init__.py exports."""
    # First check __init__.py for re-exports like `from .mainapp import app`
    init_file = subpkg_dir / "__init__.py"
    if init_file.exists():
        result = _follow_init_reexport(init_file, subpkg_dir)
        if result:
            return result

    # Check common app file names in subpackage
    for name in ["app.py", "main.py", "mainapp.py", "server.py", "api.py"]:
        path = subpkg_dir / name
        if path.exists():
            result = _find_app_in_file(path)
            if result:
                return path, result

    return None


def _find_existing_cli_entrypoint(project_dir: Path, module_name: str) -> str | None:
    """Check if pyproject.toml already has a CLI entrypoint for this module.

    Returns the entrypoint string if found, None otherwise.
    """
    pyproject = project_dir / "pyproject.toml"
    if not pyproject.exists():
        return None

    try:
        data = tomlkit.parse(pyproject.read_text())
    except Exception:
        return None

    scripts = data.get("project", {}).get("scripts", {})
    if not scripts:
        return None

    # Look for any script that references our module
    for script_name, entry in scripts.items():
        if isinstance(entry, str) and entry.startswith(f"{module_name}."):
            return f"{script_name} = \"{entry}\""

    return None


def _follow_init_reexport(init_file: Path, subpkg_dir: Path) -> tuple[Path, str] | None:
    """Follow a re-export in __init__.py to find the actual app file.

    Looks for patterns like:
    - from .mainapp import app
    - from module.subpkg.mainapp import app
    """
    try:
        content = init_file.read_text()
    except Exception:
        return None

    # Look for: from .module import app (or similar variable names)
    # Pattern matches: from .mainapp import app, application, etc.
    pattern = r"from\s+\.(\w+)\s+import\s+(\w+)"
    for match in re.finditer(pattern, content):
        module_name, var_name = match.groups()
        if var_name.lower() in ("app", "application", "api"):
            target_file = subpkg_dir / f"{module_name}.py"
            if target_file.exists():
                # Verify the app is actually there
                app_var = _find_app_in_file(target_file)
                if app_var:
                    return target_file, app_var

    # Also check for absolute imports: from pkg.subpkg.module import app
    abs_pattern = r"from\s+[\w.]+\.(\w+)\s+import\s+(\w+)"
    for match in re.finditer(abs_pattern, content):
        module_name, var_name = match.groups()
        if var_name.lower() in ("app", "application", "api"):
            target_file = subpkg_dir / f"{module_name}.py"
            if target_file.exists():
                app_var = _find_app_in_file(target_file)
                if app_var:
                    return target_file, app_var

    return None


def _find_app_in_file(path: Path) -> str | None:
    """Find FastAPI app variable name in a file."""
    try:
        content = path.read_text()
    except Exception:
        return None

    # Look for FastAPI() instantiation patterns
    # Matches: app = FastAPI(...) or application = FastAPI(...)
    pattern = r"^(\w+)\s*=\s*FastAPI\s*\("
    for match in re.finditer(pattern, content, re.MULTILINE):
        return match.group(1)

    return None


def render_template(template: str, **kwargs) -> str:
    """Simple template rendering replacing KEY with value."""
    result = template
    for key, value in kwargs.items():
        result = result.replace(key, value)
    return result


def patch_app_file(
    path: Path, module_name: str, app_var: str, dry_run: bool = False
) -> bool:
    """Patch an existing app.py with frontend integration.

    Inserts import and Frontend instantiation after imports, route at bottom,
    and tries to patch lifespan with frontend.load().

    Returns True if patched, False if already patched or failed.
    """
    if not path.exists():
        print(f"❌ Cannot patch {path} - file not found")
        return False

    original_content = path.read_text()
    marker = "from fastapi_vue import Frontend"

    if marker in original_content:
        print(f"✔️  {path} (already patched)")
        return False

    # Find where to insert the import (after other imports)
    lines = original_content.split("\n")
    import_line = "from fastapi_vue import Frontend"

    route_line = f'frontend.route({app_var}, "/")'

    # Find last import line and check if pathlib is imported
    last_import_idx = 0
    has_pathlib = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            last_import_idx = i
            if "pathlib" in stripped or "from pathlib" in stripped:
                has_pathlib = True
        elif stripped and not stripped.startswith("#") and last_import_idx > 0:
            # Stop at first non-import, non-comment, non-empty line after imports
            break

    # Check if we found imports to insert after
    if last_import_idx == 0 and not lines[0].strip().startswith(("import ", "from ")):
        print(f"⚠️  Skipping {path} (no imports found to patch)")
        return False

    # Insert imports after last import, then frontend instantiation
    if not has_pathlib:
        lines.insert(last_import_idx + 1, "from pathlib import Path")
        last_import_idx += 1
    lines.insert(last_import_idx + 1, import_line)
    lines.insert(last_import_idx + 2, FRONTEND_BLOCK)

    # Append route at end
    lines.append("")
    lines.append(route_line)
    content = "\n".join(lines)

    # Try to patch lifespan function - insert await frontend.load() before yield
    lifespan_patched = False

    # Look for yield inside an async def lifespan function
    # Find the yield statement and insert before it
    yield_pattern = r"^([ \t]+)(yield\b)"
    yield_match = re.search(yield_pattern, content, re.MULTILINE)
    if yield_match:
        indent = yield_match.group(1)
        insert_pos = yield_match.start()
        load_code = f"{indent}await frontend.load()\n"
        content = content[:insert_pos] + load_code + content[insert_pos:]
        lifespan_patched = True

    # Check if content actually changed
    if content == original_content:
        print(f"⚠️  Skipping {path} (no changes needed)")
        return False

    if dry_run:
        print(f"[DRY RUN] Would patch {path}")
        return True

    path.write_text(content)
    print(f"✅ Patched {path}")

    if not lifespan_patched:
        # Check if they're using deprecated on_event
        if f"@{app_var}.on_event" in content:
            print()
            print("⚠️  Your app uses the deprecated @app.on_event decorator.")
            print("   Please migrate to the lifespan pattern and add:")
            print("       await frontend.load()")
            print()
        else:
            print()
            print("⚠️  Could not find lifespan function to patch.")
            print("   Add this to your app's lifespan function:")
            print("       await frontend.load()")
            print()

    return True


def patch_vite_config(
    path: Path,
    module_name: str,
    dry_run: bool = False,
) -> bool:
    """Patch an existing vite.config.js/ts by adding fastapi-vue plugin.

    This approach is cleaner than inline patching - we just add an import
    and include the plugin in the plugins array.
    """
    if not path.exists():
        print(f"❌ Cannot patch {path} - file not found")
        return False

    original_content = path.read_text()
    marker = "vite-plugin-fastapi"

    if marker in original_content:
        print(f"✔️  {path} (already patched)")
        return False

    # Add import for the plugin at the top (after other imports)
    import_line = f"import fastapiVue from './{marker}.js'"

    lines = original_content.split("\n")
    new_lines = []
    import_inserted = False

    for i, line in enumerate(lines):
        new_lines.append(line)
        # Insert after the last import line before non-import content
        if not import_inserted:
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                # Check if next line is not an import
                if i + 1 < len(lines):
                    next_stripped = lines[i + 1].strip()
                    if not next_stripped.startswith(
                        "import "
                    ) and not next_stripped.startswith("from "):
                        new_lines.append(import_line)
                        import_inserted = True

    if not import_inserted:
        # No imports found, add at top
        new_lines.insert(0, import_line)

    content = "\n".join(new_lines)

    # Add fastapiVue to plugins array
    # Look for plugins: [ and add fastapiVue() as first entry
    plugins_pattern = r"(plugins\s*:\s*\[)"
    match = re.search(plugins_pattern, content)
    if match:
        insert_pos = match.end()
        content = content[:insert_pos] + "\n    fastapiVue()," + content[insert_pos:]
    else:
        print(f"⚠️  Skipping {path} (no plugins array found)")
        return False

    # Check if content actually changed
    if content == original_content:
        print(f"⚠️  Skipping {path} (no changes needed)")
        return False

    if dry_run:
        print(f"[DRY RUN] Would patch {path}")
        return True

    path.write_text(content)
    print(f"✅ Patched {path}")
    return True


def patch_frontend_health_check(frontend_dir: Path, dry_run: bool = False) -> bool:
    """Patch Vue app to include FastAPI backend health check.

    Tries HelloWorld.vue first (full demo), then falls back to App.vue (minimal).
    Works with both JS and TS versions created by create-vue.
    """
    # Find the file to patch - prefer HelloWorld.vue, fall back to App.vue
    target_file = None

    # Try HelloWorld.vue first (full demo app)
    hello_world = frontend_dir / "src" / "components" / "HelloWorld.vue"
    if hello_world.exists():
        target_file = hello_world
    else:
        # Try finding HelloWorld.vue elsewhere
        for path in frontend_dir.glob("src/**/HelloWorld.vue"):
            target_file = path
            break

    # Fall back to App.vue (minimal app)
    if target_file is None:
        app_vue = frontend_dir / "src" / "App.vue"
        if app_vue.exists():
            target_file = app_vue

    if target_file is None:
        print("⚠️  No Vue file found to patch, skipping frontend health check")
        return False

    original_content = target_file.read_text()

    # Check if already patched
    if "/api/health" in original_content:
        print(f"✔️  {target_file} (already patched)")
        return False

    content = original_content

    # Detect if TypeScript (has lang="ts" in script tag)
    is_typescript = 'lang="ts"' in content

    # Build the script content based on JS/TS
    script_addition = (
        TS_HEALTH_CHECK_SCRIPT if is_typescript else JS_HEALTH_CHECK_SCRIPT
    )

    # Insert script addition before </script>
    script_end_match = re.search(r"</script>", content)
    if not script_end_match:
        print(f"⚠️  Skipping {target_file} (no </script> tag found)")
        return False

    insert_pos = script_end_match.start()
    content = content[:insert_pos] + script_addition + content[insert_pos:]

    # Insert status inline - find the best place based on file type
    # For HelloWorld.vue: insert before </h3>
    # For App.vue (minimal): only patch if it's the default "You did it!" template
    if "HelloWorld" in str(target_file):
        # Insert before closing </h3>
        h3_close = content.find("    </h3>")
        if h3_close == -1:
            print(
                f"⚠️  Skipping {target_file} (no </h3> tag found for status insertion)"
            )
            return False
        before, after = content[:h3_close], content[h3_close:]
        content = f"{before}{indent(STATUS_SPAN_TEMPLATE, '  ')}{after}"
    else:
        # Minimal App.vue - only patch if it contains the default welcome message
        if "<h1>You did it!</h1>" not in content:
            print(f"⚠️  Skipping {target_file} (not a default Vue template)")
            return False
        # Insert before the </p> tag
        template_end = content.find("</template>")
        if template_end == -1:
            print(f"⚠️  Skipping {target_file} (no </template> tag found)")
            return False
        # Find </p> before </template>
        last_p = content.rfind("</p>", 0, template_end)
        if last_p == -1:
            print(f"⚠️  Skipping {target_file} (no </p> tag found for status insertion)")
            return False
        before, after = content[:last_p], content[last_p:]
        content = f"{before}{STATUS_SPAN_TEMPLATE}{after}"

    # Check if content actually changed
    if content == original_content:
        print(f"⚠️  Skipping {target_file} (no changes needed)")
        return False

    if dry_run:
        print(f"[DRY RUN] Would patch {target_file}")
        return True

    target_file.write_text(content)
    print(f"✅ Patched {target_file}")
    return True


# Track .new.py files written during setup (for merge notification)
_new_files_written: list[tuple[Path, Path]] = []


def write_file(
    path: Path,
    content: str,
    overwrite: bool = True,
    dry_run: bool = False,
    executable: bool = False,
    fallback_path: Path | None = None,
) -> bool:
    """Write content to a file, handling existing files and dry-run.

    If fallback_path is provided and the file exists without the upgrade marker,
    the content will be written to fallback_path instead of being skipped.
    """
    exists = path.exists()
    if exists and not overwrite:
        print(f"ℹ️  Skipping {path} (exists)")
        return False

    # Check if content is the same
    if exists:
        existing_content = path.read_text()
        if existing_content == content:
            print(f"✔️  {path} (already up to date)")
            return False

        # If overwrite requested but file doesn't have upgrade marker
        if overwrite and UPGRADE_MARKER not in existing_content:
            if fallback_path is not None:
                # Write to fallback path instead
                return _write_fallback_file(
                    path, fallback_path, content, dry_run, executable
                )
            print(f"ℹ️  Skipping {path} (customized by user)")
            return False

    if dry_run:
        action = "overwrite" if exists else "create"
        print(f"[DRY RUN] Would {action} {path}")
        return True

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if executable and sys.platform != "win32":
        path.chmod(path.stat().st_mode | 0o111)
    action = "Updated" if exists else "Created"
    print(f"✅ {action} {path}")
    return True


def _write_fallback_file(
    original_path: Path,
    fallback_path: Path,
    content: str,
    dry_run: bool,
    executable: bool,
) -> bool:
    """Write content to a fallback .new.py file when original can't be overwritten."""
    # Check if fallback already has same content
    if fallback_path.exists():
        if fallback_path.read_text() == content:
            print(f"✔️  {fallback_path} (already up to date)")
            return False

    if dry_run:
        print(f"[DRY RUN] Would create {fallback_path} (original customized by user)")
        _new_files_written.append((fallback_path, original_path))
        return True

    fallback_path.parent.mkdir(parents=True, exist_ok=True)
    fallback_path.write_text(content)
    if executable and sys.platform != "win32":
        fallback_path.chmod(fallback_path.stat().st_mode | 0o111)
    print(f"✅ Created {fallback_path} (original customized by user)")
    _new_files_written.append((fallback_path, original_path))
    return True


def merge_pyproject(
    data: tomlkit.TOMLDocument, additions: dict, module_name: str
) -> tomlkit.TOMLDocument:
    """Merge additions into pyproject.toml data, preserving comments and existing values."""
    # Ensure hatchling build system is configured
    if "build-system" not in data:
        data["build-system"] = tomlkit.table()

    # Add hatchling to requires if not present, preserving existing requires
    if "requires" not in data["build-system"]:
        data["build-system"]["requires"] = ["hatchling"]
    else:
        requires = list(data["build-system"]["requires"])
        if not any(r.startswith("hatchling") for r in requires):
            requires.insert(0, "hatchling")
            data["build-system"]["requires"] = requires

    if "build-backend" not in data["build-system"]:
        data["build-system"]["build-backend"] = "hatchling.build"

    # Ensure project table exists
    if "project" not in data:
        data["project"] = tomlkit.table()

    # Ensure Python version is at least 3.11 (required by fastapi-vue)
    if "requires-python" in data["project"]:
        req = data["project"]["requires-python"]
        # Parse minimum version from strings like ">=3.10" or ">=3.9,<4"
        import re
        match = re.search(r">=\s*(\d+)\.(\d+)", req)
        if match:
            major, minor = int(match.group(1)), int(match.group(2))
            if major < 3 or (major == 3 and minor < 11):
                data["project"]["requires-python"] = ">=3.11"
    else:
        data["project"]["requires-python"] = ">=3.11"

    # Add hatch build config
    if "tool" not in data:
        data["tool"] = tomlkit.table()
    if "hatch" not in data["tool"]:
        data["tool"]["hatch"] = tomlkit.table()
    if "build" not in data["tool"]["hatch"]:
        data["tool"]["hatch"]["build"] = tomlkit.table()

    hatch_build = data["tool"]["hatch"]["build"]
    hatch_additions = additions["tool"]["hatch"]["build"]

    # Set packages if not already set
    if "packages" not in hatch_build:
        hatch_build["packages"] = [
            p.replace("MODULE_NAME", module_name) for p in hatch_additions["packages"]
        ]

    # Set artifacts if not already set
    if "artifacts" not in hatch_build:
        hatch_build["artifacts"] = [
            a.replace("MODULE_NAME", module_name) for a in hatch_additions["artifacts"]
        ]

    # Set only-packages if not already set
    if "only-packages" not in hatch_build:
        hatch_build["only-packages"] = hatch_additions["only-packages"]

    # Add sdist target with custom hook
    if "targets" not in hatch_build:
        hatch_build["targets"] = tomlkit.table()
    if "sdist" not in hatch_build["targets"]:
        hatch_build["targets"]["sdist"] = tomlkit.table()
    if "hooks" not in hatch_build["targets"]["sdist"]:
        hatch_build["targets"]["sdist"]["hooks"] = tomlkit.table()
    if "custom" not in hatch_build["targets"]["sdist"]["hooks"]:
        hatch_build["targets"]["sdist"]["hooks"]["custom"] = tomlkit.table()
    if "path" not in hatch_build["targets"]["sdist"]["hooks"]["custom"]:
        hatch_build["targets"]["sdist"]["hooks"]["custom"]["path"] = hatch_additions[
            "targets"
        ]["sdist"]["hooks"]["custom"]["path"]

    return data


# =============================================================================
# Command implementations
# =============================================================================


def find_js_runtime() -> tuple[str, str] | None:
    """Find a JavaScript runtime from JS_RUNTIME env or auto-detect.

    Returns (tool_path, tool_name) where tool_name is "deno", "npm", or "bun".
    Returns None if no runtime is found.
    """
    import shutil

    options = ["deno", "npm", "bun"]

    # Check for JS_RUNTIME environment variable
    if js_runtime_env := os.environ.get("JS_RUNTIME"):
        js_runtime = js_runtime_env
        js_path = Path(js_runtime)
        runtime_name = js_path.name
        # Map node to npm
        if runtime_name == "node":
            runtime_name = "npm"
            js_runtime = str(js_path.parent / "npm") if js_path.parent.name else "npm"
        for option in options:
            if option == runtime_name or runtime_name.startswith(option):
                tool = shutil.which(js_runtime)
                if tool is None:
                    print(f"⚠️  JS_RUNTIME={js_runtime_env} not found")
                    return None
                return tool, option
        print(f"⚠️  JS_RUNTIME={js_runtime_env} not recognized")
        return None

    # Auto-detect
    for option in options:
        if tool := shutil.which(option):
            return tool, option
    return None


def ensure_python_project(project_dir: Path, dry_run: bool = False) -> bool:
    """Ensure pyproject.toml exists, run uv init if needed."""
    pyproject = project_dir / "pyproject.toml"
    if pyproject.exists():
        return True

    if dry_run:
        print(f"[DRY RUN] Would run: uv init {project_dir}")
        return True

    print("📦 No pyproject.toml found, initializing Python project...")
    print(">>> uv init")
    result = subprocess.run(["uv", "init", str(project_dir)], check=False)
    if result.returncode != 0:
        print("❌ uv init failed")
        return False

    # Remove files created by uv init that we don't need
    for filename in ["hello.py", "main.py", ".python-version"]:
        filepath = project_dir / filename
        if filepath.exists():
            filepath.unlink()

    return True


def ensure_frontend(project_dir: Path, dry_run: bool = False) -> bool:
    """Ensure frontend directory exists with a Vue project, run create-vue if needed."""
    frontend_dir = project_dir / "frontend"
    package_json = frontend_dir / "package.json"

    # Check for package.json, not just directory existence (empty dir shouldn't count)
    if package_json.exists():
        return True

    # Find JS runtime
    runtime = find_js_runtime()
    if runtime is None:
        print("❌ No JavaScript runtime found (need deno, npm, or bun)")
        return False
    js_tool, js_name = runtime

    # Build the create command based on runtime
    create_vue_commands = {
        "deno": [js_tool, "run", "-A", "npm:create-vue@latest", "frontend"],
        "npm": [js_tool, "create", "vue@latest", "frontend"],
        "bun": [js_tool, "create", "vue@latest", "frontend"],
    }
    create_cmd = create_vue_commands[js_name]

    if dry_run:
        print(f"[DRY RUN] Would run: {' '.join(create_cmd)}")
        return True

    print("🎨 No frontend/ found, creating Vue project...")
    print(f">>> {' '.join(create_cmd)}")
    print("(Follow the prompts to configure your Vue app)")
    print()
    result = subprocess.run(
        create_cmd,
        cwd=project_dir,
        check=False,
    )
    if result.returncode != 0:
        print("❌ create-vue failed")
        return False

    return True


def cmd_setup(args: argparse.Namespace) -> int:
    """Set up or update FastAPI+Vue integration in a project.

    This unified command handles:
    - Creating new projects (uv init + create-vue if needed)
    - Patching existing projects with integration files
    - Updating already-patched projects
    """
    project_path = Path(args.project_dir)

    # Handle both "." and "/path/to/project"
    if project_path.is_absolute():
        project_dir = project_path
    else:
        project_dir = Path.cwd() / project_path

    project_dir = project_dir.resolve()
    dry_run = args.dry_run

    # Create project directory if it doesn't exist
    if not project_dir.exists():
        if dry_run:
            print(f"[DRY RUN] Would create directory: {project_dir}")
        else:
            project_dir.mkdir(parents=True)
            print(f"✅ Created {project_dir}")

    print(f"🔧 Setting up project: {project_dir}")

    if dry_run:
        print("\n🏃 DRY RUN MODE - no changes will be made\n")

    # Step 1: Ensure frontend exists (do this first so cancellation doesn't leave partial setup)
    if not ensure_frontend(project_dir, dry_run):
        return 1

    # Step 2: Ensure Python project exists
    if not ensure_python_project(project_dir, dry_run):
        return 1

    # Detect module name
    module_name = args.module_name or find_module_name(project_dir)
    if not module_name:
        # Derive from directory name
        module_name = project_dir.name.replace("-", "_")
        print(f"📦 Using module name from directory: {module_name}")

    # Title for templates
    project_title = module_name.replace("_", " ").title()

    print(f"📦 Module: {module_name}")

    # Template variables
    tpl_vars = {
        "MODULE_NAME": module_name,
        "PROJECT_TITLE": project_title,
    }

    module_dir = project_dir / module_name
    scripts_dir = project_dir / "scripts"
    fastapi_vue_scripts = scripts_dir / "fastapi-vue"

    # Find existing FastAPI app
    app_info = find_fastapi_app(module_dir, project_dir) if module_dir.exists() else None

    if app_info:
        app_file, app_var = app_info
        print(f"📍 Found FastAPI app: {app_var} in {app_file.name}")
        tpl_vars["APP_VAR"] = app_var
        tpl_vars["APP_MODULE"] = app_file.stem
    else:
        print("📍 No existing FastAPI app found, will create new one")
        app_file = None
        app_var = "app"
        tpl_vars["APP_VAR"] = app_var
        tpl_vars["APP_MODULE"] = "app"

    # Create directories
    if not dry_run:
        fastapi_vue_scripts.mkdir(parents=True, exist_ok=True)
        if not module_dir.exists():
            module_dir.mkdir(parents=True)

    # === Install scripts (always update our own scripts) ===
    # util.py and build-frontend.py are internal and always overwritten
    # devserver.py can be customized, so use fallback if needed
    internal_script_files = [
        (fastapi_vue_scripts / "util.py", "scripts/fastapi-vue/util.py"),
        (
            fastapi_vue_scripts / "build-frontend.py",
            "scripts/fastapi-vue/build-frontend.py",
        ),
    ]

    for dest_path, template_path in internal_script_files:
        template = load_template(template_path)
        content = render_template(template, **tpl_vars)
        write_file(
            dest_path,
            content,
            overwrite=True,
            dry_run=dry_run,
        )

    # devserver.py - use fallback if customized by user
    devserver_path = scripts_dir / "devserver.py"
    devserver_fallback = scripts_dir / "devserver.new.py"
    template = load_template("scripts/devserver.py")
    content = render_template(template, **tpl_vars)
    write_file(
        devserver_path,
        content,
        overwrite=True,
        dry_run=dry_run,
        executable=True,
        fallback_path=devserver_fallback,
    )

    # === Handle app module ===
    if app_file:
        # Existing app: patch with import, route, and try to patch lifespan
        patch_app_file(app_file, module_name, app_var, dry_run=dry_run)
    else:
        # No app: create full app.py
        # Create __init__.py if missing
        init_file = module_dir / "__init__.py"
        if not init_file.exists():
            template = load_template("backend/__init__.py")
            content = render_template(template, **tpl_vars)
            write_file(init_file, content, overwrite=False, dry_run=dry_run)

        # Create app.py
        app_file_path = module_dir / "app.py"
        template = load_template("backend/app.py")
        content = render_template(template, **tpl_vars)
        write_file(app_file_path, content, overwrite=False, dry_run=dry_run)

    # === Handle __main__.py ===
    # Skip if project already has a CLI entrypoint in pyproject.toml
    existing_cli = _find_existing_cli_entrypoint(project_dir, module_name)
    if existing_cli:
        print(f"ℹ️  Using existing CLI entrypoint: {existing_cli}")
    else:
        main_file = module_dir / "__main__.py"
        main_fallback = module_dir / "__main__.new.py"
        template = load_template("backend/__main__.py")
        main_content = render_template(template, **tpl_vars)

        # Use write_file with fallback - it handles all cases:
        # - File doesn't exist: create it
        # - File exists with marker: update it
        # - File exists without marker: write to fallback
        write_file(
            main_file,
            main_content,
                overwrite=True,
            dry_run=dry_run,
            fallback_path=main_fallback,
        )

    # === Update vite.config.js/ts ===
    frontend_dir = project_dir / "frontend"
    if frontend_dir.exists():
        # Install the vite plugin file (always update)
        plugin_file = frontend_dir / "vite-plugin-fastapi.js"
        template = load_template("frontend/vite-plugin-fastapi.js")
        content = render_template(template, **tpl_vars)
        write_file(plugin_file, content, overwrite=True, dry_run=dry_run)

        # Find existing vite config (prefer .ts, fall back to .js)
        vite_config_ts = frontend_dir / "vite.config.ts"
        vite_config_js = frontend_dir / "vite.config.js"

        if vite_config_ts.exists():
            patch_vite_config(vite_config_ts, module_name, dry_run)
        elif vite_config_js.exists():
            patch_vite_config(vite_config_js, module_name, dry_run)
        else:
            print("⚠️  No vite.config.ts or vite.config.js found in frontend/")
            print("   Run create-vue first to generate a Vite config to patch.")

        # Patch Vue app with backend health check
        patch_frontend_health_check(frontend_dir, dry_run)

    # === Update pyproject.toml ===
    pyproject_path = project_dir / "pyproject.toml"
    if pyproject_path.exists():
        old_content = pyproject_path.read_text()
        data = tomlkit.parse(old_content)

        updated = merge_pyproject(data, PYPROJECT_ADDITIONS, module_name)

        # Only add script entry if project doesn't already have scripts
        if "scripts" not in updated["project"] or not updated["project"]["scripts"]:
            updated["project"]["scripts"] = tomlkit.table()
            script_name = module_name.replace("_", "-")
            updated["project"]["scripts"][script_name] = f"{module_name}.__main__:main"

        # Check if content actually changed
        new_content = tomlkit.dumps(updated)

        if new_content == old_content:
            print(f"✔️  {pyproject_path} (already up to date)")
        elif dry_run:
            print(f"[DRY RUN] Would update {pyproject_path}")
        else:
            pyproject_path.write_text(new_content)
            print(f"✅ Updated {pyproject_path}")

    # === Add dependencies using uv ===
    if dry_run:
        print("[DRY RUN] Would run: uv add -U 'fastapi[standard]' fastapi-vue")
        print("[DRY RUN] Would run: uv add -U --group dev httpx")
    else:
        print("📦 Adding dependencies...")
        result = subprocess.run(
            ["uv", "add", "-U", "fastapi[standard]", "fastapi-vue"],
            cwd=project_dir,
            check=False,
        )
        if result.returncode != 0:
            print("⚠️  Failed to add main dependencies")
        result = subprocess.run(
            ["uv", "add", "-U", "--group", "dev", "httpx"],
            cwd=project_dir,
            check=False,
        )
        if result.returncode != 0:
            print("⚠️  Failed to add dev dependencies")

    # === Update .gitignore ===
    gitignore_path = project_dir / ".gitignore"
    gitignore_entry = f"/{module_name}/frontend-build"
    if gitignore_path.exists():
        gitignore_content = gitignore_path.read_bytes()
        if b"frontend-build" in gitignore_content:
            print("✔️  .gitignore (frontend-build already ignored)")
        elif dry_run:
            print(f"[DRY RUN] Would add {gitignore_entry} to .gitignore")
        else:
            nl = b"\r\n" if b"\r\n" in gitignore_content else b"\n"
            suffix = b"" if gitignore_content.endswith(nl) else nl
            gitignore_path.write_bytes(gitignore_content + suffix + gitignore_entry.encode() + nl)
            print(f"✅ Added {gitignore_entry} to .gitignore")
    elif dry_run:
        print(f"[DRY RUN] Would create .gitignore with {gitignore_entry}")
    else:
        gitignore_path.write_text(f"{gitignore_entry}\n")
        print("✅ Created .gitignore")

    print()
    print("=" * 60)
    print("✅ Setup complete!")
    print("=" * 60)

    # Show cd command only if project is not in current directory
    cd_cmd = "" if project_dir == Path.cwd() else f"cd {project_dir}\n   "
    script_name = module_name.replace("_", "-")

    message = SETUP_COMPLETE_MESSAGE.replace("CD_CMD", cd_cmd).replace(
        "SCRIPT_NAME", script_name
    )
    print(message)

    # Show merge note if any .new.py files were written
    if _new_files_written:
        print()
        print(
            "⚠️  Note: Some files could not be auto-upgraded because you customized them."
        )
        print("   Please manually merge the following files:")
        for new_file, original_file in _new_files_written:
            print(f"     • {new_file.name} → {original_file.name}")
        print()
        # Clear the list for potential subsequent runs
        _new_files_written.clear()

    return 0


# =============================================================================
# Main entry point
# =============================================================================


def is_uninitialized_folder(path: Path) -> bool:
    """Check if a folder appears to be completely uninitialized."""
    return (
        not (path / "pyproject.toml").exists() and not (path / "package.json").exists()
    )


def is_already_patched(path: Path) -> bool:
    """Check if a folder has already been patched by fastapi-vue-setup."""
    # Check for our scripts directory
    if (path / "scripts" / "fastapi-vue").exists():
        return True

    # Check for vite plugin in frontend
    if (path / "frontend" / "vite-plugin-fastapi.js").exists():
        return True

    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Set up FastAPI+Vue projects with integrated build/dev systems",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  fastapi-vue-setup my-new-project     Create a new project from scratch
  fastapi-vue-setup .                  Set up integration in current directory
  fastapi-vue-setup . --dry-run        Preview what would be done
""",
    )
    parser.add_argument(
        "project_dir",
        nargs="?",
        default=None,
        help="Project directory (use . for current directory)",
    )
    parser.add_argument("--module-name", help="Python module name (auto-detected)")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be done"
    )

    args = parser.parse_args()

    if args.project_dir is None:
        parser.print_help()
        return 0

    return cmd_setup(args)


if __name__ == "__main__":
    sys.exit(main())
