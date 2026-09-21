"""Operator entry point for checkpointed JVM campaigns and evidence publication."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestwin.api.governed_jvm_context import GovernedJvmSettings
from orchestwin.jvm_execution.operation_governance import content_hash
from orchestwin.jvm_execution.validation_campaign import JvmValidationCampaign, write_once
from orchestwin.jvm_execution.validation_harvest import (
    harvest_campaign,
    load_publication,
    publish_catalog,
)
from orchestwin.jvm_execution.validation_prerequisites import RunnerPrerequisiteCollector
from orchestwin.jvm_execution.validation_verification import read_document, require
from orchestwin.sandbox.execution_profiles import ExecutionTarget


async def database_action(args):
    # Explicit operator connection only: no dotenv, default DB, or stored credentials.
    url = os.environ.get("ORCHESTWIN_JVM_VALIDATION_DATABASE_URL")
    require(url is not None, "EXPLICIT_DATABASE_URL_REQUIRED")
    engine = create_async_engine(url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        if args.action == "publish":
            return await publish_catalog(
                sessions, root=args.root, expected_package_hash=args.package_hash
            )
        configuration = GovernedJvmSettings(_env_file=None, **read_document(args.configuration))
        target = ExecutionTarget(args.target)
        campaign = JvmValidationCampaign(
            sessions,
            config=configuration,
            output_root=args.root / "campaign",
            owner_user_id=args.owner,
            targets=(target,),
        )
        manifest = await campaign.prepare()
        if args.action == "prepare":
            return {"campaign_hash": content_hash(manifest), "scope": manifest}
        require(content_hash(manifest) == args.campaign_hash, "APPROVED_CAMPAIGN_CHANGED")
        await campaign.run(owner_approved=True)
        write_once(args.root / "database-export.json", await campaign.export_database(target))
        return {
            "campaign_hash": args.campaign_hash,
            "execution_complete": True,
            "level_d_validated": False,
        }
    finally:
        await engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    for name in ("capture-runners", "prepare", "run", "harvest", "verify", "publish"):
        command = actions.add_parser(name)
        command.add_argument("--root", type=Path, required=True)
        if name in {"prepare", "run"}:
            command.add_argument("--configuration", type=Path, required=True)
            command.add_argument("--owner", type=UUID, required=True)
            command.add_argument(
                "--target", choices=["JVM_JAVA", "JVM_KOTLIN", "JVM_SCALA"], required=True
            )
        if name == "run":
            command.add_argument(
                "--campaign-hash",
                required=True,
                help="Hash of the fixture scope explicitly approved by the operator.",
            )
        if name in {"harvest", "capture-runners"}:
            command.add_argument("--repo-root", type=Path, required=True)
        if name == "capture-runners":
            command.add_argument("--gradle-image-id", required=True)
            command.add_argument("--sbt-image-id", required=True)
            command.add_argument("--docker-context", required=True)
        if name == "harvest":
            command.add_argument("--distribution-path", type=Path, required=True)
        if name in {"verify", "publish"}:
            command.add_argument("--package-hash", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "capture-runners":
            result = RunnerPrerequisiteCollector(
                repo_root=args.repo_root,
                output_root=args.root / "prerequisites",
                images={"gradle": args.gradle_image_id, "sbt": args.sbt_image_id},
                docker_context=args.docker_context,
            ).capture()
        elif args.action == "harvest":
            result = harvest_campaign(
                root=args.root, repo_root=args.repo_root, distribution_path=args.distribution_path
            )
        elif args.action == "verify":
            catalog = load_publication(args.root, expected_package_hash=args.package_hash)
            result = {
                "package_verified": True,
                "catalog_hash": catalog.content_hash,
                "records": len(catalog.records),
            }
        else:
            result = asyncio.run(database_action(args), loop_factory=asyncio.SelectorEventLoop)
    except Exception as error:
        # Do not leak connection strings, source bytes, or driver exception details.
        print(json.dumps({"status": "FAILED", "error_type": type(error).__name__}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
