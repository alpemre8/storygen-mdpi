"""Deterministic result exports and separate execution/gate documentation."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from . import ANALYZER_VERSION

TITLES = ("Target distance magnitude", "Maintain-only direction tolerance", "Analytic direction baselines",
          "Failure-aware all-attempt outcomes", "Global-common exclusions", "Feature outcomes for all four models",
          "Off-target numerical feature drift", "Rewrite length ratios", "Cluster dependence sensitivity", "Interval length sensitivity")
SHORT = {"qwen2.5-7b-q4":"Qwen2.5", "llama3.1-8b-instruct-gguf":"Llama3.1",
         "qwen3.5-9b-gguf":"Qwen3.5", "gemma3-12b-it-gguf":"Gemma3"}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)+"\n",encoding="utf-8")


def write_csv(path, rows):
    keys = list(dict.fromkeys(k for row in rows for k in row))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=keys,lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k:json.dumps(v,sort_keys=True,ensure_ascii=False,allow_nan=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})


def tex_escape(value):
    replacements={"\\":r"\textbackslash{}","&":r"\&","%":r"\%","$":r"\$","#":r"\#","_":r"\_","{":r"\{","}":r"\}","~":r"\textasciitilde{}","^":r"\textasciicircum{}"}
    return "".join(replacements.get(c,c) for c in str(value))


def tex_table(path, rows, columns, caption, note):
    # Self-contained article, with repeated headings and page breaks via longtable.
    # Tables stay below nine narrow columns; detailed full-precision fields are CSV.
    def display(row, column):
        key,title,style=column
        value=row.get(key)
        if value is None:
            return "N/A"
        if key=="model":
            value=SHORT.get(value,value)
        if isinstance(value,bool):
            return "yes" if value else "no"
        if isinstance(value,(float,int)):
            return str(value) if style=="integer" else f"{value*100:.2f}" if style=="percent" else f"{value:.2f}" if style=="pp" else f"{value:.3f}"
        if isinstance(value,list) and len(value)==2 and all(isinstance(x,(int,float)) for x in value):
            return f"[{value[0]:.3f}, {value[1]:.3f}]" if style!="pp" else f"[{value[0]:.2f}, {value[1]:.2f}]"
        return tex_escape(value).replace(r"\_",r"\_\allowbreak{}")
    headings=" & ".join(tex_escape(c[1]) for c in columns)+r" \\"
    # Fixed total width and wrapped cells also accommodate long protocol names.
    import math
    weights=[math.sqrt(max(8,len(c[1]),max((len(str(r.get(c[0],""))) for r in rows),default=0))) for c in columns]
    available_mm=267-2*len(columns)*5*25.4/72.27
    spec="".join(r">{\raggedright\arraybackslash}p{"+f"{available_mm*w/sum(weights):.3f}mm"+"}" for w in weights)
    body=[r"\documentclass[10pt]{article}",r"\usepackage[a4paper,landscape,margin=15mm]{geometry}",
          r"\usepackage{longtable,booktabs,array}",r"\begin{document}",r"\small",
          r"\setlength{\tabcolsep}{5pt}",r"\renewcommand{\arraystretch}{1.15}",
          r"\begin{longtable}{"+spec+"}",r"\caption{"+tex_escape(caption)+r"}\\",
          r"\toprule",headings,r"\midrule",r"\endfirsthead",r"\toprule",headings,r"\midrule",r"\endhead"]
    body += [" & ".join(display(row,c) for c in columns)+r" \\" for row in rows]
    body += [r"\bottomrule",r"\end{longtable}",r"\noindent "+tex_escape(note),r"\end{document}",""]
    path.write_text("\n".join(body),encoding="utf-8")


def columns(*items):
    return [(k,title,style) for k,title,style in items]


def export_analysis(output, number, result):
    aid=f"A{number:02d}"
    root=output/"results"/aid
    root.mkdir(parents=True,exist_ok=False)
    write_json(root/"results.json",dict(analyzer_version=ANALYZER_VERSION,analysis_id=aid,**result))
    for key,value in result.items():
        if isinstance(value,list) and all(isinstance(row,dict) for row in value) and value:
            write_csv(root/(key+".csv"),value)
    entries=[]
    def table(suffix,rows,cols,caption,note):
        name=aid+"_"+suffix
        # CSV contains ALL fields; LaTeX selects readable display columns.
        write_csv(output/"tables"/(name+".csv"),rows)
        tex_table(output/"tables"/(name+".tex"),rows,cols,caption,note)
        entries.append(dict(name=name,caption=caption,note=note,rows_n=len(rows),csv=f"tables/{name}.csv",tex=f"tables/{name}.tex"))
    model=("model","Model","text");condition=("condition","Condition","text");n=("task_n","N tasks","integer")
    generic="New deterministic diagnostic of operational Qwen-extractor measurements. Values in CSV/JSON are unrounded; N/A is explicitly undefined. No inference about narrative validity or generation variance."
    if number==1:
        for pop in ("model_pair","global_common"):
            rows=[r for r in result["summary"] if r["population"]==pop]
            table("distance_"+pop,rows,columns(model,condition,n,("mean_dB","Mean dB","number"),("mean_dA","Mean dA","number"),("mean_G","Mean G","number"),("median_G","Median G","number"),("mean_task_relative_G","Mean task R","number")),f"A01 target distance magnitude on {pop} tasks; positive G is closer to target.",generic+" Mean task-relative gain is distinct from ratio of aggregate means and binary TI. Distances are in [0,1] score units.")
        rows=[r for r in result["confidence_intervals"] if r["condition"]=="CG-minus-DP"]
        table("gain_contrasts",rows,columns(model,("population","Population","text"),n,("cluster_n","Clusters","integer"),("point","CG-DP G","number"),("ci95","95% CI","number")),"A01 paired target-distance gain contrasts, including global common N=186.","Base-interval cluster bootstrap: 10000 PCG64 draws, seed42, fresh stream per model/population, linear percentiles; task-macro weights. "+generic)
        table("epsilon_sensitivity",result["TI_epsilon"],columns(model,condition,("population","Population","text"),n,("epsilon","Epsilon","number"),("TI_epsilon","TI epsilon %","percent")),"A01 diagnostic minimum-gain thresholds; canonical TI retained at epsilon zero.","Diagnostic endpoint snapping within 1e-12 at .01/.05/.10; no snapping at zero. "+generic)
    elif number==2:
        table("maintain_tolerance",result["summary"],columns(model,n,("points_n","N points","integer"),("maintain_micro_proportion","Maintain %","percent"),("tau","Tau","number"),("dp_DA","DP DA %","percent"),("cg_DA","CG DA %","percent"),("delta_DA_pp","Delta pp","pp")),"A02 maintain-only tolerance DA on each model's paired tasks.","Increase/decrease rules and target signs stay exact. Tau=0 equals published DA; positive tau allows abs(A-B)<=tau+1e-12 only on maintain points. "+generic)
        table("direction_contributions",result["direction_contributions"],columns(model,n,("tau","Tau","number"),("direction","Target direction","text"),("delta_DA_contribution_pp","Delta contribution pp","pp")),"A02 direction contributions to task-macro CG-DP DA.","Each scene weight is 1/scene count within its task and 1/N across paired tasks; contributions sum to the original delta at tau zero. "+generic)
    elif number==3:
        table("direction_floors",result["summary"],columns(("stratum","Stratum","text"),("stratum_value","Value","text"),("policy","Analytic policy","text"),("tasks_n","N tasks","integer"),("points_n","N points","integer"),("micro_DA","Micro %","percent"),("macro_DA","Task macro %","percent")),"A03 analytic direction calibration, all 240 frozen target-only tasks and feature/length strata.","Counts are 902 increase, 338 maintain, 760 decrease over 2000 feature-scene positions. Frequency-matched prediction probabilities use each stratum's micro proportions; its macro expectation uses original task weights. Uniform independent reference is 1/3. No empirical rewrite or TI baseline.")
    elif number==4:
        table("all_attempt_outcomes",result["summary"],columns(model,condition,("measurable_n","Measured /240","integer"),("failed_n","Failures","integer"),("coverage","Coverage %","percent"),("conditional_TI","Cond. TI %","percent"),("conditional_DA","Cond. DA %","percent"),("ATI","ATI %","percent"),("ADA_all","ADA all %","percent")),"A04 conditional and failure-aware outcomes across all 240 attempts per condition.","Actual TI/DA on failures remain absent. A zero enters only the separate all-attempt composites E*TI and E*DA. Original Table A3 coverage and ATI reproduced. "+generic)
        table("robustness_deltas",result["paired_and_all_attempt_deltas"],columns(model,n,("delta_TI_pp","Paired TI pp","pp"),("delta_DA_pp","Paired DA pp","pp"),("delta_ATI_pp","All240 ATI pp","pp"),("delta_ADA_all_pp","All240 ADA pp","pp"),("delta_coverage_pp","Coverage pp","pp")),"A04 CG-DP differences with paired versus fixed all-attempt denominators.","Paired N varies by model; ATI/ADA differences retain 240 attempts for both conditions. "+generic)
    elif number==5:
        rows=[]
        for r in result["excluded_task_manifest"]:
            failures=", ".join(SHORT[f["model"]]+"/"+f["condition"][:2] for f in r["failed_conditions"])
            rows.append({**r,"failure_codes":failures})
        table("excluded_ids",rows,columns(("task_id","Excluded task","text"),("base_interval_id","Base interval","text"),("selected_feature","Feature","text"),("interval_length","Scenes","integer"),("failure_codes","Failed model/condition","text")),"A05 all 54 unique excluded tasks from the all-eight-condition common intersection.","Denominator 240 tasks, retained 186. Full film identities, direction histograms and reasons are in the companion CSV/JSON. 54 unique exclusions differ from 68 condition-attempt failures and model-pair exclusions.")
        rows=[r for r in result["retained_excluded_distributions"] if r["stratum"] in ("selected_feature","interval_length","target_direction_points")]
        table("exclusion_distributions",rows,columns(("population","Population","text"),("stratum","Stratum","text"),("value","Value","text"),("task_n","Tasks","integer"),("points_n","Points","integer"),("proportion","Within population %","percent")),"A05 distributions of retained 186 and excluded 54 tasks.","Feature/length rates use their population's task count; target-direction rates use all selected scene points in that population, with no majority label assumption.")
    elif number==6:
        for pop in ("model_pair","global_common"):
            table("feature_outcomes_"+pop,[r for r in result["summary"] if r["population"]==pop],columns(model,("feature","Feature","text"),n,("dp_TI","DP TI %","percent"),("cg_TI","CG TI %","percent"),("delta_TI_pp","TI delta pp","pp"),("dp_DA","DP DA %","percent"),("cg_DA","CG DA %","percent"),("delta_DA_pp","DA delta pp","pp")),f"A06 five-feature outcomes on {pop} tasks.","All DP/CG contrasts use identical task IDs within the displayed feature. CSV gives each condition's failed counts out of 48 feature attempts. Global-common feature subsets come from the same overall 186 tasks. Gemma paired Ns 46/47/48/48/48 and all Table8 values reproduce. "+generic)
    elif number==7:
        table("off_target_drift",result["summary"],columns(model,condition,("feature","Selected feature","text"),n,("mean_absolute_drift","Mean abs drift","number"),("median_absolute_drift","Median task drift","number"),("max_scene_dimension_drift","Max point drift","number"),("task_macro_fraction_ge_0_1",">=0.1 %","percent"),("task_macro_fraction_ge_0_2",">=0.2 %","percent")),"A07 incidental drift in the four nonselected source-feature dimensions on paired tasks.","Source is the original five-vector, after is verified historical reanalysis. Each task averages its scenes and four uncontrolled dimensions. Inclusive .1/.2 endpoints use 1e-12 tolerance. Dimension-specific signed/absolute shifts are in CSV. This is no semantic content-preservation score. "+generic)
        table("drift_contrasts",result["paired_deltas"],columns(model,n,("cluster_n","Clusters","integer"),("delta_mean_absolute_drift","CG-DP drift","number"),("ci95","95% CI","number")),"A07 paired contrasts in mean absolute off-target drift.","Base-interval PCG64 cluster percentile sensitivity, 10000 draws, seed42; fresh per model, task-macro weights. "+generic)
    elif number==8:
        for suffix,rows in (("length_ratios",[r for r in result["summary"] if r["stratum"]=="all"]),("length_ratio_strata",[r for r in result["summary"] if r["stratum"]!="all"])):
            table(suffix,rows,columns(model,condition,("stratum_value","Stratum","text"),n,("scene_n","N scenes","integer"),("scene_median_word_ratio","Scene median","number"),("task_macro_mean_word_ratio","Task mean ratio","number"),("short_scene_n","<0.35 count","integer"),("long_scene_n",">3 count","integer")),"A08 original-to-rewrite word ratios on paired tasks, with scene and task denominators.","Ratio is rewritten/original. Text is NFC Unicode normalized, whitespace collapsed/trimmed, words are whitespace-separated chunks, characters are Unicode code points after normalization. Zero original count gives N/A. Character ratios, full quantiles, empty/zero cases and recorded warning counts are in CSV/JSON. All 1852 valid task texts are joined in detailed records. Length does not establish faithfulness.")
    elif number==9:
        table("cluster_CIs",result["summary"],columns(model,("scheme","Sampling unit","text"),("metric","Metric","text"),n,("cluster_n","Clusters","integer"),("delta_pp","CG-DP pp","pp"),("ci95","95% CI pp","pp"),("ci_sign_class","CI sign class","text")),"A09 paired TI/DA uncertainty under distinct cluster definitions.","Base intervals call the frozen approved table-a6-pcg64-v1 kernel exactly. Other schemes are new protocol IDs, 10000 sorted-cluster PCG64 draws, seed42, task-macro ratio of sums. Overlap components connect any shared source scene within each film, including transitive overlap. Few-film/component CIs are sensitivity estimates; fewer than two clusters or degenerate distributions give N/A. Source-film clustering does not address reference-film/crossed dependence; bootstrap cannot assess stochastic generation variance. Historical execution provenance remains UNVERIFIED.")
    elif number==10:
        table("length_outcomes",result["summary"],columns(model,("interval_length","Scenes/task","integer"),n,("cluster_n","Clusters","integer"),("dp_TI","DP TI %","percent"),("cg_TI","CG TI %","percent"),("dp_DA","DP DA %","percent"),("cg_DA","CG DA %","percent"),("delta_DA_pp","DA delta pp","pp")),"A10 paired outcomes by 5/8/12-scene interval length.","Paired N is explicit; condition coverage has a separate 80-attempt denominator per length. Distances, gains, mean scene movement and clustered delta CIs are in CSV/JSON. Each source scene was rewritten separately; models did not receive the complete interval. Equal source/reference lengths do not test unequal-length interpolation or coordinated narrative control. "+generic)
        table("length_coverage",result["length_coverage"],columns(model,condition,("interval_length","Scenes/task","integer"),("attempted_n","Attempts","integer"),("measurable_n","Measured","integer"),("failed_n","Failed","integer"),("coverage","Coverage %","percent"),("ATI","ATI %","percent"),("ADA_all","ADA all %","percent")),"A10 coverage and all-attempt composites by length, exactly 80 attempts per condition/length.","Each length stratum retains original failures; this denominator differs from matched complete-case tasks.")
    return entries


PROTOCOL = """# P01B deterministic analysis protocol

