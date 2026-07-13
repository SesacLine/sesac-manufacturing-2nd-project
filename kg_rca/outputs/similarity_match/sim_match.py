# -*- coding: utf-8 -*-
"""step=null (direct route) 가설의 cause vs mapping_table.yaml cause 임베딩 유사도 매칭"""
import json, io, os
import numpy as np
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
load_dotenv(os.path.join(REPO, ".env"))
from openai import OpenAI
client = OpenAI()

hyps = json.load(io.open(os.path.join(HERE, "direct_hyps.json"), encoding="utf-8"))

# mapping_table.yaml의 cause + 주석/공정 정보를 텍스트로 표현
MAPPING = {
    "Edge-Ring": [
        ("etch_nonuniformity", "ETCH", "etch nonuniformity. 식각 불균일"),
        ("cmp_edge_overpolish", "CMP", "CMP edge overpolish. CMP 에지 과연마"),
        ("clean_residue", "CLEAN", "clean residue. 세정 문제로 인한 잔류물"),
    ],
    "Center": [
        ("deposition_center_thickness", "DEPO", "deposition center thickness anomaly. 증착 중앙부 두께 이상"),
        ("cmp_center_overpolish", "CMP", "CMP center overpolish. CMP 중앙 과연마"),
        ("clean_nozzle_clog", "CLEAN", "clean nozzle clog causing center residue. 세정 노즐 막힘으로 중앙 잔류"),
    ],
    "Scratch": [
        ("cmp_pad_wear", "CMP", "CMP pad wear or conditioning anomaly. CMP 패드 마모/컨디셔닝 이상"),
        ("cmp_slurry_particle", "CMP", "CMP slurry large particle scratch. 슬러리 대입자 스크래치"),
        ("clean_brush_contact", "CLEAN", "cleaning brush contact anomaly. 세정 브러시 접촉 이상"),
    ],
}

def embed(texts):
    resp = client.embeddings.create(model="text-embedding-3-small", input=texts)
    return np.array([d.embedding for d in resp.data])

def cos(a, b):
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))

# 임베딩 대상 텍스트 수집
hyp_texts = [f"{h['cause_name']}. {h['cause_description']}" for h in hyps]
map_texts, map_keys = [], []
for pat, rows in MAPPING.items():
    for slug, proc, text in rows:
        map_keys.append((pat, slug, proc))
        map_texts.append(text)

hv = embed(hyp_texts)
mv = embed(map_texts)

results = []
for i, h in enumerate(hyps):
    scores = []
    for j, (pat, slug, proc) in enumerate(map_keys):
        if pat != h["pattern"]:
            continue
        scores.append((slug, proc, round(cos(hv[i], mv[j]), 4)))
    scores.sort(key=lambda x: -x[2])
    results.append({
        "pattern": h["pattern"],
        "rank": h["rank"],
        "cause": h["cause"],
        "cause_name": h["cause_name"],
        "cause_description": h["cause_description"],
        "scores": scores,
        "best": scores[0],
    })

with io.open(os.path.join(HERE, "sim_results.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("done", len(results))
