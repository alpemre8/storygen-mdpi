"""Finite sequential execution, honest status and isolated output guards."""
from __future__ import annotations

from datetime import datetime, timezone
import platform
from pathlib import Path
import subprocess
import time
import traceback
import json
import xml.etree.ElementTree as ET

import numpy as np

from ..io import sha256_file
from . import ANALYZER_VERSION, BlockedAnalysis
from .loader import load_dataset
from .analyses import ANALYSES
from .reporting import (TITLES, write_json, write_csv, export_analysis, write_documents,
                        artifact_manifest)


def source_identity(project):
    files=sorted((project/"evaluation/src/storygen_evaluation/reviewer").glob("*.py"))
    files += [project/"evaluation/cli/run_reviewer_analyses.py"]
    return dict(commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=project,text=True).strip(),
                dirty=bool(subprocess.check_output(["git","status","--porcelain"],cwd=project,text=True).strip()),
                source_files=[dict(repository_relative_path=str(p.relative_to(project)),sha256=sha256_file(p)) for p in files])


def validate_test_receipt(path):
    receipt=json.loads(Path(path).read_text())
    for key in ("junit","log"):
        ref=receipt[key]
        if sha256_file(Path(ref["path"])) != ref["sha256"]:
            raise RuntimeError("Test evidence hash mismatch")
    root=ET.parse(receipt["junit"]["path"]).getroot()
    cases=root.findall(".//testcase")
    failures=sum(bool(c.findall("failure") or c.findall("error")) for c in cases)
    skipped=sum(bool(c.findall("skipped")) for c in cases)
    new=sum(c.attrib.get("classname","").endswith("test_reviewer") for c in cases)
    if failures or skipped or receipt.get("passed")!=len(cases) or receipt.get("new_count")!=new or receipt.get("existing_count")!=len(cases)-new or len(cases)-new<53:
        raise RuntimeError("P01B requires passing existing and frozen-depot tests without skips")
    if receipt.get("failed")!=0 or receipt.get("skipped")!=0:
        raise RuntimeError("Nonpassing test receipt")
    sources=receipt.get("tested_source_files",[])
    if not sources:
        raise RuntimeError("Tested source identities missing")
    for source in sources:
        if sha256_file(Path(source["path"]))!=source["sha256"]:
            raise RuntimeError("Source changed after regression tests")
    return receipt


def run_pipeline(plan_path,output,artifact_paths,tests,command):
    output=Path(output)
    # A directory containing only a frozen plan/evidence/logs is permitted for
    # this initial execution. Any existing result/report forbids overwriting.
    if (output/"ANALYSIS_STATUS.json").exists() or any((output/"results"/f"A{i:02d}").exists() for i in range(1,11)):
        raise RuntimeError("Existing reviewer result directory; use a NEW output directory")
    output.mkdir(parents=True,exist_ok=True)
    for name in ("results","tables","logs","evidence"):
        (output/name).mkdir(exist_ok=True)
    started=datetime.now(timezone.utc).isoformat()
    status=dict(analyzer_version=ANALYZER_VERSION,phase_status="RUNNING",analyses={})
    write_json(output/"ANALYSIS_STATUS.json",status)
    def progress(message):
        print(message,flush=True)
        with (output/"logs/progress.log").open("a") as f:
            f.write(message+"\n")
    progress("INPUT validation started; no inference")
    try:
        dataset=load_dataset(Path(plan_path),artifact_paths)
    except Exception as exc:
        status.update(phase_status="FAIL",input_error=str(exc))
        write_json(output/"ANALYSIS_STATUS.json",status)
        (output/"logs/input_error.log").write_text(traceback.format_exc())
        (output/"P01B_REPORT.md").write_text(f"# P01B\n\nFAIL: input verification failed: {exc}. No diagnostic PASS was produced.\n")
        raise
    project=Path(__file__).resolve().parents[4]
    provenance={**dataset.provenance,"implementation":source_identity(project),
                "runtime":{"python":platform.python_version(),"numpy":np.__version__}}
    write_json(output/"INPUT_PROVENANCE.json",provenance)
    write_json(output/"evidence/baseline_validation.json",dataset.validation)
    write_json(output/"evidence/canonical_tasks.json",dataset.tasks)
    with (output/"evidence/canonical_analysis_view.jsonl").open("w",encoding="utf-8") as stream:
        import json
        for model in dataset.models:
            for condition in ("DP-v1","CG-v1"):
                for record in dataset.rows(model,condition):
                    stream.write(json.dumps(record,sort_keys=True,ensure_ascii=False,allow_nan=False)+"\n")
    progress("INPUT PASS: 1920 exact records, 1852 measurable, 68 failed; common186")
    results,tables={},[]
    for i,analyze in enumerate(ANALYSES,1):
        aid=f"A{i:02d}"
        tick=time.monotonic()
        progress(f"{aid} START {TITLES[i-1]}")
        try:
            result=analyze(dataset,artifact_paths) if aid=="A09" else analyze(dataset)
            if not result.get("summary"):
                raise RuntimeError("Empty scientific summary")
            tables += export_analysis(output,i,result)
            results[aid]=result
            entry=dict(status="PASS",evidence=f"results/{aid}/results.json")
        except BlockedAnalysis as exc:
            root=output/"results"/aid
            root.mkdir(exist_ok=True)
            entry=dict(status="BLOCKED",reason=str(exc),evidence=f"results/{aid}/blocked.json")
            write_json(root/"blocked.json",entry)
        except Exception as exc:
            entry=dict(status="FAIL",reason=str(exc),evidence=f"logs/{aid}_error.log")
            (output/entry["evidence"]).write_text(traceback.format_exc())
        elapsed=int(time.monotonic()-tick)
        entry["elapsed_hh_mm_ss"]=f"{elapsed//3600:02d}:{elapsed//60%60:02d}:{elapsed%60:02d}"
        status["analyses"][aid]=entry
        progress(f"{aid} {entry['status']} elapsed {entry['elapsed_hh_mm_ss']}"+(" reason="+entry["reason"] if "reason" in entry else ""))
        write_json(output/"ANALYSIS_STATUS.json",status)
    states=[s["status"] for s in status["analyses"].values()]
    status["phase_status"]="FAIL" if "FAIL" in states else "PARTIAL" if "BLOCKED" in states or tests.get("failed",1) or tests.get("skipped",1) else "PASS"
    status["phase_gate_note"]="Final historical integrity verification and complete deliverable checks required before local PASS tag"
    write_json(output/"evidence/execution_metadata.json",dict(started_utc=started,finished_utc=datetime.now(timezone.utc).isoformat(),command=command,source=provenance["implementation"]))
    write_documents(output,dataset,status,tables,results,tests,command)
    write_json(output/"evidence/table_catalog.json",tables)
    artifact_manifest(output)
    progress("P01B computational status "+status["phase_status"]+"; STOP")
    return status
