"""Prepare reproducible review packets. Never calls a model or invents review results."""
from collections import defaultdict, deque
import json
from pathlib import Path
from .db import utcnow
from .summaries import source_payload, input_hash, validate_output, PROMPT_VERSION, SummaryError


FORMAT = "github-rank-summary-evaluation"


def balanced(items, key, limit):
    buckets = defaultdict(deque)
    for item in items:
        buckets[key(item)].append(item)
    result = []
    while len(result)<limit and any(buckets.values()):
        for group in sorted(buckets):
            if buckets[group] and len(result)<limit:
                result.append(buckets[group].popleft())
    return result


def prepare_evaluation(db, project_count=30, news_count=30, resource_count=10, model=None):
    counts = {"project":project_count,"news":news_count,"resource":resource_count}
    if any(type(n) is not int or not 0<=n<=100 for n in counts.values()) or not sum(counts.values()):
        raise ValueError("Choose 0 to 100 per entity kind and at least one sample")
    with db.connect() as con:
        con.execute("BEGIN")
        overrides = {r["repo_id"]:dict(r) for r in con.execute("SELECT * FROM repository_overrides")}
        projects = [json.loads(r["data"]) for r in con.execute("SELECT data FROM repositories ORDER BY full_name COLLATE NOCASE")]
        news = [json.loads(r["data"]) for r in con.execute("SELECT data FROM news ORDER BY published_at DESC,id")]
        resources = [json.loads(r["data"]) for r in con.execute("SELECT data FROM resources ORDER BY repo_id,path")]
        summaries = [dict(r) for r in con.execute("SELECT * FROM summaries ORDER BY created_at DESC,rowid DESC")]
    projects = [r for r in projects if not overrides.get(r["id"],{}).get("excluded") and not (r.get("archived") or r.get("disabled") or r.get("is_fork"))]
    resources = [r for r in resources if not overrides.get(r["repo_id"],{}).get("excluded")]
    selected = {"project":balanced(projects,lambda r:r["category"]+":"+(r.get("language") or "unknown"),project_count),
                "news":balanced(news,lambda r:r["source_id"]+":"+r["topic"],news_count),
                "resource":balanced(resources,lambda r:r["kind"]+":"+r.get("ecosystem","unknown"),resource_count)}
    cache = {}
    for row in summaries:
        if row["prompt_version"]==PROMPT_VERSION and (not model or row["model"]==model):
            cache.setdefault((row["entity_kind"],row["entity_id"],row["input_hash"]),row)
    samples = []
    for kind,items in selected.items():
        for item in items:
            payload = source_payload(kind,item)
            digest = input_hash(payload)
            candidate = cache.get((kind,str(item["id"]),digest))
            samples.append({"sample_id":f"{kind}:{item['id']}:{digest[:16]}","entity_kind":kind,"entity_id":str(item["id"]),
                            "name":payload["name"],"url":item["url"],"input_hash":digest,"input":payload,
                            "candidate":json.loads(candidate["data"]) if candidate else None,
                            "candidate_meta":{k:candidate[k] for k in ("model","prompt_version","created_at")} if candidate else None,
                            "review":{"facts_supported":None,"chinese_clear":None,"useful":None,"notes":""}})
    return {"format":FORMAT,"version":1,"created_at":utcnow(),"prompt_version":PROMPT_VERSION,
            "requested":counts,"selected":{k:len(v) for k,v in selected.items()},"model_filter":model,
            "selection":"Deterministic round robin across category/language, source/topic and resource kind/ecosystem; no model calls.",
            "samples":samples}


def evaluation_report(packet):
    if not isinstance(packet,dict) or packet.get("format")!=FORMAT or packet.get("version")!=1 or not isinstance(packet.get("samples"),list) or len(packet["samples"])>300:
        raise ValueError("Unsupported evaluation packet")
    counts = {k:0 for k in ("samples","missing_outputs","generated","invalid_input","invalid_output","awaiting_review","human_reviewed","human_passed","human_rejected")}
    rows, seen = [], set()
    for sample in packet["samples"]:
        counts["samples"] += 1
        status, error = None, None
        sample_id = sample.get("sample_id") if isinstance(sample,dict) else None
        try:
            if not isinstance(sample,dict) or not isinstance(sample_id,str) or not isinstance(sample.get("input"),dict):
                raise ValueError("Malformed sample")
            payload=sample["input"]
            if payload.get("kind") not in ("project","news","resource") or sample.get("entity_kind")!=payload["kind"] or not isinstance(sample.get("entity_id"),str):
                raise ValueError("Invalid entity identity")
            if not isinstance(payload.get("name"),str) or not isinstance(payload.get("sources"),list) or not 1<=len(payload["sources"])<=4:
                raise ValueError("Malformed source payload")
            if any(not isinstance(source,dict) or any(not isinstance(source.get(key),str) for key in ("id","url","text")) for source in payload["sources"]):
                raise ValueError("Malformed source evidence")
            if len({source["id"] for source in payload["sources"]})!=len(payload["sources"]):
                raise ValueError("Duplicate source identity")
            digest=input_hash(payload)
            if sample_id!=f"{sample['entity_kind']}:{sample['entity_id']}:{digest[:16]}" or sample_id in seen or digest!=sample["input_hash"]:
                raise ValueError("Sample identity or input hash changed")
            seen.add(sample_id)
            if sample.get("candidate") is None:
                status = "missing_outputs"
            else:
                counts["generated"] += 1
                candidate = sample["candidate"]
                try:
                    clean = {**candidate,"evidence":[{k:e[k] for k in ("source_id","quote")} for e in candidate["evidence"]]}
                    checked = validate_output(clean,sample["input"])
                    for original,validated in zip(candidate["evidence"],checked["evidence"]):
                        if "url" in original and original["url"]!=validated["url"]:
                            raise ValueError("Citation URL changed")
                except (ValueError,KeyError,TypeError,SummaryError) as exc:
                    status, error = "invalid_output",str(exc)[:200]
                if not status:
                    review = sample.get("review",{})
                    review = review if isinstance(review,dict) else {}
                    flags = [review.get(k) for k in ("facts_supported","chinese_clear","useful")]
                    if not all(isinstance(flag,bool) for flag in flags):
                        status = "awaiting_review"
                    else:
                        counts["human_reviewed"] += 1
                        status = "human_passed" if all(flags) else "human_rejected"
        except (ValueError,KeyError,TypeError) as exc:
            status, error = "invalid_input",str(exc)[:200]
        counts[status] += 1
        rows.append({"sample_id":sample_id,"status":status,"error":error})
    return {"format":FORMAT+"-report","created_at":utcnow(),"counts":counts,
            "human_pass_rate":counts["human_passed"]/counts["human_reviewed"] if counts["human_reviewed"] else None,
            "automatic_validity_rate":(counts["generated"]-counts["invalid_output"])/counts["generated"] if counts["generated"] else None,
            "note":"Literal evidence validation does not establish semantic accuracy. Human scores exist only for completed manual reviews.","samples":rows}


def write_json(path, value):
    path = Path(path)
    if path.suffix.lower()!=".json":
        raise ValueError("Use a .json output path")
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x",encoding="utf-8") as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