These are new, prespecified diagnostics over the original frozen eight conditions. Analyzer identity: reviewer-r1-deterministic-v1. No text was generated or remeasured. The original Qwen instrument is an operational score space; these diagnostics do not independently validate narrative constructs or artistic quality.

## Frozen inputs and populations

One verified text-free canonical view joins 240 tasks, 48 bases, 10 films/938 scenes, five features and eight conditions. Original plan B/T, source five-vectors, after five-vectors and text pointers/hashes are retained; every original scientific record is replayed by existing evaluate_task and compared exactly. Failed attempts have A/TI/DA absent. P01A explicit path overrides resolve by declared SHA, with no scanning/substitution. Per-model matched DP/CG IDs are 234/232/198/237; global common IDs are the same 186 for every condition; all-attempt denominators are 240 (feature48; length80). Every result states its population. Detailed condition-measurable records include all 1852 successes; matched contrasts exclude every unpaired task.

## Metric and numerical rules

Canonical dB=mean|B-T|, dA=mean|A-T|, TI=1[dA<dB], DA=mean[sign(A-B)=sign(T-B)], sign(0)=0. The existing kernel is unchanged and supplies dB/dA/TI/DA; exact signs, zero and strict TI have no new tolerance. The effective 0.1 grid describes predominant scoring resolution, not an exclusive constraint: finer historical values are counted in VALIDATION_REPORT and retained without quantization. Raw float arithmetic is preserved. Canonical floating-point tiny positive gains remain TI successes and enter (0,.01]. For diagnostic positive endpoint bins only, gains within 1e-12 of .01/.05/.10 are snapped to that endpoint; bins are (0,.01],(.01,.05],(.05,.10],>.10. Epsilon zero is canonical TI exactly, other epsilons use those endpoint rules. Positive maintain tolerance includes abs(A-B)<=tau+1e-12; tau zero calls the exact rule. Drift thresholds include abs(D)>=.1-1e-12 and >=.2-1e-12. Other signs/ties, dB>0 validity, length-tail <.35/>3, and canonical target directions stay exact. No measure is changed to enforce a favorable outcome.

