"""IEEE-style English report from sealed computed results, without source text."""

from pathlib import Path
import shutil
import subprocess
from common import MODULES, read, sha, write
from analyses import NAMES

TITLE = (
    "E06: Statistical Robustness, Failure-Aware Evaluation, and Sensitivity "
    "Analyses for Feature-Curve-Guided Screenplay Rewriting"
)
COVERAGE = """# E06 reviewer coverage

| Module | Reviewer comment | Portion addressed |
|---|---|---|
| A01 | R3 C5 | Exact MAINTAIN tolerance sensitivity; canonical DA unchanged. |
| A02 | R3 C7 | Trivial direction-label baselines only. The no-guidance rewrite baseline belongs to E02. |
| A03 | R3 C4; R1 C7 | Failure-zero all-attempt DA and explicit observation ledger. |
| A04 | R1 C7; R3 C4 | Excluded unique tasks versus missing observations, feature/length/film/direction composition. |
| A05 | R1 C7 | All models, both conditions, all five feature-specific TI/DA groups. |
| A06 | R1 C6 | Output/input length ratios only. Content preservation remains separate. |
| A07 | R1 C3 | Small-positive-improvement threshold sensitivity only; previous distance analyses also contribute. |

Multi-part comments are not declared fully resolved by E06. No human validation,
independent feature extraction, semantic or dramaturgical judgment, new rewrite
model, or isolated numerical-guidance causal experiment is supplied here.
"""


def escape(value):
    return "".join(
        {
            "\\": r"\textbackslash{}",
            "&": r"\&",
            "%": r"\%",
            "$": r"\$",
            "#": r"\#",
            "_": r"\_",
            "{": r"\{",
            "}": r"\}",
            "~": r"\textasciitilde{}",
            "^": r"\textasciicircum{}",
        }.get(c, c)
        for c in str(value)
    )


def cell(value):
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def markdown_table(rows, fields):
    return (
        "\n".join(
            [
                "| " + " | ".join(fields) + " |",
                "| " + " | ".join("---" for _ in fields) + " |",
                *[
                    "| "
                    + " | ".join(cell(r.get(k)).replace("|", "/") for k in fields)
                    + " |"
                    for r in rows
                ],
            ]
        )
        + "\n"
    )


def seal_inputs(run):
    paths = [
        p
        for p in Path(run).rglob("*")
        if p.is_file()
        and p.parts[-2] not in ("08_logs",)
        and (
            p.name
            in (
                "E06_VALIDATION.json",
                "E06_PROVENANCE.json",
                "E06_RESULTS_SUMMARY.json",
                "IMPLEMENTATION_IDENTITY.json",
            )
            or any(
                part
                in (
                    "02_canonical_metrics",
                    "03_analyses",
                    "04_cross_validation",
                    "05_tables",
                )
                for part in p.parts
            )
        )
    ]
    return {str(p.relative_to(run)): sha(p) for p in sorted(paths)}


def verify_seal(run):
    run = Path(run)
    seal = read(run / "00_manifest/RESULT_SEAL.json")
    if any(sha(run / p) != h for p, h in seal["files"].items()):
        raise ValueError("Changed computed result: report refused")
    if seal["dataset_kind"] != read(run / "E06_MANIFEST.json")["dataset_kind"]:
        raise ValueError("Synthetic/real report boundary violation")
    return seal


