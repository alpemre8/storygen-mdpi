"""Post-hoc rendering of stored evidence, without metric recomputation."""

from pathlib import Path
import shutil
import subprocess
import uuid
from .engine.common import StoryGenError, file_sha, read, write_json, durable_write, utc, identifier

TEMPLATE_VERSION = "ieee-evidence/2"


def tex_escape(value):
    table = {
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
    }
    rendered = format(value, ".6g") if isinstance(value, float) else str(value)
    return "".join(table.get(c, c) for c in rendered)


def stored_tables(evidence):
    """Format stored values only; no estimators, metric callbacks or missing-value fill."""
    sections = []

    def table(title, headers, rows):
        if not rows:
            return
        sections.append(r"\subsection{" + tex_escape(title) + "}\n")
        # Short tables split across columns/pages without silently truncating records.
        width = 0.80 / len(headers)
        columns = "@{}" + "".join(f"p{{{width:.3f}\\columnwidth}}" for _ in headers) + "@{}"
        for start in range(0, len(rows), 12):
            cells = [
                r"\begin{table}[htbp]\centering\footnotesize",
                r"\begin{tabular}{" + columns + "}",
                " & ".join(tex_escape(h) for h in headers) + r" \\ \hline",
            ]
            cells.extend(
                " & ".join(tex_escape(v).replace(r"\_", r"\_\allowbreak{}") for v in row) + r" \\"
                for row in rows[start : start + 12]
            )
            cells.extend([r"\end{tabular}", r"\end{table}"])
            sections.append("\n".join(cells))

    checks = evidence.get("scientific_gate", {}).get("checks", [])
    table(
        "Declared scientific gates",
        ["Gate", "Threshold", "Observed", "Status"],
        [[g["name"], g["value"], g["observed"], g["status"]] for g in checks],
    )
    coverage = evidence.get("coverage", [])
    if isinstance(coverage, list):
        table(
            "Source coverage",
            ["Source", "Observed", "Matched", "Population"],
            [
                [
                    i + 1,
                    row.get("observed_units", "UNAVAILABLE"),
                    row.get("matched_units", "UNAVAILABLE"),
                    row.get("source_population", "UNAVAILABLE"),
                ]
                for i, row in enumerate(coverage)
            ],
        )
    metric_rows = []
    for row in evidence.get("rows", []):
        for source_index, value in enumerate(row["source_values"]):
            metrics = value if isinstance(value, dict) else {"value": value}
            for name, stored in metrics.items():
                if isinstance(stored, (int, float, bool)) or stored is None:
                    metric_rows.append(
                        [
                            row["unit_id"],
                            source_index + 1,
                            name,
                            "NULL (stored missing)" if stored is None else stored,
                        ]
                    )
    table(
        "Existing matched metric values", ["Unit", "Source", "Metric", "Stored value"], metric_rows
    )
    source_exposures = [
        (source["run_id"], source.get("development_exposure", []))
        for source in evidence.get("sources", [])
        if source.get("development_exposure")
    ]
    if source_exposures:
        sections.append(r"\subsection{Development exposure in source runs}")
        for source_id, exposed in source_exposures:
            sections.append(tex_escape(source_id) + ": " + tex_escape(str(exposed)) + r"\par")
        sections.append(
            "Development task exposure must accompany interpretation of these source runs. Exact IDs are retained above and in the source evidence."
        )
    strata_rows = []
    for stratum in evidence.get("strata", {}).values():
        for role, condition in stratum["conditions"].items():
            model = condition["model"]
            strata_rows.append(
                [
                    role,
                    model["model_id"],
                    model["quantization"],
                    ", ".join(str(i + 1) for i in stratum["source_indexes"]),
                ]
            )
    table(
        "Separate model and quantization strata",
        ["Role", "Model", "Quantization", "Sources"],
        strata_rows,
    )
    for name in ["excluded_units", "development_exposure"]:
        values = evidence.get(name, [])
        if values:
            sections.append(
                r"\subsection{" + tex_escape(name) + "}\n" + tex_escape(str(values)) + r"\par"
            )
    return "\n".join(sections), {
        "gate_rows": len(checks),
        "coverage_rows": len(coverage),
        "stored_metric_rows": len(metric_rows),
    }


def render(source, output, *, report_id=None, pdf=False):
    source = Path(source)
    evidence = read(source)
    if not isinstance(evidence, dict):
        raise StoryGenError("Report requires an existing structured evidence object")
    target = Path(output) / identifier(report_id or ("REPORT-" + uuid.uuid4().hex))
    target.mkdir(parents=True, exist_ok=False)
    title = evidence.get("experiment_id", evidence.get("analysis_id", "Stored evidence"))
    fields = []
    for key, value in evidence.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            fields.append(tex_escape(key) + ": " + tex_escape(value) + r"\par")
    body = "\n".join(fields)
    tables, rendered_counts = stored_tables(evidence)
    content = (
        r"\documentclass[conference]{IEEEtran}"
        "\n"
        r"\usepackage[T1]{fontenc}"
        "\n"
        r"\begin{document}"
        "\n"
        r"\title{StoryGen: " + tex_escape(title) + "}"
        "\n"
        r"\author{StoryGen evidence renderer}\maketitle"
        "\n"
        r"\section{Stored evidence}"
        "\n" + body + "\n" + tables + "\n"
        r"\section{Provenance and limitations}"
        "\n"
        "Source SHA-256: " + r"\texttt{" + file_sha(source) + "}\\par\n"
        "This report renders existing values. Execution completion does not establish scientific validity. "
        "Tables use six significant digits; the accompanying exact source JSON retains full precision, gates, denominators, exclusions and development exposure.\n"
        r"\end{document}"
        "\n"
    )
    durable_write(target / "report.tex", content.encode())
    durable_write(target / "source_evidence.json", source.read_bytes())
    manifest = {
        "template_version": TEMPLATE_VERSION,
        "template_implementation_sha256": file_sha(__file__),
        "source_sha256": file_sha(source),
        "tex_sha256": file_sha(target / "report.tex"),
        "created_utc": utc(),
        "pdf_status": "NOT_REQUESTED",
        "rendered_counts": rendered_counts,
        "metric_recomputation": False,
        "numeric_display": "six significant digits; exact input JSON is preserved",
    }
    if pdf:
        compiler = shutil.which("pdflatex")
        if not compiler:
            manifest["pdf_status"] = "DEPENDENCY_PENDING"
            manifest["operator_command"] = (
                f"cd {target!s} && pdflatex -no-shell-escape -interaction=nonstopmode -halt-on-error report.tex"
            )
        else:
            result = subprocess.run(
                [
                    compiler,
                    "-no-shell-escape",
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    "report.tex",
                ],
                cwd=target,
                capture_output=True,
            )
            (target / "compile.log").write_bytes(result.stdout + result.stderr)
            manifest["pdf_status"] = "COMPILED" if result.returncode == 0 else "COMPILATION_FAILED"
            if result.returncode == 0:
                manifest["pdf_sha256"] = file_sha(target / "report.pdf")
    write_json(target / "report_manifest.json", manifest)
    return target, manifest
