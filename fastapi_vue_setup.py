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
import tomllib
from pathlib import Path

import tomli_w

# Template directory
TEMPLATE_DIR = Path(__file__).parent / "template"

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

    with open(pyproject, "rb") as f:
        data = tomllib.load(f)

    if "project" in data and "name" in data["project"]:
        name = data["project"]["name"]
        return name.replace("-", "_")

    return None


def find_fastapi_app(module_dir: Path) -> tuple[Path, str] | None:
    """Find the FastAPI app in a module directory.

    Returns (file_path, app_variable_name) or None if not found.
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

    # Then check all .py files
    for path in module_dir.glob("*.py"):
        if path.name not in candidates:
            result = _find_app_in_file(path)
            if result:
                return path, result

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

    content = path.read_text()
    marker = "from fastapi_vue import Frontend"

    if marker in content:
        print(f"⚠️  Skipping {path} (already patched)")
        return False

    if dry_run:
        print(f"[DRY RUN] Would patch {path}")
        return True

    # Find where to insert the import (after other imports)
    lines = content.split("\n")
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

    # Try to patch lifespan function
    lifespan_patched = False

    # Look for async def lifespan pattern and insert after the opening (and docstring if present)
    lifespan_pattern = r"(async\s+def\s+lifespan\s*\([^)]*\)\s*(?:->.*?)?:\s*\n)"
    match = re.search(lifespan_pattern, content)
    if match:
        insert_pos = match.end()
        rest = content[insert_pos:]

        # Detect indentation from the next line
        indent_match = re.match(r"([ \t]*)", rest)
        indent = (
            indent_match.group(1) if indent_match and indent_match.group(1) else "    "
        )

        # Check if there's a docstring and skip past it
        docstring_pattern = r'^([ \t]*)("""[\s\S]*?"""|\'\'\'\'[\s\S]*?\'\'\')\s*\n'
        docstring_match = re.match(docstring_pattern, rest)
        if docstring_match:
            insert_pos += docstring_match.end()

        load_code = f"{indent}await frontend.load()\n"
        content = content[:insert_pos] + load_code + content[insert_pos:]
        lifespan_patched = True

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

    content = path.read_text()
    marker = "vite-plugin-fastapi"

    if marker in content:
        print(f"⚠️  Skipping {path} (already patched)")
        return False

    if dry_run:
        print(f"[DRY RUN] Would patch {path}")
        return True

    # Add import for the plugin at the top (after other imports)
    import_line = f"import fastapiVue from './{marker}.js'"

    lines = content.split("\n")
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

    content = target_file.read_text()

    # Check if already patched
    if "/api/health" in content:
        print(f"⚠️  Skipping {target_file} (already patched)")
        return False

    if dry_run:
        print(f"[DRY RUN] Would patch {target_file}")
        return True

    # Detect if TypeScript (has lang="ts" in script tag)
    is_typescript = 'lang="ts"' in content

    # Build the script content based on JS/TS
    script_addition = (
        TS_HEALTH_CHECK_SCRIPT if is_typescript else JS_HEALTH_CHECK_SCRIPT
    )

    # Insert script addition before </script>
    script_end_match = re.search(r"</script>", content)
    if script_end_match:
        insert_pos = script_end_match.start()
        content = content[:insert_pos] + script_addition + content[insert_pos:]

    # Insert status inline - find the best place based on file type
    # For HelloWorld.vue: insert before </h3>
    # For App.vue (minimal): insert before the last </p> in template
    if "HelloWorld" in str(target_file):
        # Insert before closing </h3>
        h3_close = content.find("</h3>")
        if h3_close != -1:
            content = (
                f"{content[:h3_close]}\n{STATUS_SPAN_TEMPLATE}    {content[h3_close:]}"
            )
    else:
        # Minimal App.vue - insert before the last </p> before </template>
        template_end = content.find("</template>")
        if template_end != -1:
            # Find last </p> before </template>
            last_p = content.rfind("</p>", 0, template_end)
            if last_p != -1:
                content = (
                    f"{content[:last_p]}\n{STATUS_SPAN_TEMPLATE}  {content[last_p:]}"
                )

    target_file.write_text(content)
    print(f"✅ Patched {target_file}")
    return True


def write_file(
    path: Path,
    content: str,
    overwrite: bool = True,
    dry_run: bool = False,
    executable: bool = False,
) -> bool:
    """Write content to a file, handling existing files and dry-run."""
    exists = path.exists()
    if exists and not overwrite:
        print(f"⚠️  Skipping {path} (exists)")
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


def merge_pyproject(data: dict, additions: dict, module_name: str) -> dict:
    """Merge additions into pyproject.toml data."""
    result = data.copy()

    # Ensure hatchling build system is configured
    if "build-system" not in result:
        result["build-system"] = {}
    result["build-system"]["requires"] = ["hatchling"]
    result["build-system"]["build-backend"] = "hatchling.build"

    # Add dependencies
    if "project" not in result:
        result["project"] = {}
    if "dependencies" not in result["project"]:
        result["project"]["dependencies"] = []

    # Add hatch build config
    if "tool" not in result:
        result["tool"] = {}
    if "hatch" not in result["tool"]:
        result["tool"]["hatch"] = {}
    if "build" not in result["tool"]["hatch"]:
        result["tool"]["hatch"]["build"] = {}

    hatch_build = additions["tool"]["hatch"]["build"]
    result["tool"]["hatch"]["build"]["packages"] = [
        p.replace("MODULE_NAME", module_name) for p in hatch_build["packages"]
    ]
    result["tool"]["hatch"]["build"]["artifacts"] = [
        a.replace("MODULE_NAME", module_name) for a in hatch_build["artifacts"]
    ]
    result["tool"]["hatch"]["build"]["only-packages"] = hatch_build["only-packages"]

    if "targets" not in result["tool"]["hatch"]["build"]:
        result["tool"]["hatch"]["build"]["targets"] = {}

    result["tool"]["hatch"]["build"]["targets"]["sdist"] = hatch_build["targets"][
        "sdist"
    ]

    return result


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
    app_info = find_fastapi_app(module_dir) if module_dir.exists() else None

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
    script_files = [
        (fastapi_vue_scripts / "util.py", "scripts/fastapi-vue/util.py"),
        (
            fastapi_vue_scripts / "build-frontend.py",
            "scripts/fastapi-vue/build-frontend.py",
        ),
        (scripts_dir / "devserver.py", "scripts/devserver.py"),
    ]

    for dest_path, template_path in script_files:
        template = load_template(template_path)
        content = render_template(template, **tpl_vars)
        is_executable = dest_path.name == "devserver.py"
        write_file(
            dest_path,
            content,
            overwrite=True,
            dry_run=dry_run,
            executable=is_executable,
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
    main_file = module_dir / "__main__.py"
    if not main_file.exists():
        template = load_template("backend/__main__.py")
        content = render_template(template, **tpl_vars)
        write_file(main_file, content, overwrite=False, dry_run=dry_run)

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
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)

        updated = merge_pyproject(data, PYPROJECT_ADDITIONS, module_name)

        # Add script entry pointing to the app we found/created
        if "scripts" not in updated["project"]:
            updated["project"]["scripts"] = {}
        script_name = module_name.replace("_", "-")
        updated["project"]["scripts"][script_name] = f"{module_name}.__main__:main"

        if dry_run:
            print(f"[DRY RUN] Would update {pyproject_path}")
        else:
            with open(pyproject_path, "wb") as f:
                tomli_w.dump(updated, f)
            print(f"✅ Updated {pyproject_path}")

    # === Add dependencies using uv ===
    if dry_run:
        print("[DRY RUN] Would run: uv add 'fastapi[standard]' fastapi-vue")
        print("[DRY RUN] Would run: uv add --group dev httpx")
    else:
        print("📦 Adding dependencies...")
        result = subprocess.run(
            ["uv", "add", "fastapi[standard]", "fastapi-vue"],
            cwd=project_dir,
            check=False,
        )
        if result.returncode != 0:
            print("⚠️  Failed to add main dependencies")
        result = subprocess.run(
            ["uv", "add", "--group", "dev", "httpx"],
            cwd=project_dir,
            check=False,
        )
        if result.returncode != 0:
            print("⚠️  Failed to add dev dependencies")

    # === Update .gitignore ===
    gitignore_path = project_dir / ".gitignore"
    gitignore_entry = f"{module_name}/frontend-build/"
    if gitignore_path.exists():
        gitignore_content = gitignore_path.read_text()
        if gitignore_entry not in gitignore_content:
            if dry_run:
                print(f"[DRY RUN] Would add {gitignore_entry} to .gitignore")
            else:
                with open(gitignore_path, "a") as f:
                    if not gitignore_content.endswith("\n"):
                        f.write("\n")
                    f.write(f"{gitignore_entry}\n")
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
