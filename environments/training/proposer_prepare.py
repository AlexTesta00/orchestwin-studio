"""Materialize verified synthetic references using production proposer prompts.

No model, provider response, or application artifact is fabricated. A capture
port stops before inference and an explicitly synthetic author supplies the
reference. Publication requires isolated Node execution of every whole bundle.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from proposer_curriculum import (  # noqa: E402
    CURRICULUM_ID,
    EXCLUDED_FAMILIES,
    NumericFamily,
    StatefulFamily,
    all_families,
    js,
    source_bundle,
)
from pydantic import TypeAdapter  # noqa: E402

from orchestwin.models.proposal_evidence import evidence_application  # noqa: E402
from orchestwin.models.proposal_generation import (  # noqa: E402
    ProposalGenerator,
    ProposalModelConfiguration,
)
from orchestwin.models.source_context import (  # noqa: E402
    implementation_contract,
    implementation_work_order,
)
from orchestwin.models.source_file_generation import (  # noqa: E402
    MANIFEST_CONTRACT,
    PROTOCOL,
    generate_source_files,
)
from orchestwin.models.structured_generation import ModelRuntimeIdentity  # noqa: E402
from orchestwin.projects.requirements_primitives import (  # noqa: E402
    canonical_json,
    snapshot_content_hash,
)

NODE_IMAGE = "docker.io/library/node:26.7.0-bookworm-slim@sha256:4db36457f406501e6f608802e5da617e5fbd0e80b75901b6a09de1ae5a667d32"
MODEL = "Qwen/Qwen3-4B-Instruct-2507"
REVISION = "abcc171021d4f320b2e7f47c6f0deca67ded870c"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    Path(path).write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )


def context_for(family, locale, prototype):
    identifier = str(uuid5(NAMESPACE_URL, CURRICULUM_ID + "/" + family.name + "/" + locale))
    stateful = isinstance(family, StatefulFamily)
    signature = (
        "createService(): {apply(action: string, name: string, amount: number): object, snapshot(): object}"
        if stateful
        else "compute(a: number, b: number, mode: string): number"
    )
    statements = [
        dict(
            code="REQ-001",
            title=family.title[0],
            statement=family.rule + " Public interface: " + signature,
        )
    ]
    criteria = [
        dict(
            code="AC-001",
            statement=(
                "Bind the exact prototype fields and operation values to the public core. Show the actual result on the separate result screen; Back preserves field values. "
                "Convert numeric form text (decimal dot or comma) before invoking numeric parameters. Reject blank, nonfinite, malformed or out-of-domain inputs visibly without losing previous state."
            ),
        )
    ]
    return dict(
        project_id=identifier,
        target_selection={"target": "WEB_STATIC"},
        fixed_files=[],
        provenance_references=[
            dict(
                kind="ARCHITECTURE",
                reference_id="synthetic:" + identifier,
                version_number=1,
                content_hash=snapshot_content_hash(family.rule),
            )
        ],
        requirements=dict(content=dict(requirements=statements, acceptance_criteria=criteria)),
        design=dict(content=dict(prototype=prototype)),
        architecture=dict(
            content=dict(
                interface=signature,
                representation="The core uses the English operation identifiers even when select labels are translated.",
                operations=[
                    dict(value=mode[0], label=mode[0 if locale == "en" else 1])
                    for mode in family.modes
                ],
                state="One private state store per createService instance; UI retains one instance."
                if stateful
                else "Pure computations; input text persists while navigating between screens.",
            )
        ),
    )


def manifest_for(family, context):
    stateful = isinstance(family, StatefulFamily)
    interface = context["architecture"]["content"]["interface"]
    # The manifest names exported callables. Service methods remain documented
    # in the business context; an object type body is not a callable signature.
    exported_interface = "createService(): object" if stateful else interface
    work_order = implementation_work_order(implementation_contract(context))
    return dict(
        rationale="Implement the selected design with a shared browser and Node core.",
        behavior_plan=dict(
            inputs_and_validation="Validate every required field and numeric domain before changing state. Parse decimal form text only at the UI boundary.",
            state_and_lifetime="Each service owns an isolated private map; one browser instance survives successive submissions. Return defensive copies."
            if stateful
            else "The core is pure. Form fields remain intact when returning from results.",
            observable_outputs="Compute real outputs, expose them through the documented core, and display them on the separate result screen. Show invalid input visibly.",
        ),
        acceptance_checks=[
            dict(
                source=statement["source"],
                public_interface=interface,
                observable_postcondition=(
                    "Reject an empty "
                    + statement["field_name"]
                    + " field before producing a result or changing state."
                    if "field_name" in statement
                    else family.rule
                    if index == 0
                    else "Show the real core result in SCR-002; the Back link returns to SCR-001 with unchanged field values and no lost records."
                ),
            )
            for index, statement in enumerate(work_order["statements"])
        ],
        files=[
            dict(
                normalized_path="index.html",
                media_type="text/html",
                purpose="Render the exact prototype and load the shared implementation.",
                interface="DOM: form, first, second, mode, entry, result, output, error, back",
                depends_on=[],
            ),
            dict(
                normalized_path="app.js",
                media_type="text/javascript",
                purpose="Implement validated business behavior and browser bindings.",
                interface=exported_interface + "; readNumber(raw: string): number",
                depends_on=["index.html"],
            ),
            dict(
                normalized_path="app.test.cjs",
                media_type="text/javascript",
                purpose="Assert the actual core behavior and invalid input handling.",
                interface="test(name, callback): void",
                depends_on=["app.js"],
            ),
        ],
    )


class _Captured(Exception):
    pass


class _MemoryScope:
    """Satisfy pipeline bookkeeping in memory; never persist model evidence."""

    async def begin(self, **kwargs):
        pass

    async def append(self, **kwargs):
        pass


class _CapturePort:
    def __init__(self):
        self.request = None

    async def generate(self, request):
        self.request = request
        raise _Captured


class ReferenceAuthor:
    def __init__(self, family, locale, files, manifest):
        self.family, self.locale, self.files, self.manifest = family, locale, files, manifest
        self.rows = []
        self.port = _CapturePort()
        self.configuration = ProposalModelConfiguration(
            base_url="http://127.0.0.1:1",
            model_name="synthetic-reference-author-no-inference",
            token_file=ROOT / "environments/training/proposer_never_read.secret",
            identity=ModelRuntimeIdentity(
                provider_id="synthetic-reference-author",
                runtime_id="capture-before-inference",
                base_model_repository=MODEL,
                base_model_revision=REVISION,
                tokenizer_revision=REVISION,
                configuration_sha256="0" * 64,
            ),
        )
        self.production = ProposalGenerator(self.configuration, self.port)
        self._proposal_evidence_store = _MemoryScope()

    async def generate(self, **kwargs):
        try:
            await self.production.generate(**kwargs)
        except _Captured:
            request = self.port.request
        else:
            raise AssertionError("The reference author must never perform inference")
        step = kwargs["context"].get("source_step")
        path = step["file"]["normalized_path"] if step else None
        reference = {"content": self.files[path]} if path else self.manifest
        result = TypeAdapter(kwargs["output_type"]).validate_json(
            canonical_json(reference), strict=True, extra="forbid"
        )
        self.rows.append(
            dict(
                id=f"{self.family.name}-{self.locale}-{path or 'manifest'}",
                group_id=self.family.name,
                semantic_family=self.family.name,
                split=self.family.split,
                locale=self.locale,
                component="source-file" if path else "source-manifest",
                source_path=path,
                step=path or "manifest",
                provenance="SYNTHETIC_ENGINEER_AUTHORED",
                provider_inference_performed=False,
                messages=[
                    dict(role="system", content=request.system_instruction),
                    dict(role="user", content=request.input_payload_json),
                    dict(role="assistant", content=canonical_json(reference)),
                ],
            )
        )
        return result

    @evidence_application
    async def capture(self, *, owner_user_id, project_id, context):
        return await generate_source_files(self, task="web-source", context=context)


def capture_rows(family, locale):
    files, prototype = source_bundle(family, locale)
    context = context_for(family, locale, prototype)
    author = ReferenceAuthor(family, locale, files, manifest_for(family, context))
    result = asyncio.run(
        author.capture(
            owner_user_id=uuid5(NAMESPACE_URL, "synthetic-reference-owner"),
            project_id=uuid5(NAMESPACE_URL, family.name + locale),
            context=context,
        )
    )
    assert {item.normalized_path: item.content for item in result.output.files} == files
    return author.rows, files, prototype


def independent_oracle(family):
    """Separate execution oracle, including classic-browser execution without CJS.

    The DOM double checks event wiring and screen state, not layout/accessibility.
    It does not reuse the reference's own node:test file as an admission oracle.
    """
    stateful = isinstance(family, StatefulFamily)
    code = """const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const api = require('./app.js');