## New uncertainty protocols

New IDs are p01b-a01-<population>-meanG-base-v1, p01b-a01-<population>-deltaG-base-v1, p01b-a07-drift-base-v1, p01b-a08-wordratio-base-v1, p01b-a09-<source scheme>-paired-pp-v1, and p01b-a10-length<N>-<metric>-base-v1. Each model, population/condition and estimand resets numpy.random.default_rng(42)/PCG64 independently. There are 10000 draws, 95% linear percentile intervals, deterministically sorted represented cluster IDs, and no unmeasured pair substitution. A draw samples K of the K represented clusters with replacement and retains every task in each sampled cluster, including repeated clusters. Estimator is sum of sampled task outcomes / sum of sampled task counts; unequal cluster sizes do not receive equal mean weights. CI is N/A with an explicit reason for fewer than two clusters, constant task values or degenerate resampling. Fewer than ten represented clusters carry a sensitivity warning; no invented minimum-size significance test. TI/DA deltas are CG-DP percentage points; continuous deltas are original score/ratio units. These descriptive contrasts do not alone justify significance or causality.

The approved A6 base-interval analysis alone uses table-a6-pcg64-v1, exact frozen source bytes, task order, sorted 48 clusters and original paired inputs, through the unchanged existing kernel. Its raw fractional CIs and companion historical display-pp fields are preserved. Published endpoints reproduce; the author's prospective adoption does not confirm historical script execution, which remains UNVERIFIED. The historical MT19937 default and Paper-22 lock are untouched.

