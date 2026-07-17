"""Static dependency rules for the Phase 4 modular-monolith boundaries."""

import ast
from pathlib import Path


TARGET_APPS = (
    "core",
    "tenants",
    "customers",
    "cards",
    "card_artwork",
    "integrations",
    "pos",
    "pos_dotykacka",
    "communications",
    "brevo",
    "wallets",
    "wallet_apple",
    "wallet_google",
    "billing",
    "printing",
    "enrollment",
    "marketing",
)

ALLOWED_TARGET_IMPORTS = {
    "core": {"core"},
    "tenants": {"core", "tenants"},
    "customers": {"core", "tenants", "customers"},
    "cards": {"core", "tenants", "customers", "cards"},
    "card_artwork": {"core", "tenants", "cards", "card_artwork"},
    "integrations": {"core", "tenants", "integrations"},
    "pos": {"core", "tenants", "customers", "integrations", "pos"},
    "pos_dotykacka": {
        "core",
        "tenants",
        "customers",
        "integrations",
        "pos",
        "pos_dotykacka",
    },
    "communications": {
        "core",
        "tenants",
        "customers",
        "integrations",
        "communications",
    },
    "brevo": {
        "core",
        "tenants",
        "customers",
        "integrations",
        "communications",
        "brevo",
    },
    "wallets": {
        "core",
        "tenants",
        "customers",
        "cards",
        "card_artwork",
        "wallets",
    },
    "wallet_apple": {
        "core",
        "tenants",
        "customers",
        "cards",
        "card_artwork",
        "wallets",
        "wallet_apple",
    },
    "wallet_google": {
        "core",
        "tenants",
        "customers",
        "cards",
        "card_artwork",
        "wallets",
        "wallet_google",
    },
    "billing": {"core", "tenants", "billing"},
    "printing": {
        "core",
        "tenants",
        "billing",
        "cards",
        "card_artwork",
        "printing",
    },
    "enrollment": {
        "core",
        "tenants",
        "customers",
        "cards",
        "integrations",
        "pos",
        "communications",
        "wallets",
        "billing",
        "enrollment",
    },
    "marketing": {"core", "billing", "marketing"},
}


def _import_roots(source: str, filename: str) -> set[str]:
    roots = set()
    tree = ast.parse(source, filename=filename)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def forbidden_imports(base_dir: Path) -> list[dict[str, str]]:
    """Return forbidden imports in new target apps; the legacy app is exempt."""

    target_set = set(TARGET_APPS)
    violations = []
    for app_name in TARGET_APPS:
        app_dir = base_dir / app_name
        if not app_dir.is_dir():
            violations.append(
                {"app": app_name, "file": app_name, "import": "<missing app>"}
            )
            continue
        for source_path in app_dir.rglob("*.py"):
            if any(part in {"migrations", "tests", "__pycache__"} for part in source_path.parts):
                continue
            imported_targets = _import_roots(
                source_path.read_text(encoding="utf-8"),
                str(source_path),
            ) & target_set
            for imported_app in sorted(
                imported_targets - ALLOWED_TARGET_IMPORTS[app_name]
            ):
                violations.append(
                    {
                        "app": app_name,
                        "file": str(source_path.relative_to(base_dir)),
                        "import": imported_app,
                    }
                )
    return violations