function browser() {
  const nodes = Object.fromEntries(['form','first','second','mode','entry','result','output','error','back'].map(id => [id, {
    value:'',textContent:'',hidden:id === 'result',handlers:{},
    addEventListener(type, handler) { this.handlers[type] = handler; }, focus() { this.focused = true; }
  }]));
  const context = {document:{getElementById(id) { assert.ok(nodes[id], 'unknown DOM id'); return nodes[id]; }}};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(__dirname + '/app.js','utf8'), context, {timeout:1000});
  return {nodes,context,submit() { nodes.form.handlers.submit({preventDefault(){}}); }};
}
test('independent numeric parsing adversarial inputs', () => {
  assert.equal(api.readNumber('+1,25'),1.25);
  assert.equal(api.readNumber('.5'),0.5);
  for(const bad of ['', ' ', '0x10', '1e3', '1.2.3', 'NaN', 'Infinity', null, 3]) assert.throws(() => api.readNumber(bad));
});
"""
    if stateful:
        code += "test('independent state oracle with prototype-sensitive keys', () => {\n  const service = api.createService();\n"
        for mode, label, amount, expected in family.sequence:
            code += f"  service.apply({js(mode)}, {js(label)}, {amount}); assert.deepEqual(service.snapshot(), {js(expected)});\n"
        code += f"  const before = service.snapshot(); assert.throws(() => service.apply(...{js(family.invalid)}));\n"
        code += f"  for(const value of ['', '  ', null, 2]) assert.throws(() => service.apply({js(family.modes[0][0])},value,1));\n"
        code += f"  for(const amount of [0,-1,1.5,NaN,Infinity,'3']) assert.throws(() => service.apply({js(family.modes[0][0])},'Other',amount));\n"
        code += "  assert.throws(() => service.apply('UNKNOWN','Other',2)); assert.deepEqual(service.snapshot(),before);\n  const copy=service.snapshot(); copy.Other=42; assert.deepEqual(service.snapshot(),before);\n  assert.deepEqual(api.createService().snapshot(),{});\n"
        code += f"  const isolated=api.createService(); isolated.apply({js(family.modes[0][0])},'__proto__',2); assert.equal(isolated.snapshot()['__proto__'],2);\n}});\n"
        first = family.sequence[0]
        second = family.sequence[1]
        core_assertion = "assert.equal(typeof context.createService,'function');"
        first_values = first[1], str(first[2]), first[0], js(first[3])
        second_values = second[1], str(second[2]), second[0], js(second[3])
    else:
        code += "test('independent literal business oracles', () => {\n"
        for a, b, mode, expected in family.examples:
            code += (
                f"  assert.ok(Math.abs(api.compute({a}, {b}, {js(mode)}) - {expected}) <= 1e-9);\n"
            )
        code += f"  assert.throws(() => api.compute(...{js(family.invalid)}));\n"
        code += f"  for(const a of ['3',NaN,Infinity,null]) assert.throws(() => api.compute(a,2,{js(family.modes[0][0])}));\n"
        code += "  assert.throws(() => api.compute(3,2,'UNKNOWN'));\n});\n"
        first = family.examples[0]
        second = family.examples[1]
        core_assertion = "assert.equal(typeof context.compute,'function');"
        first_values = str(first[0]), str(first[1]), first[2], str(float(f"{first[3]:.12g}"))
        second_values = str(second[0]), str(second[1]), second[2], str(float(f"{second[3]:.12g}"))
    code += (
        "test('browser invokes same core and preserves screen and input state', () => {\n  const {nodes,context,submit}=browser();\n  "
        + core_assertion
        + "\n"
    )
    code += "  submit(); assert.ok(nodes.error.textContent); assert.equal(nodes.entry.hidden,false); assert.equal(nodes.result.hidden,true);\n"
    for a, b, mode, expected in (first_values, second_values):
        code += f"  nodes.first.value={js(a)}; nodes.second.value={js(b)}; nodes.mode.value={js(mode)}; submit();\n"
        code += "  assert.equal(nodes.error.textContent,''); assert.equal(nodes.entry.hidden,true); assert.equal(nodes.result.hidden,false);\n"
        if stateful:
            code += f"  assert.equal(nodes.output.textContent,{js(expected)});\n"
        else:
            code += (
                f"  assert.ok(Math.abs(Number(nodes.output.textContent) - {expected}) < 1e-9);\n"
            )
        code += "  nodes.back.handlers.click({preventDefault(){}}); assert.equal(nodes.entry.hidden,false); assert.equal(nodes.result.hidden,true);\n"
        code += f"  assert.equal(nodes.first.value,{js(a)}); assert.equal(nodes.second.value,{js(b)});\n"
    code += "  nodes.second.value='invalid'; submit(); assert.ok(nodes.error.textContent); assert.equal(nodes.result.hidden,true);\n});\n"
    return code


def docker_verify(output, bundles):
    runner = """const fs=require('node:fs');const cp=require('node:child_process');