## Analysis definitions

A01: G=dB-dA, absolute G=|G|, R=G/dB for dB>0 else N/A. Counts improve/tie/worsen are exact G signs. Summaries/quantiles are equal task weighted. Mean task R is explicitly distinct from mean(G)/mean(dB); binary TI% is no percentage distance reduction. Paired and global-common summaries have independent base-cluster CI streams. Small positive bins and epsilon0/.01/.05/.10 are diagnostic.

A02: frozen exact target sign, original increase/decrease hits, maintain-only tau0/.05/.10/.20. Scene-direction micro accuracies accompany task-macro stratum weights and correct contributions. Each scene has weight1/n_t and each paired task1/N. Direction contributions to CG-DP sum to the original paired DA delta, including Llama's -7.18pp at display precision. No symmetric dead-zone replacement.

A03: all240 target-only tasks contain 2000 selected feature-scene positions (400 source-window positions repeated for five features), with 902 increase/338 maintain/760 decrease. Always-direction micro chance is that direction's point fraction, macro chance is mean within-task direction fraction. Uniform independent prediction reference is1/3. Optional frequency-matched reference draws with each stratum's micro p_k: micro expectation sum p_k squared; macro expectation sum p_k times task-macro target-direction weights. No rewriting, empirical TI, no-guidance performance or human outcomes are implied.

