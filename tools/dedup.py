#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dedup - 文档向量语义去重（近重复检测）。

把 docs/ 下每篇 Markdown 切成片段并编码成向量，比较文档级向量的余弦相似度，
找出"字面不同但意思重复 / 高度相似"的文档对——这正是 wiki/知识库治理中
"知识向量化"真正有用的落点。

后端（--backend）：
  tfidf  默认，纯标准库，离线可用。基于词频-逆文档频的稠密向量（轻量词法近似，
         能抓住几乎相同的文本；语义 paraphrasing 需下面的 st 后端）。
  st     真实语义：需先 pip install sentence-transformers，用多语言模型编码，
         可识别"换种说法但意思一样"的重复。
  api    调用嵌入 API：设置环境变量 EMBED_API_URL / EMBED_API_KEY（按实现替换）。

用法：
  python tools/dedup.py docs
  python tools/dedup.py docs --threshold 0.8
  python tools/dedup.py docs --backend st --model BAAI/bge-small-zh-v1.5
  python tools/dedup.py docs --json
"""
import argparse
import math
import os
import re
import sys
from datetime import date

EXEMPT = {"readme.md", "_template.md"}
WIKI_RE = re.compile(r"\[\[([^\]]+)\]\]")
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def iter_md(root):
    for dp, _d, fns in os.walk(root):
        _d[:] = [d for d in _d if not d.startswith(".")]  # 跳过 .reports / .git 等
        for fn in sorted(fns):
            if fn.lower().endswith(".md") and fn.lower() not in EXEMPT:
                yield os.path.join(dp, fn)


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def strip_frontmatter(text):
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:]
    return text


def chunk_text(text, size=400):
    text = strip_frontmatter(text)
    text = re.sub(r"```.*?```", " ", text, flags=re.S)          # 去代码块
    text = WIKI_RE.sub(lambda m: m.group(1).split("|")[0], text)  # wikilink 取文字
    text = MD_LINK_RE.sub(lambda m: m.group(1).split("/")[-1], text)
    paras = [p.strip() for p in re.split(r"\n\s*\n|#{1,6}\s", text) if p.strip()]
    chunks, buf = [], ""
    for p in paras:
        if len(buf) + len(p) > size and buf:
            chunks.append(buf)
            buf = p
        else:
            buf = (buf + " " + p).strip()
    if buf:
        chunks.append(buf)
    return chunks or [""]


def tokenize(text):
    # 拉丁词 + 中文单字与二元组（CJK 用二元组才能捕捉"共享片段"）
    toks = re.findall(r"[a-zA-Z0-9]+", text.lower())
    for run in re.findall(r"[一-鿿]+", text):
        for ch in run:
            toks.append(ch)
        for i in range(len(run) - 1):
            toks.append(run[i:i + 2])
    return toks


class TfidfEmbedder:
    """离线词法向量：文档向量 = 各片段 TF-IDF 向量的均值。"""
    def __init__(self, docs_chunks):
        df = {}
        all_chunks = [c for chunks in docs_chunks for c in chunks]
        for c in all_chunks:
            for t in set(tokenize(c)):
                df[t] = df.get(t, 0) + 1
        self.df = df
        self.N = len(all_chunks)
        self.idx = {t: i for i, t in enumerate(sorted(df))}
        self.dim = len(self.idx)

    def _vec(self, chunk):
        counts = {}
        for t in tokenize(chunk):
            counts[t] = counts.get(t, 0) + 1
        vec = [0.0] * self.dim
        for t, c in counts.items():
            i = self.idx.get(t)
            if i is None:
                continue
            idf = math.log((self.N + 1) / (self.df[t] + 1)) + 1
            vec[i] = (1 + math.log(c)) * idf
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed(self, chunks):
        if not chunks:
            return [0.0] * self.dim
        dim = self.dim
        avg = [0.0] * dim
        for v in (self._vec(c) for c in chunks):
            for i in range(dim):
                avg[i] += v[i]
        return [x / len(chunks) for x in avg]


class StEmbedder:
    """真实语义向量：sentence-transformers 多语言模型。"""
    def __init__(self, model_name):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            sys.exit("未安装 sentence-transformers。请运行：pip install sentence-transformers")
        self.model = SentenceTransformer(model_name)

    def embed(self, chunks):
        if not chunks:
            return None
        embs = self.model.encode(chunks, normalize_embeddings=True)
        dim = len(embs[0])
        avg = [0.0] * dim
        for e in embs:
            for i in range(dim):
                avg[i] += e[i]
        return [x / len(embs) for x in avg]


class ApiEmbedder:
    """调用嵌入 API（需自行按服务商格式调整解析）。"""
    def __init__(self):
        self.url = os.environ.get("EMBED_API_URL")
        self.key = os.environ.get("EMBED_API_KEY")
        if not self.url:
            sys.exit("需设置环境变量 EMBED_API_URL 与 EMBED_API_KEY")

    def embed(self, chunks):
        import json
        import urllib.request
        req = urllib.request.Request(
            self.url,
            data=json.dumps({"input": chunks}).encode(),
            headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        embs = [e["embedding"] for e in data["data"]]
        dim = len(embs[0])
        avg = [0.0] * dim
        for e in embs:
            for i in range(dim):
                avg[i] += e[i]
        return [x / len(embs) for x in avg]


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def main():
    ap = argparse.ArgumentParser(description="文档向量语义去重")
    ap.add_argument("root", nargs="?", default="docs")
    ap.add_argument("--backend", default="tfidf", choices=["tfidf", "st", "api"])
    ap.add_argument("--model", default="BAAI/bge-small-zh-v1.5")
    ap.add_argument("--threshold", type=float, default=None,
                     help="相似度阈值；省略时 tfidf 用 0.55，st/api 用 0.80")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    threshold = args.threshold if args.threshold is not None else (
        0.55 if args.backend == "tfidf" else 0.80)

    root = args.root
    if not os.path.isdir(root):
        print("目录不存在: " + root)
        return 2

    paths = list(iter_md(root))
    if not paths:
        print("未找到可处理文档。")
        return 0

    docs_chunks = [chunk_text(read_text(p)) for p in paths]
    if args.backend == "tfidf":
        emb = TfidfEmbedder(docs_chunks)
        vecs = [emb.embed(ch) for ch in docs_chunks]
    elif args.backend == "st":
        emb = StEmbedder(args.model)
        vecs = [emb.embed(ch) for ch in docs_chunks]
    else:
        emb = ApiEmbedder()
        vecs = [emb.embed(ch) for ch in docs_chunks]

    pairs = []
    n = len(paths)
    for i in range(n):
        for j in range(i + 1, n):
            sim = cosine(vecs[i], vecs[j])
            if sim >= threshold:
                pairs.append((sim, paths[i], paths[j]))
    pairs.sort(reverse=True)

    result = [{"similarity": round(sim, 4),
               "a": os.path.relpath(a, root).replace("\\", "/"),
               "b": os.path.relpath(b, root).replace("\\", "/")} for sim, a, b in pairs]

    if args.json:
        import json
        print(json.dumps({"threshold": threshold, "backend": args.backend,
                          "pairs": result}, ensure_ascii=False, indent=2))
    else:
        print("向量语义去重（backend=%s, threshold=%.2f）" % (args.backend, threshold))
        print("-" * 60)
        if not result:
            print("未发现高度相似（>=%.2f）的文档对。" % threshold)
        for sim, a, b in pairs:
            print("  %.3f  %s  <->  %s" % (sim,
                  os.path.relpath(a, root).replace("\\", "/"),
                  os.path.relpath(b, root).replace("\\", "/")))
        print("-" * 60)
        print("共发现 %d 对疑似重复。" % len(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
