"""A01–A10 estimands over the single verified Dataset; no inference imports."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import re

from ..supporting import cluster_bootstrap_paired
from . import FEATURES, CONDITIONS, ENDPOINT_ATOL, BlockedAnalysis
from .statistics import (average, distribution, distance, gain_bin, snap_endpoint,
                         directions, tolerance_hits, analytic_floor, all_attempt,
                         off_target, bootstrap, window_key, overlap_components)


def strata(dataset, populations=("model_pair",)):
    for population in populations:
        for model in dataset.models:
            ids = dataset.pairs[model] if population == "model_pair" else dataset.common
            yield population, model, ids


def label(record):
    return {k: record[k] for k in ("model", "condition", "task_id", "base_interval_id", "selected_feature", "interval_length")}


def basic(rows):
    return dict(task_n=len(rows), TI=average([r["TI"] for r in rows]), DA=average([r["DA"] for r in rows]))


def paired_metrics(dataset, model, ids):
    dp, cg = (dataset.rows(model, c, ids) for c in CONDITIONS)
    a, b = basic(dp), basic(cg)
    return dict(task_n=len(ids), dp_TI=a["TI"], cg_TI=b["TI"], dp_DA=a["DA"], cg_DA=b["DA"],
                delta_TI_pp=100 * (b["TI"]-a["TI"]) if ids else None,
                delta_DA_pp=100 * (b["DA"]-a["DA"]) if ids else None)


def a01(dataset):
    summary, raw, differences, sensitivity, cis = [], [], [], [], []
    for model in dataset.models:
        for condition in CONDITIONS:
            raw += [dict(population="condition_measurable", **label(r), **distance(r), gain_bin=gain_bin(distance(r)["G"])) for r in dataset.rows(model,condition) if r["measurable"]]
    for population, model, ids in strata(dataset, ("model_pair", "global_common")):
        gains = {}
        for condition in CONDITIONS:
            rows = dataset.rows(model, condition, ids)
            values = [distance(r) for r in rows]
            for r, v in zip(rows, values):
                raw.append(dict(population=population, **label(r), **v, gain_bin=gain_bin(v["G"])))
            g = [v["G"] for v in values]
            gains[condition] = g
            ci = bootstrap(g, [r["base_interval_id"] for r in rows], f"p01b-a01-{population}-meanG-base-v1")
            cis.append(dict(population=population, model=model, condition=condition, estimand="mean_G", **ci))
            bins = Counter(gain_bin(x) for x in g)
            relative = [v["relative_G"] for v in values]
            mean_db, mean_da = average([v["dB"] for v in values]), average([v["dA"] for v in values])
            summary.append(dict(population=population, model=model, condition=condition, task_n=len(ids),
                                mean_dB=mean_db, mean_dA=mean_da, mean_G=average(g),
                                median_G=distribution(g)["median"], mean_absolute_G=average([abs(x) for x in g]),
                                mean_task_relative_G=average(relative), relative_valid_n=sum(x is not None for x in relative),
                                ratio_of_aggregate_mean_gain=average(g)/mean_db if mean_db else None,
                                improved_n=sum(x > 0 for x in g), tied_n=sum(x == 0 for x in g), worsened_n=sum(x < 0 for x in g),
                                gain_distribution=distribution(g), relative_distribution=distribution(relative),
                                tiny_gain_bins={k:bins[k] for k in ("(0,.01]", "(.01,.05]", "(.05,.10]", ">.10")},
                                mean_G_ci95=ci["ci95"], ci_reason=ci["ci_reason"]))
            for eps in (0, .01, .05, .1):
                sensitivity.append(dict(population=population, model=model, condition=condition, task_n=len(ids), epsilon=eps,
                                        TI_epsilon=average([r["TI"] if eps == 0 else snap_endpoint(v["G"],(.01,.05,.1)) > eps for r,v in zip(rows,values)])))
        delta = [b-a for a,b in zip(gains[CONDITIONS[0]],gains[CONDITIONS[1]])]
        differences += [dict(population=population, model=model, task_id=tid, delta_G=value) for tid,value in zip(ids,delta)]
        ci = bootstrap(delta, [dataset.records[(model, CONDITIONS[0])][tid]["base_interval_id"] for tid in ids], f"p01b-a01-{population}-deltaG-base-v1")
        cis.append(dict(population=population, model=model, condition="CG-minus-DP", estimand="delta_G", **ci))
    return dict(summary=summary, task_metrics=raw, paired_differences=differences, TI_epsilon=sensitivity, confidence_intervals=cis)


def a02(dataset):
    summary, breakdown, contributions, task_values = [], [], [], []
    names = {1:"increase",0:"maintain",-1:"decrease"}
    for _, model, ids in strata(dataset):
        dp, cg = (dataset.rows(model,c,ids) for c in CONDITIONS)
        point_n = sum(r["interval_length"] for r in dp)
        maintain_n = sum(directions(r).count(0) for r in dp)
        for tau in (0, .05, .1, .2):
            condition_values = {}
            for condition, rows in zip(CONDITIONS, (dp,cg)):
                hits = [tolerance_hits(r,tau) for r in rows]
                condition_values[condition] = average([average(h) for h in hits])
                for r,h in zip(rows,hits):
                    if tau == 0 and average(h) != r["DA"]:
                        raise RuntimeError("A02 tau=0 differs from frozen DA")
                    task_values.append(dict(**label(r), tau=tau, DA_maintain_tolerance=average(h)))
                for direction, name in names.items():
                    count = sum(directions(r).count(direction) for r in rows)
                    correct = sum(sum(hit for hit,s in zip(h,directions(r)) if s==direction) for r,h in zip(rows,hits))
                    macro_contribution = sum(sum(hit for hit,s in zip(h,directions(r)) if s==direction)/len(h) for r,h in zip(rows,hits))/len(rows)
                    macro_weight = sum(directions(r).count(direction)/r["interval_length"] for r in rows)/len(rows)
                    breakdown.append(dict(model=model, condition=condition, population="model_pair", tau=tau, direction=name,
                                          task_n=len(ids), points_n=count, direction_micro_DA=correct/count if count else None,
                                          task_macro_correct_contribution=macro_contribution, task_macro_direction_weight=macro_weight,
                                          weighted_direction_accuracy=macro_contribution/macro_weight if macro_weight else None))
            summary.append(dict(model=model, population="model_pair", task_n=len(ids), points_n=point_n, maintain_points_n=maintain_n,
                                maintain_micro_proportion=maintain_n/point_n, tau=tau,
                                dp_DA=condition_values[CONDITIONS[0]], cg_DA=condition_values[CONDITIONS[1]],
                                delta_DA_pp=100*(condition_values[CONDITIONS[1]]-condition_values[CONDITIONS[0]])))
            for direction,name in names.items():
                value = 100*sum(sum((b-a) for a,b,s in zip(tolerance_hits(d,tau),tolerance_hits(c,tau),directions(d)) if s==direction)/d["interval_length"] for d,c in zip(dp,cg))/len(ids)
                contributions.append(dict(model=model,population="model_pair",task_n=len(ids),tau=tau,direction=name,delta_DA_contribution_pp=value))
            if abs(sum(r["delta_DA_contribution_pp"] for r in contributions if r["model"]==model and r["tau"]==tau)-summary[-1]["delta_DA_pp"]) > 1e-12:
                raise RuntimeError("A02 direction contributions do not sum to paired DA difference")
    return dict(summary=summary, direction_breakdown=breakdown, direction_contributions=contributions, task_values=task_values)


def a03(dataset):
    summary = []
    groups = [("all_tasks", "all", dataset.tasks)]
    groups += [("feature",f,[t for t in dataset.tasks if t["selected_feature"]==f]) for f in FEATURES]
    groups += [("length",n,[t for t in dataset.tasks if t["interval_length"]==n]) for n in (5,8,12)]
    for stratum,value,tasks in groups:
        rows = analytic_floor(tasks)
        summary += [dict(stratum=stratum,stratum_value=value,population="all240_target_only",**r) for r in rows]
        p = [r["micro_DA"] for r in rows]
        summary.append(dict(stratum=stratum,stratum_value=value,population="all240_target_only",policy="uniform_independent_random_reference",direction="random",tasks_n=len(tasks),points_n=sum(t["interval_length"] for t in tasks),direction_points=None,micro_DA=1/3,macro_DA=1/3))
        summary.append(dict(stratum=stratum,stratum_value=value,population="all240_target_only",policy="micro_frequency_matched_independent_reference",direction="random",tasks_n=len(tasks),points_n=sum(t["interval_length"] for t in tasks),direction_points=None,micro_DA=sum(x*x for x in p),macro_DA=sum(p[i]*rows[i]["macro_DA"] for i in range(3))))
    totals = {r["direction"]:r["direction_points"] for r in summary if r["stratum"]=="all_tasks" and r["direction"]!="random"}
    if totals != {"increase":902,"maintain":338,"decrease":760}:
        raise RuntimeError("A03 canonical target direction totals contradict frozen 2000 positions")
    return dict(summary=summary, exact_direction_totals=totals)


def a04(dataset):
    summary, features, delta, taxonomy, failures, detail_taxonomy = [], [], [], [], [], []
    for model in dataset.models:
        for condition in CONDITIONS:
            rows = dataset.rows(model,condition)
            summary.append(dict(model=model,condition=condition,population="all_attempt240",**all_attempt(rows)))
            for f in FEATURES:
                subset = [r for r in rows if r["selected_feature"]==f]
                features.append(dict(model=model,condition=condition,feature=f,population="all_attempt_feature48",**all_attempt(subset)))
            counts = Counter(r["failure_reason"] for r in rows if not r["measurable"])
            taxonomy += [dict(model=model,condition=condition,failure_reason=k,failed_attempt_n=v,attempted_n=len(rows)) for k,v in sorted(counts.items())]
            details=Counter((r["failure_detail"] or {}).get("reported_error_category","no_recorded_rewrite_detail") for r in rows if not r["measurable"])
            detail_taxonomy += [dict(model=model,condition=condition,reported_error_category=k,failed_attempt_n=v,attempted_n=len(rows)) for k,v in sorted(details.items())]
            for r in rows:
                if not r["measurable"]:
                    failures.append(dict(**label(r),failure_reason=r["failure_reason"],failure_detail=r["failure_detail"],actual_DA=None,actual_TI=None,composite_contribution=0))
        dp,cg = [r for r in summary if r["model"]==model]
        delta.append(dict(model=model,population="fixed_all_attempt240",attempted_n=240,delta_ATI_pp=100*(cg["ATI"]-dp["ATI"]),delta_ADA_all_pp=100*(cg["ADA_all"]-dp["ADA_all"]),delta_coverage_pp=100*(cg["coverage"]-dp["coverage"]),**paired_metrics(dataset,model,dataset.pairs[model])))
    # Read manuscript Table A3 as a comparison control, never as computed results.
    text = Path(dataset.plan["manuscript_text_control"]["path"]).read_text()
    section = text[text.index("Table A3. All-Attempt Robustness"):]
    controls = re.findall(r"(Gemma-3-12B|Qwen2.5-7B|Llama-3.1-8B|Qwen3.5-9B)\s+(DP-v1|CG-v1)\s+(240)\s+(\d+)\s+([\d.]+)\s+(\d+)\s+([\d.]+)",section)
    if len(controls)!=8:
        raise RuntimeError("Could not securely parse original Table A3 control")
    for display,condition,n,measured,coverage,failed,ati in controls:
        model=next(r["model"] for r in dataset.plan["runs"] if r["display_model"]==display)
        actual=next(r for r in summary if r["model"]==model and r["condition"]==condition)
        if (actual["attempted_n"],actual["measurable_n"],actual["failed_n"],round(100*actual["coverage"],2),round(100*actual["ATI"],2)) != (int(n),int(measured),int(failed),float(coverage),float(ati)):
            raise RuntimeError("Original Table A3 coverage/ATI contradiction")
    return dict(summary=summary, by_feature=features, paired_and_all_attempt_deltas=delta, failure_taxonomy=taxonomy,reported_rewrite_error_taxonomy=detail_taxonomy, failed_attempts=failures, original_A3_matches=True)


def a05(dataset):
    excluded = [t for t in dataset.tasks if t["task_id"] not in dataset.common]
    manifest, distributions, frequencies, pair_exclusions = [], [], [], []
    for t in excluded:
        failed=[dict(model=m,condition=c,reason=dataset.records[(m,c)][t["task_id"]]["failure_reason"]) for m in dataset.models for c in CONDITIONS if not dataset.records[(m,c)][t["task_id"]]["measurable"]]
        counts=Counter(directions(t))
        manifest.append({k:t[k] for k in ("task_id","base_interval_id","selected_feature","interval_length","source_film_id","reference_film_id")}|dict(failed_conditions=failed,increase_points=counts[1],maintain_points=counts[0],decrease_points=counts[-1],points_n=t["interval_length"]))
    for name,tasks in (("retained_global_common",[t for t in dataset.tasks if t["task_id"] in dataset.common]),("excluded_any_eight_failure",excluded)):
        for key in ("selected_feature","interval_length","source_film_id","reference_film_id","base_interval_id"):
            counts=Counter(t[key] for t in tasks)
            universe=sorted({t[key] for t in dataset.tasks})
            distributions += [dict(population=name,stratum=key,value=k,task_n=counts[k],population_tasks_n=len(tasks),proportion=counts[k]/len(tasks)) for k in universe]
        signs=Counter(s for t in tasks for s in directions(t));points=sum(signs.values())
        distributions += [dict(population=name,stratum="target_direction_points",value=label,task_n=None,points_n=signs[k],population_points_n=points,proportion=signs[k]/points) for k,label in ((1,"increase"),(0,"maintain"),(-1,"decrease"))]
    for m in dataset.models:
        pair_exclusions.append(dict(model=m,excluded_task_n=240-len(dataset.pairs[m]),excluded_task_ids=[t["task_id"] for t in dataset.tasks if t["task_id"] not in dataset.pairs[m]],denominator_attempted_tasks=240))
        for c in CONDITIONS:
            frequencies.append(dict(model=m,condition=c,failed_attempts_n=sum(not r["measurable"] for r in dataset.rows(m,c)),attempted_n=240))
    if len(manifest)!=54 or sum(r["failed_attempts_n"] for r in frequencies)!=68:
        raise RuntimeError("Unique common exclusions/failure attempts contradiction")
    return dict(summary=frequencies, excluded_task_manifest=manifest, retained_excluded_distributions=distributions, model_pair_exclusions=pair_exclusions,unique_excluded_n=len(manifest),failed_attempt_n=68)


def a06(dataset):
    summary=[]
    for population,model,ids in strata(dataset,("model_pair","global_common")):
        for feature in FEATURES:
            subset=[tid for tid in ids if dataset.records[(model,CONDITIONS[0])][tid]["selected_feature"]==feature]
            failed={c:sum(not r["measurable"] for r in dataset.rows(model,c) if r["selected_feature"]==feature) for c in CONDITIONS}
            summary.append(dict(population=population,model=model,feature=feature,feature_attempted_n=48,dp_failed_n=failed[CONDITIONS[0]],cg_failed_n=failed[CONDITIONS[1]],**paired_metrics(dataset,model,subset)))
    names={"Pacing":"pacing","Emotion intensity":"emotion","Dialogue density":"dialogue","Action density":"action","Character interaction":"character"}
    gemma=dataset.models[-1]
    for control in dataset.validation["table8_control"]:
        actual=next(r for r in summary if r["model"]==gemma and r["population"]=="model_pair" and r["feature"]==names[control["feature"]])
        if actual["task_n"]!=int(control["pair_n"]):
            raise RuntimeError("Gemma Table8 N contradiction")
        for name in ("dp_TI","cg_TI","dp_DA","cg_DA"):
            if round(100*actual[name],2)!=float(control[name.lower()].removesuffix("%")):
                raise RuntimeError("Gemma Table8 published precision contradiction")
    return dict(summary=summary,original_Gemma_Table8_matches=True)


def a07(dataset):
    tasks,summary,contrasts=[],[],[]
    for model in dataset.models:
        ids=dataset.pairs[model]
        values={}
        for c in CONDITIONS:
            measured=[r for r in dataset.rows(model,c) if r["measurable"]]
            values[c]={r["task_id"]:off_target(r) for r in measured}
            for r in measured:
                tasks.append(dict(**label(r),population="condition_measurable",in_model_pair=r["task_id"] in ids,**values[c][r["task_id"]]))
            rows=dataset.rows(model,c,ids)
            for feature in ["all",*FEATURES]:
                selected=[r for r in rows if feature=="all" or r["selected_feature"]==feature]
                entries=[values[c][r["task_id"]] for r in selected]
                absolute=[e["mean_absolute_drift"] for e in entries]
                d=distribution(absolute)
                summary.append(dict(model=model,condition=c,population="model_pair",feature=feature,task_n=len(entries),off_target_points_n=sum(e["off_target_points_n"] for e in entries),mean_absolute_drift=d["mean"],median_absolute_drift=d["median"],max_scene_dimension_drift=max((e["max_absolute_drift"] for e in entries),default=None),task_drift_distribution=d,task_macro_fraction_ge_0_1=average([e["fraction_ge_0_1"] for e in entries]),task_macro_fraction_ge_0_2=average([e["fraction_ge_0_2"] for e in entries]),signed_shift_by_dimension={f:average([e["signed"].get(f) for e in entries]) for f in FEATURES},mean_absolute_by_dimension={f:average([e["absolute"].get(f) for e in entries]) for f in FEATURES}))
        delta=[values[CONDITIONS[1]][tid]["mean_absolute_drift"]-values[CONDITIONS[0]][tid]["mean_absolute_drift"] for tid in ids]
        contrasts.append(dict(model=model,population="model_pair",task_n=len(ids),delta_mean_absolute_drift=average(delta),**{k:v for k,v in bootstrap(delta,[dataset.records[(model,CONDITIONS[0])][tid]["base_interval_id"] for tid in ids],"p01b-a07-drift-base-v1").items() if k not in ("point","task_n")}))
    return dict(summary=summary,task_drift=tasks,paired_deltas=contrasts)


def a08(dataset):
    scenes,tasks,summary,contrasts=[],[],[],[]
    for model in dataset.models:
        ids=dataset.pairs[model]
        task_means={}
        for c in CONDITIONS:
            measured=[r for r in dataset.rows(model,c) if r["measurable"]]
            task_means[c]={}
            for r in measured:
                if r["text_ratios"] is None:
                    raise BlockedAnalysis(f"A08 unresolved original/rewritten text join {r['original_text_pointer']} {r['task_id']}")
                stats=distribution([s["word_ratio"] for s in r["text_ratios"]])
                task_means[c][r["task_id"]]=stats["mean"]
                tasks.append(dict(**label(r),population="condition_measurable",in_model_pair=r["task_id"] in ids,mean_word_ratio=stats["mean"],median_word_ratio=stats["median"],mean_character_ratio=average([s["character_ratio"] for s in r["text_ratios"]]),reported_warning_count=r["reported_warning_count"]))
                for s in r["text_ratios"]:
                    scenes.append(dict(**label(r),population="condition_measurable",in_model_pair=r["task_id"] in ids,**s))
            rows=dataset.rows(model,c,ids)
            for stratum,options in (("all",["all"]),("feature",list(FEATURES)),("length",[5,8,12])):
                for value in options:
                    selected=[r for r in rows if stratum=="all" or r["selected_feature" if stratum=="feature" else "interval_length"]==value]
                    ss=[s for r in selected for s in r["text_ratios"]]
                    d=distribution([s["word_ratio"] for s in ss]);td=distribution([task_means[c][r["task_id"]] for r in selected])
                    summary.append(dict(model=model,condition=c,population="model_pair",stratum=stratum,stratum_value=value,task_n=len(selected),scene_n=len(ss),valid_word_ratio_n=d["n"],scene_mean_word_ratio=d["mean"],scene_median_word_ratio=d["median"],task_macro_mean_word_ratio=td["mean"],task_macro_median_word_ratio=td["median"],scene_ratio_distribution=d,task_mean_ratio_distribution=td,character_ratio_distribution=distribution([s["character_ratio"] for s in ss]),short_scene_n=sum(s["word_ratio"] is not None and s["word_ratio"]<.35 for s in ss),long_scene_n=sum(s["word_ratio"] is not None and s["word_ratio"]>3 for s in ss),zero_original_n=sum(s["zero_original"] for s in ss),empty_rewrite_n=sum(s["empty_rewrite"] for s in ss),reported_warning_count=sum(r["reported_warning_count"] or 0 for r in selected),warning_records_available_n=sum(r["reported_warning_count"] is not None for r in selected)))
        valid=[tid for tid in ids if all(task_means[c][tid] is not None for c in CONDITIONS)]
        delta=[task_means[CONDITIONS[1]][tid]-task_means[CONDITIONS[0]][tid] for tid in valid]
        contrasts.append(dict(model=model,population="model_pair_with_defined_task_word_ratios",original_pair_n=len(ids),defined_pair_n=len(valid),delta_task_mean_word_ratio=average(delta),**bootstrap(delta,[dataset.records[(model,CONDITIONS[0])][tid]["base_interval_id"] for tid in valid],"p01b-a08-wordratio-base-v1")))
    return dict(summary=summary,scene_ratios=scenes,task_ratios=tasks,paired_deltas=contrasts)


def a09(dataset,artifact_paths):
    summary,cluster_manifest,frozen_results=[],[],[]
    component=overlap_components(dataset.tasks)
    for model in dataset.models:
        ids=dataset.pairs[model]
        runs={r["condition"]:r for r in dataset.plan["runs"] if r["model"]==model}
        original=cluster_bootstrap_paired(dp_run=Path(runs[CONDITIONS[0]]["records"]["path"]).parent,cg_run=Path(runs[CONDITIONS[1]]["records"]["path"]).parent,taskset_runtime=Path(dataset.plan["taskset"]["path"]),model_id=model,rng_engine="numpy-pcg64",artifact_paths=artifact_paths)
        approved=next(m for m in dataset.approved["models"] if m["model_id"]==model)
        if original["pair_task_ids"]!=approved["paired_task_ids"] or original["cluster_ids"]!=approved["cluster_ids"] or [original[k]["ci_pp"] for k in ("target_improvement","directional_accuracy")]!=approved["retained_table_A6_ci_pp"]:
            raise RuntimeError("Approved A6 endpoints/population/order failed")
        frozen_results.append(original)
        rows=dataset.rows(model,CONDITIONS[0],ids)
        for scheme in ("base_interval_id","source_window","source_overlap_component","source_film"):
            keys=[r["base_interval_id"] if scheme=="base_interval_id" else window_key(r) if scheme=="source_window" else component[r["task_id"]] if scheme=="source_overlap_component" else r["source_film_id"] for r in rows]
            groups=Counter(keys)
            cluster_manifest += [dict(model=model,scheme=scheme,cluster_id=k,cluster_task_n=v,paired_task_n=len(ids)) for k,v in sorted(groups.items())]
            for metric,k in (("TI","target_improvement"),("DA","directional_accuracy")):
                delta=[100*(dataset.records[(model,CONDITIONS[1])][tid][metric]-dataset.records[(model,CONDITIONS[0])][tid][metric]) for tid in ids]
                if scheme=="base_interval_id":
                    ci=[100*v for v in original[k]["ci"]]
                    info=dict(protocol_id="table-a6-pcg64-v1",task_n=len(ids),cluster_n=48,ci95=ci,ci_reason=None,small_cluster_warning=False,point=100*original[k]["difference"])
                else:
                    info=bootstrap(delta,keys,f"p01b-a09-{scheme}-paired-pp-v1")
                original_ci=[100*v for v in original[k]["ci"]]
                def sign_class(ci):
                    return "N/A" if ci is None else "positive" if ci[0]>0 else "negative" if ci[1]<0 else "includes_zero"
                summary.append(dict(model=model,scheme=scheme,metric=metric,population="model_pair",delta_pp=average(delta),**info,ci_sign_class=sign_class(info["ci95"]),base_ci_sign_class=sign_class(original_ci),same_CI_sign_class_as_base=sign_class(info["ci95"])==sign_class(original_ci)))
    return dict(summary=summary,cluster_manifest=cluster_manifest,approved_A6=frozen_results,overlap_component_by_task=[dict(task_id=t["task_id"],source_window=window_key(t),component=component[t["task_id"]]) for t in dataset.tasks])


def a10(dataset):
    summary,coverage,confidence,scene_changes=[],[],[],[]
    for model in dataset.models:
        for n in (5,8,12):
            ids=[tid for tid in dataset.pairs[model] if dataset.records[(model,CONDITIONS[0])][tid]["interval_length"]==n]
            dp,cg=(dataset.rows(model,c,ids) for c in CONDITIONS)
            clusters=[r["base_interval_id"] for r in dp]
            result=dict(model=model,population="model_pair_length",interval_length=n,cluster_n=len(set(clusters)),**paired_metrics(dataset,model,ids))
            for c,rows,prefix in zip(CONDITIONS,(dp,cg),("dp","cg")):
                result.update({prefix+"_mean_"+key:average([distance(r)[key] for r in rows]) for key in ("dB","dA","G")})
                result[prefix+"_mean_scene_absolute_movement"]=average([average([abs(a-b) for a,b in zip(r["A"],r["B"])]) for r in rows])
                result[prefix+"_mean_scene_distance_gain"]=average([average([abs(b-t)-abs(a-t) for b,t,a in zip(r["B"],r["T"],r["A"])]) for r in rows])
                subset=[r for r in dataset.rows(model,c) if r["interval_length"]==n]
                coverage.append(dict(model=model,condition=c,population="all_attempt_length80",interval_length=n,**all_attempt(subset)))
                for r in rows:
                    scene_changes.append(dict(**label(r),mean_scene_absolute_movement=average([abs(a-b) for a,b in zip(r["A"],r["B"])]),scene_distance_gain=[abs(b-t)-abs(a-t) for b,t,a in zip(r["B"],r["T"],r["A"])]))
            for metric in ("TI","DA","G"):
                delta=[100*(b[metric]-a[metric]) if metric!="G" else distance(b)["G"]-distance(a)["G"] for a,b in zip(dp,cg)]
                ci=bootstrap(delta,clusters,f"p01b-a10-length{n}-{metric}-base-v1")
                confidence.append(dict(model=model,interval_length=n,metric=metric,population="model_pair_length",**ci))
                result["delta_"+metric+"_ci95"]=ci["ci95"]
                result["delta_"+metric+"_ci_reason"]=ci["ci_reason"]
            summary.append(result)
    if any(r["attempted_n"]!=80 for r in coverage):
        raise RuntimeError("A10 length failure denominator contradiction")
    return dict(summary=summary,length_coverage=coverage,confidence_intervals=confidence,task_scene_diagnostics=scene_changes)


ANALYSES = (a01,a02,a03,a04,a05,a06,a07,a08,a09,a10)