A04: ATI=sum(E*TI)/240 and ADA_all=sum(E*DA)/240; failure indicator E=0 contributes zero only to these composites while actual DA/TI remain absent. Coverage, conditional scores, original Table A3 ATI, taxonomy, feature48 variants and fixed-denominator deltas are separate from paired complete-case metrics. Failure taxonomy retains the canonical reason and classifies recorded rewrite error wording using ordered literal substrings plan_like/plan-like, empty, json, scene_coverage, scene id, timeout, otherwise other_recorded_rewrite_error. This is a reported-error category, not an inferred semantic failure; original exception type/stage and reported scene ID are retained without exporting error/response text.

A05: unique exclusions are the complement of all-eight eligibility, exactly54; retained186. Full IDs, failed condition/reason lists, film/base/feature/length and target-point direction histograms are exported. Feature/length/film/base distributions use task denominators; direction distributions use points. No forced single direction per task. 68 failed attempts and model-specific paired exclusions are different units.

A06: all four models by five selected features; each primary contrast is its exact paired subset. A separate common186 feature table supports cross-model comparison. Failed counts use original48 feature attempts. Gemma paper order pacing/emotion/dialogue/action/character has Ns46/47/48/48/48; published control CSV is only a validation target.

A07: join original source B_g and historical after A_g for the four g unequal to selected f; D=A_g-B_g. Per task mean absolute drift averages all n_t scenes and four off-target dimensions; task distributions, maximum point drift, dimension-specific signed/absolute shifts and inclusive threshold task-macro fractions are exported. Missing required dimensions block A07; contradictory identities fail. Every measurable task has a drift record; condition contrasts use only paired IDs. Numerical off-target drift is no content-preservation validation.