const cases=JSON.parse(fs.readFileSync('/data/bundles.json','utf8'));
const report=[];
for(const name of cases){
 const result=cp.spawnSync(process.execPath,['--test','app.test.cjs','oracle.cjs'],{cwd:'/data/references/'+name,encoding:'utf8',timeout:15000});
 report.push({case:name,passed:result.status===0,exit_code:result.status,stdout:result.stdout,stderr:result.stderr});
 if(result.status!==0){process.stdout.write(JSON.stringify(report));process.exit(1);}
}
process.stdout.write(JSON.stringify(report));
"""
    (output / "verify.cjs").write_text(runner, encoding="utf-8")
    save(output / "bundles.json", bundles)
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--user",
        "1000:1000",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "128",
        "--memory",
        "512m",
        "--cpus",
        "2",
        "--mount",
        f"type=bind,source={output.resolve()},target=/data,readonly",
        NODE_IMAGE,
        "node",
        "/data/verify.cjs",
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        timeout=180,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    (output / "docker-verification.stdout.json").write_bytes(result.stdout)
    (output / "docker-verification.stderr.txt").write_bytes(result.stderr)
    if result.returncode != 0:
        raise RuntimeError(
            "Isolated reference verification failed; dataset was not published. See docker-verification files."
        )
    report = json.loads(result.stdout)
    if len(report) != len(bundles) or not all(item["passed"] for item in report):
        raise RuntimeError("Every reference bundle must pass before dataset publication")
    return dict(
        image=NODE_IMAGE,
        bundles=len(report),
        all_passed=True,
        evidence_sha256=digest(output / "docker-verification.stdout.json"),
        network="none",
        read_only=True,
        limits="512MiB/2CPU/128pids",
        oracle_scope="Literal expected values, state isolation, failure atomicity, classic-browser VM and DOM event double; not real rendered-browser proof",
    )


def prepare(output, *, dataset_version=1):
    if type(dataset_version) is not int or dataset_version < 1:
        raise ValueError("dataset version must be a positive integer")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "references").mkdir()
    rows, bundles, references = [], [], {}
    for family in all_families():
        for locale in ("en", "it"):
            group_rows, files, prototype = capture_rows(family, locale)
            name = family.name + "-" + locale
            folder = output / "references" / name
            folder.mkdir()
            for path, content in files.items():
                (folder / path).write_text(content, encoding="utf-8", newline="\n")
            (folder / "oracle.cjs").write_text(
                independent_oracle(family), encoding="utf-8", newline="\n"
            )
            save(folder / "prototype.json", prototype)
            references[name] = {path.name: digest(path) for path in folder.iterdir()}
            rows.extend(group_rows)
            bundles.append(name)
    verification = docker_verify(output, bundles)
    files = {}
    for split in ("train", "validation"):
        selected = [row for row in rows if row["split"] == split]
        path = output / (split + ".jsonl")
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            for row in selected:
                stream.write(canonical_json(row) + "\n")
        files[path.name] = dict(
            sha256=digest(path), rows=len(selected), size_bytes=path.stat().st_size
        )
    source_paths = [
        Path(__file__),
        Path(__file__).with_name("proposer_curriculum.py"),
        ROOT / "src/orchestwin/models/source_file_generation.py",
        ROOT / "src/orchestwin/models/proposal_generation.py",
    ]
    manifest = dict(
        curriculum_id=CURRICULUM_ID,
        dataset_version=dataset_version,
        provenance="SYNTHETIC_ENGINEER_AUTHORED",
        source_generation_protocol=PROTOCOL,
        source_manifest_contract=MANIFEST_CONTRACT,
        files=files,
        references=references,
        verification=verification,
        excluded_semantic_families=list(EXCLUDED_FAMILIES),
        semantic_family_splits={
            split: [family.name for family in all_families() if family.split == split]
            for split in ("train", "validation")
        },
        locales=["en", "it"],
        row_components=["source-manifest", "source-file"],
        template_diversity=dict(
            numeric_business_families=len(
                [family for family in all_families() if isinstance(family, NumericFamily)]
            ),
            stateful_business_families=len(
                [family for family in all_families() if isinstance(family, StatefulFamily)]
            ),
            core_generators=2,
            shared_form_layouts=1,
        ),
        source_sha256={
            str(path.relative_to(ROOT)).replace("\\", "/"): digest(path) for path in source_paths
        },
        tokenization_audited=False,
        provider_inference_performed=False,
        model_training_performed=False,
        model_quality_measured=False,
        limitations=[
            "Compact synthetic development curriculum; not a large or representative production dataset.",
            "Translated examples share a semantic family and never cross splits.",
            "Distinct business families reuse two core generators and one form layout; family count is not architectural diversity.",
            "Reference Node tests and independent execution oracles share engineer-authored specifications; neither demonstrates model capability.",
            "Manifest wording follows current production prompts, but no human project approval is claimed.",
            "Requires tokenizer audit without truncation before training; no held-out qualification cases are included.",
        ],
    )
    save(output / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--dataset-version",
        type=int,
        default=1,
        help="Artifact revision within the same semantic curriculum; never overwrite an existing output.",
    )
    args = parser.parse_args()
    manifest = prepare(args.output, dataset_version=args.dataset_version)
    print(
        json.dumps(
            dict(
                output=str(args.output.resolve()),
                files=manifest["files"],
                verification=manifest["verification"],
            )
        )
    )


if __name__ == "__main__":
    main()
