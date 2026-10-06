"""Start the native local API with explicit real models and the Compose database."""

import argparse
import os
import sys
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import URL

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def configure(
    models: Path | None = None,
    access: str = "accounts",
    local_owner: str | None = None,
):
    values = dotenv_values(ROOT / "compose.env")
    for key in ("ORCHESTWIN_POSTGRES_PASSWORD", "ORCHESTWIN_AUTH_JWT_SECRET"):
        if not values.get(key):
            raise SystemExit("Missing local credential configuration: " + key)
    url = URL.create(
        "postgresql+psycopg",
        username=values.get("ORCHESTWIN_POSTGRES_USER", "orchestwin"),
        password=values["ORCHESTWIN_POSTGRES_PASSWORD"],
        host="127.0.0.1",
        port=15432,
        database=values.get("ORCHESTWIN_POSTGRES_DB", "orchestwin"),
        query={"connect_timeout": "10"},
    )
    os.environ["ORCHESTWIN_DATABASE_URL"] = url.render_as_string(hide_password=False)
    os.environ["ORCHESTWIN_AUTH_JWT_SECRET"] = values["ORCHESTWIN_AUTH_JWT_SECRET"]
    os.environ["ORCHESTWIN_CORS_ALLOWED_ORIGINS"] = (
        '["http://127.0.0.1:8080","http://127.0.0.1:5173"]'
    )
    if models is not None:
        os.environ["ORCHESTWIN_MODEL_RUNTIME_MODE"] = "REAL_REQUIRED"
        os.environ["ORCHESTWIN_MODEL_RUNTIME_CONFIG_FILE"] = str(models.resolve())
    os.environ["ORCHESTWIN_ACCESS_MODE"] = "LOCAL_OWNER" if access == "local" else "ACCOUNTS"
    if local_owner is not None:
        os.environ["ORCHESTWIN_LOCAL_OWNER_EMAIL"] = local_owner


def parse_arguments(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("migrate", "api", "check"))
    parser.add_argument("--models", type=Path)
    parser.add_argument("--access", choices=("accounts", "local"), default="accounts")
    parser.add_argument("--local-owner")
    args = parser.parse_args(arguments)
    if args.action != "migrate" and args.models is None:
        parser.error("--models must select an explicit real model configuration")
    if args.local_owner is not None and args.access != "local":
        parser.error("--local-owner requires --access local")
    return args


def main():
    args = parse_arguments()
    os.chdir(ROOT)
    configure(args.models, args.access, args.local_owner)
    if args.action == "migrate":
        from orchestwin.persistence import load_database_settings
        from orchestwin.persistence.migrate import upgrade_database

        upgrade_database(load_database_settings())
    elif args.action == "api":
        from orchestwin.api.server import main as serve

        serve([])
    else:
        import asyncio
        import json

        from check_real_model_runtime import check

        options = {"loop_factory": asyncio.SelectorEventLoop} if sys.platform == "win32" else {}
        report = asyncio.run(check(args.models.resolve()), **options)
        print(json.dumps(report, indent=2))
        raise SystemExit(0 if report["ready"] else 1)


if __name__ == "__main__":
    main()