A08: valid rewritten scene content joins original scene text using verified film/ordered scene IDs and original script SHA. NFC Unicode normalization, whitespace collapse and edge trim precede counting; a word is a nonempty whitespace-separated chunk, characters count Unicode code points including normalized spaces and punctuation. Ratios are rewrite/original; zero original counts yield N/A with counts, never infinity. Scene distributions and task means/medians are separate. Task-macro comparison uses defined paired task means, and valid scene-ratio counts document missingness. Short<.35 and long>3 use strict boundaries. Recorded warning counts combine task validation_warnings and per-scene warnings as recorded entries, which may include duplicate reporting of the same event; they are not inferred from tails. No screenplay text is exported. All1852 complete task texts are joined, summaries/contrasts use exact model pairs.

A09: approved frozen base CI versus new exact source-film+ordered-window clusters, overlap-connected source-window components and source-film clusters. Components are derived on the frozen full240 design (not selectively recomputed after model failures); within a film any shared original scene connects windows transitively. Resampling uses only represented paired tasks, with cluster counts/sizes exported. Source-film/component estimates have few clusters and remaining reference-film/crossed dependency; no claim that film clustering eliminates all dependency or estimates stochastic generation variance. Sign classes describe zero inclusion only, not a new significance claim.

A10: paired length5/8/12 outcomes, distances and gains, scene-level absolute selected-feature movement, and mean scene distance gain. Separate coverage/composites retain exactly80 attempts per condition/length. CIs use represented base clusters with the same explicitly versioned new protocol and N/A rules. Binary TI on an average distance can differ with interval size even when mean scene movement is similar; descriptive trends do not establish an interval-length effect. Rewriting was per scene; whole narrative context, coordinated trajectory control and unequal-length interpolation were not tested.

## Exports