def report(run, output=None, compile_pdf=False, fixture=False):
    run = Path(run)
    verify_seal(run)
    manifest = read(run / "E06_MANIFEST.json")
    if (manifest["dataset_kind"] == "SYNTHETIC") != fixture:
        raise ValueError("Synthetic/real report boundary violation")
    if not fixture and read(run / "E06_STATUS.json")["status"] != "COMPLETE":
        raise ValueError("Real report requires a completed validated analysis")
    output = Path(output) if output else run / "07_report"
    output.mkdir(parents=True, exist_ok=False)
    modules = {a: read(run / "03_analyses" / a / RESULT_JSON[a]) for a in MODULES}
    validation = read(run / "E06_VALIDATION.json")
    prefix = "SYNTHETIC FIXTURE — NOT SCIENTIFIC EVIDENCE. " if fixture else ""
    lines = [
        r"\documentclass[conference]{IEEEtran}",
        r"\usepackage[T1]{fontenc}",
        r"\usepackage{url}",
        r"\usepackage{graphicx}",
        r"\begin{document}",
        r"\title{" + escape(prefix + TITLE) + "}",
        r"\author{\IEEEauthorblockN{StoryGen E06 reproducible analysis}}",
        r"\maketitle",
        r"\begin{abstract}"
        + escape(
            prefix
            + "This retrospective deterministic analysis evaluates maintain tolerance, analytic direction baselines, failure-aware performance, exclusions, feature-specific performance, text length and small-improvement sensitivity. All tables are derived from persisted machine-readable E06 results. Canonical task-macro TI and DA remain unchanged. Results are descriptive; execution does not establish independent scientific validity."
        )
        + r"\end{abstract}",
    ]
    sections = [
        (
            "Introduction and Reviewer Motivation",
            "E06 addresses bounded reviewer requests using existing historical outputs, without inference or new generation. Threshold sensitivities are retrospective diagnostics, not newly preregistered primary metrics.",
        ),
        (
            "Historical Benchmark and Data Provenance",
            "The intended frozen design is 10 screenplays, 48 base intervals, five features, four models and two prompting packages: 240 tasks and 1920 planned observations. These are design expectations; actual eligibility is computed and validated. Exact consumed paths and SHA-256 identities are in E06_PROVENANCE.json. Original Qwen measurements are retained; E01 Mistral values are not substituted.",
        ),
        (
            "Experimental Design",
            "Tasks are the primary aggregation units. Feature tasks sharing a base interval are not independent screenplay samples. Global-common, condition-conditional, within-model paired and all-attempt populations are explicitly distinguished.",
        ),
        (
            "Canonical Metrics and Statistical Methods",
            "For task j, dB=mean absolute source-target distance and dA=mean absolute rewrite-target distance. TI=1[dA<dB]; DA=mean scene-level exact sign matches. G=dB-dA. Aggregation macro-averages tasks. All-attempt metrics set failed contributions to zero, preserving every planned task. Missing distances remain undefined. All reported summaries and paired differences are descriptive; no confidence intervals or hypothesis tests are claimed. No bootstrap resampling is invoked. Null denotes undefined statistics, including no eligible records or insufficient sample size for sample standard deviation.",
        ),
    ]
    for title, text in sections:
        lines.extend([r"\section{" + escape(title) + "}", escape(text)])
    overview = []
    for a in MODULES:
        m = modules[a]
        lines.extend(
            [
                r"\section{" + escape(a + " — " + NAMES[a]) + "}",
                escape("Module status: " + m["status"] + ". " + m["denominator"]),
            ]
        )
        if a == "A06":
            lines.append(escape(m["limitation"]))
        if a == "A02":
            lines.append(
                escape(
                    "Policies predict directions only; they do not generate text and have no TI."
                )
            )
        if a == "A07":
            lines.append(
                escape(
                    "Threshold values do not establish human-perceived significance."
                )
            )
        if a == "A01":
            lines.append(
                escape(
                    "Llama direction contributions distinguish condition-conditional, within-model paired and global-common populations. Each hit is weighted by 1/L and then 1/N for the named condition population. The contributions sum to its CG-minus-DP DA difference."
                )
            )
        for name, rows in m["tables"].items():
            if not rows:
                lines.append(escape(name + ": no eligible rows; see module status."))
                continue
            # All complete tables remain in CSV/Markdown. Two-column numeric slices
            # keep IEEE pages readable; no record is dropped from these slices.
            scalar_fields = [
                k
                for k in rows[0]
                if any(
                    isinstance(r.get(k), (int, float))
                    and not isinstance(r.get(k), bool)
                    for r in rows
                )
            ]
            id_fields = [
                k
                for k in (
                    "model",
                    "condition",
                    "feature",
                    "policy",
                    "direction",
                    "source_basis",
                    "task_id",
                    "epsilon",
                    "tolerance",
                    "interval_length",
                )
                if k in rows[0]
            ]
            md = markdown_table(rows, list(rows[0]))
            (output / (name.removesuffix(".csv") + ".md")).write_text(md)
            lines.append(
                escape("Complete table: " + name + " (" + str(len(rows)) + " rows).")
            )
            # Avoid thousands of scene/task rows in the narrative, retaining all
            # rows in linked sidecars and including every aggregate metric table.
            aggregate = not any(k in rows[0] for k in ("scene_id", "task_id"))
            if aggregate:
                priority = (
                    "canonical_DA",
                    "tolerance_adjusted_DA",
                    "DA_change_pp",
                    "maintain_accuracy",
                    "task_macro_contribution",
                    "CG_minus_DP_contribution_pp",
                    "task_macro_DA",
                    "scene_pooled_proportion",
                    "conditional_TI",
                    "conditional_DA",
                    "all_attempt_TI",
                    "all_attempt_DA",
                    "valid_tasks",
                    "missing_tasks",
                    "excluded_unique_tasks",
                    "scene_positions",
                    "mean",
                    "median",
                    "sd",
                    "canonical_TI",
                    "threshold_adjusted_TI",
                    "all_attempt_threshold_TI",
                    "TI_reduction_pp",
                )
                chosen = [
                    k for k in priority if k in scalar_fields and k not in id_fields
                ][:5]
                if not chosen:
                    chosen = [k for k in scalar_fields if k not in id_fields][:5]
                if chosen:
                    lines.extend(
                        [
                            r"\begin{table*}[tp]\centering\scriptsize",
                            r"\caption{"
                            + escape(
                                a
                                + " "
                                + name
                                + "; complete precision and remaining columns in companion table"
                            )
                            + "}",
                            r"\resizebox{\textwidth}{!}{%",
                            r"\begin{tabular}{l"
                            + "r" * len(chosen)
                            + r"}\hline Population & "
                            + " & ".join(escape(k) for k in chosen)
                            + r" \\ \hline",
                        ]
                    )
                    for row in rows:
                        label = " / ".join(cell(row.get(k)) for k in id_fields) or "all"
                        lines.append(
                            escape(label)
                            + " & "
                            + " & ".join(escape(cell(row.get(k))) for k in chosen)
                            + r" \\"
                        )
                    lines.append(r"\hline\end{tabular}}\end{table*}")
        lines.append(r"\clearpage")
        overview.append(
            dict(module=a, status=m["status"], table_count=len(m["tables"]))
        )
    ending = [
        (
            "Cross-Module Consistency Checks",
            "Validation status: "
            + validation["status"]
            + ". "
            + "; ".join(k + "=" + v["status"] for k, v in validation["checks"].items()),
        ),
        (
            "Discussion",
            "Conditional estimates describe successfully measured rewrites; all-attempt estimates include failures. Their difference reflects historical eligibility as well as measured performance. DP-v1 and CG-v1 are complete prompting packages; their differences do not isolate a numerical-guidance causal effect.",
        ),
        (
            "Limitations",
            "Length preservation does not prove semantic preservation, event preservation, or screenplay quality. Reused scenes, features from a common interval and repeated generations are not independent screenplay observations. E06 provides no human validation, independent extractor, semantic judgment, dramaturgical validation or new rewrite model. Missing optional texts limit A06. Historical execution provenance remains bounded by archived evidence. Threshold sensitivities are descriptive and no perceptual threshold is asserted.",
        ),
        (
            "Conclusion",
            "The computed artifacts quantify the seven declared diagnostics, subject to the explicit validation checks and missingness ledger. Independent scientific review remains required.",
        ),
        (
            "Reproducibility and Artifact References",
            "Use the locked E06 implementation and exact input binding. E06_MANIFEST.json identifies the dataset kind. E06_PROVENANCE.json records input hashes. E06_VALIDATION.json records invariants. RESULT_SEAL.json verifies the computed result files. Every module CSV/JSON and the Markdown companion tables retain full precision; LaTeX table cells are formatted to six decimal places. E06_REVIEWER_COVERAGE.md documents partial reviewer coverage.",
        ),
    ]
    for title, text in ending:
        lines.extend([r"\section{" + escape(title) + "}", escape(text)])
    lines.append(r"\end{document}")
    tex = output / ("SYNTHETIC_REPORT.tex" if fixture else "E06_REPORT.tex")
    tex.write_text("\n".join(lines) + "\n")
    (output / "E06_REVIEWER_COVERAGE.md").write_text(COVERAGE)
    (output / "REPORT_INDEX.md").write_text(
        "# "
        + prefix
        + TITLE
        + "\n\n"
        + markdown_table(overview, ["module", "status", "table_count"])
    )
    pdf = "NOT_REQUESTED"
    if compile_pdf:
        if not shutil.which("pdflatex") or not shutil.which("kpsewhich"):
            pdf = "UNAVAILABLE: local IEEEtran toolchain missing; no installation attempted"
        else:
            probe = subprocess.run(
                ["kpsewhich", "IEEEtran.cls"], capture_output=True, text=True
            )
            if not probe.stdout.strip():
                pdf = "UNAVAILABLE: IEEEtran.cls absent"
            else:
                try:
                    process = subprocess.run(
                        [
                            "pdflatex",
                            "-no-shell-escape",
                            "-interaction=nonstopmode",
                            "-halt-on-error",
                            tex.name,
                        ],
                        cwd=output,
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    (output / "LATEX_COMPILATION.log").write_text(
                        process.stdout + process.stderr
                    )
                    pdf = (
                        "COMPLETE"
                        if process.returncode == 0 and tex.with_suffix(".pdf").is_file()
                        else "COMPILATION_FAILED"
                    )
                except (subprocess.TimeoutExpired, OSError) as exc:
                    pdf = "UNAVAILABLE: " + type(exc).__name__
    write(
        output / "REPORT_STATUS.json",
        dict(
            dataset_kind=manifest["dataset_kind"],
            pdf=pdf,
            source=str(tex),
            computed_result_seal=sha(run / "00_manifest/RESULT_SEAL.json"),
        ),
    )
    return dict(output=str(output), pdf=pdf)


RESULT_JSON = {
    "A01": "A01_RESULTS.json",
    "A02": "A02_BASELINE_RESULTS.json",
    "A03": "A03_RESULTS.json",
    "A04": "A04_RESULTS.json",
    "A05": "A05_FEATURE_LEVEL_RESULTS.json",
    "A06": "A06_RESULTS.json",
    "A07": "A07_RESULTS.json",
}