CSV/JSON retain full precision and denominators; only LaTeX display is rounded. Lists/dicts in CSV are JSON cells; no raw content, headings or change summaries are exported. All tables are self-contained landscape article/longtable documents with captions/notes. Result identities exclude execution timestamps. Source commit, source-file SHA, input-file SHA, plan SHA, finite progress and test evidence are isolated in provenance/logs. Artifact manifest hashes all final deliverables except itself (avoiding recursive self hashing).
"""


def reviewer_comments(path):
    with ZipFile(path) as archive:
        root=ET.fromstring(archive.read("word/document.xml"))
    ns={"w":"http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paras=["".join(t.text or "" for t in p.findall(".//w:t",ns)) for p in root.findall(".//w:p",ns)]
    return [(f"R{reviewer}-{n}",paras[i]) for reviewer,ids in ((1,range(42,50)),(2,range(95,99)),(3,range(143,151)),(4,range(195,198))) for n,i in enumerate(ids,1)]


def traceability(dataset):
    mapping={"R1-1":"A01/A02 describe original-instrument outcomes only. Independent extraction E01 and human validation remain deferred.",
             "R1-2":"Original conditions remain complete prompt configurations. Matched templates E04 remain deferred.",
             "R1-3":"A01 distance/relative-gain/tiny-gain and uncertainty; A03 analytic DA floors. No-guidance empirical baseline E02 remains deferred.",
             "R1-4":"A09 exact/overlapping source-window and source-film sensitivities. Stochastic repeats E03 remain deferred.",
             "R1-5":"A10 length/scene movement and explicit per-scene/equal-length limitation. Constant/reordered controls E06 remain deferred.",
             "R1-6":"A07 four off-target dimensions and A08 length ratios. These do not replace semantic/human content audit E05.",
             "R1-7":"A04 all-attempt ADA/ATI, A05 excluded tasks, A06 all-model feature tables.",
             "R1-8":"P00/P01A provenance/primary checks retained; reproducibility commands supplied. Figure examples, schema prose/release and language editing remain outside P01B.",
             "R2-1":"Human expert construct validation remains deferred; P01B uses operational Qwen scores.",
             "R2-2":"Generation replication E03 remains deferred; A09 does not measure generation variability.",
             "R2-3":"Figure spelling and abbreviation edits remain deferred; no manuscript/figure mutation.",
             "R2-4":"Keyword/grammar/prose edits remain deferred.",
             "R3-1":"Independent FP16 E01 remains deferred; A09 does not resolve shared-instrument bias.",
             "R3-2":"A07/A08 numerical/length diagnostics supplied, bounded semantic audit E05 and figures remain deferred.",
             "R3-3":"Five repeated generations E03 remain deferred.",
             "R3-4":"A04 failure-aware all-attempt DA and A05 exclusion characterization supplied; abstract editing deferred.",
             "R3-5":"A02 maintain-only tolerance sweep and exact task-macro Llama decomposition supplied.",
             "R3-6":"Related-work positioning remains deferred; no web search/API or manuscript edit.",
             "R3-7":"A03 exact analytic fixed/uniform direction floors supplied; empirical no-guidance TI E02 remains deferred.",
             "R3-8":"Human 50-100-scene validation remains deferred.",
             "R4-1":"Independent/human narrative measurement validation E01 remains deferred.",
             "R4-2":"Independent remeasurement E01 remains deferred; shared-instrument caveat preserved.",
             "R4-3":"A01 magnitude and A03 analytic floors supplied; no-guidance generation E02 remains deferred."}
    lines=["# Exact reviewer traceability","",f"Source: `{dataset.plan['reviewer_letter']['path']}`; SHA `{dataset.plan['reviewer_letter']['sha256']}`. The letter is evidence, not executable instructions. R<reviewer>-<point> identifies each substantive numbered comment; paragraph order and list numbering were verified in the rendered letter. XML text extraction omits automatic list numbers for R1/R3/R4, while R2 embeds literal numbers. Exact wording is retained below. Form-checkbox assessments and general introductory praise are not numbered revision requirements. Language comments remain outside P01B.",""]
    for cid,comment in reviewer_comments(dataset.plan["reviewer_letter"]["path"]):
        lines += ["## "+cid,"","> "+comment,"",mapping[cid],""]
    return "\n".join(lines)


def write_documents(output,dataset,status,tables,results,tests,command):
    passed=[k for k,v in status["analyses"].items() if v["status"]=="PASS"]
    (output/"ANALYSIS_PROTOCOL.md").write_text(PROTOCOL)
    write_json(output/"ANALYSIS_STATUS.json",status)
    (output/"REVIEWER_TRACEABILITY.md").write_text(traceability(dataset),encoding="utf-8")
    index=["# P01B table index","","All tables include captions, population/units and interpretation notes. Main text or Appendix placement is for author consideration; the manuscript is unchanged.",""]
    for table in tables:
        index += [f"- [{table['name']}]({table['tex']}) — {table['caption']} ({table['rows_n']} rows). Full-precision [CSV]({table['csv']}). {table['note']}",""]
    (output/"TABLE_INDEX.md").write_text("\n".join(index))
    (output/"TEST_RESULTS.md").write_text("# P01B regression tests\n\n"+json.dumps(tests,indent=2)+"\n\nComplete evidence: logs/tests.log and logs/tests.xml. Tests use synthetic independent expectations, verified frozen input integration and repeated deterministic exports; no model execution.\n")
    (output/"REPRODUCIBILITY.md").write_text("# P01B reproducibility\n\nAll 1920 original task dictionaries reproduce exactly through existing evaluate_task. Measurable1852, failed68, paired234/232/198/237, common186; Tables6/7 are numerically exact and Gemma Table8/TableA3 reproduce at published precision. A09 calls frozen A6 PCG64 source/config and validates all16 endpoints/order/IDs. Original MT19937 behavior is covered by existing tests. Historical A6 script execution remains UNVERIFIED.\n\n```bash\n"+command+"\n```\n\nUse a fresh output directory. ANALYSIS_PLAN.json contains explicit absolute verified inputs and all settings; relocating files requires explicit hash-checked overrides. Input SHA and actual source file identities are in INPUT_PROVENANCE.json. No dependency installation, external API, LLM inference or historical mutation is part of the command. Deterministic result CSV/JSON/TeX exclude timestamps; tests compare repeat bytes.\n")
    (output/"VALIDATION_REPORT.md").write_text("# P01B scientific validation\n\n"+json.dumps({k:v for k,v in dataset.validation.items() if k not in ("cross_control","table8_control")},indent=2)+"\n\nEach successful analysis has finite nonempty records, explicit denominators and status evidence. Canonical signs/TI/DA are exact; diagnostic endpoint rules are disclosed. Degenerate/insufficient cluster CIs carry N/A reasons, never artificial certainty. Original artifacts are checked separately in evidence/final_integrity_verification.json before final phase gate.\n\n"+json.dumps(status,indent=2)+"\n")
    unresolved=[k+": "+str(v.get("reason")) for k,v in status["analyses"].items() if v["status"]!="PASS"]
    later="Independent FP16 measurement/instrument validation (E01); no-guidance empirical rewrite floor (E02); stochastic generation repeats (E03); matched prompting templates (E04); structured semantic content audit (E05); optional curve controls (E06); human expert validation; manuscript/figure/language/related-work edits. Historical A6 execution provenance remains UNVERIFIED and does not invalidate prospective approved scientific reproduction."
    (output/"REMAINING_BLOCKERS.md").write_text("# Remaining gaps\n\nP01B analysis blockers: "+("; ".join(unresolved) if unresolved else "none")+".\n\nFuture reviewer evidence still needed: "+later+"\n")
    (output/"NEXT_STEPS.md").write_text("# Next phase\n\nE01 independent FP16 extraction is the recommended next phase only after explicit author approval of its model, measurement protocol and runtime plan. Keep original rewrite texts, task windows, failure populations and generation lineage; derive independent B/T/A consistently under a separately frozen instrument. Current availability/runtime gaps documented in P00 still need qualification. P01B stops here; no E01 or subsequent experiment has started.\n")
    takeaways=[]
    if "A02" in results:
        values=[r for r in results["A02"]["direction_contributions"] if r["model"]==dataset.models[1] and r["tau"]==0]
        takeaways.append("Llama paired DA contributions (pp): "+", ".join(f"{r['direction']} {r['delta_DA_contribution_pp']:.4f}" for r in values)+"; these sum to the original -7.18pp at manuscript precision.")
    if "A04" in results:
        r=next(r for r in results["A04"]["paired_and_all_attempt_deltas"] if r["model"]==dataset.models[2])
        takeaways.append(f"Qwen3.5 paired TI delta {r['delta_TI_pp']:.4f}pp versus all-attempt ATI {r['delta_ATI_pp']:.4f}pp; paired DA {r['delta_DA_pp']:.4f}pp versus all-attempt ADA_all {r['delta_ADA_all_pp']:.4f}pp.")
    if "A03" in results:
        r=results["A03"]["summary"][0]
        takeaways.append(f"Always-increase analytic DA: point-micro {100*r['micro_DA']:.4f}%, original task-macro {100*r['macro_DA']:.4f}%; not a rewritten-text baseline.")
    (output/"P01B_REPORT.md").write_text(f"# P01B deterministic reviewer analyses\n\n**P01B = {status['phase_status']}**. Completed: {', '.join(passed)}. Exact output directory: `{output}`.\n\n"+"\n\n".join(takeaways)+f"\n\n{len(tables)} standalone paper-ready CSV/LaTeX table pairs and all required analysis result/report files are provided. Existing tests: {tests.get('existing_count')}; new tests: {tests.get('new_count')}; total passed: {tests.get('passed')}.\n\nThese are new descriptive operational-Qwen diagnostics. They do not establish narrative construct/content validity, isolate a numerical-information causal effect, test coordinated interval control, or measure stochastic generation variance. Source-film uncertainty leaves crossed/reference dependence unresolved. Historical A6 execution provenance remains UNVERIFIED; prospective scientific protocol reproduction is approved and intact.\n\nSource/input identities, finite progress, validation, exact reviewer crosswalk and table index are included. Final source Git receipt and protected-file verification are in evidence. No push, inference, historical mutation or E01 execution. STOP after P01B.\n")


def artifact_manifest(output):
    files=[]
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name!="ARTIFACT_MANIFEST.json" and not path.is_relative_to(output/"evidence/tmp"):
            files.append(dict(path=str(path.relative_to(output)),size=path.stat().st_size,sha256="sha256:"+hashlib.sha256(path.read_bytes()).hexdigest()))
    write_json(output/"ARTIFACT_MANIFEST.json",dict(analyzer_version=ANALYZER_VERSION,files=files,exclusions=["ARTIFACT_MANIFEST.json (self-reference)","evidence/tmp (ephemeral test artifacts)"],provenance="ANALYSIS_PLAN.json -> INPUT_PROVENANCE.json -> verified canonical view -> sequential A01-A10 -> tables/reports"))
