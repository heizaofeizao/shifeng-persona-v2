#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
石枫语料检索器 —— 纯 Python 标准库 BM25 实现（零第三方依赖）

P0 架构层：为 persona skill 提供「运行时真实原话供给」。
解决静态蒸馏的有损压缩问题：让 skill 不再只能靠提炼后的规则猜，
而是能在回答前拿到真实的原帖、时间戳、分类标签与立场摘要。

字段权重设计（为何这样配）：
  stance   3.0  每条的立场摘要，一句话浓缩「他会怎么说」，信号密度最高
  concepts 2.5  themes + mentions，概念锚（如「哈耶克」「利维坦」），精确
  title    2.0  title + question_title，标题信号密度高
  text     1.0  全文基准

用法：
  python retrieve.py "查询词"                    # 默认 top 5
  python retrieve.py "哈耶克 自发秩序" -k 8
  python retrieve.py "做题家" --category stance  # 只看真立场
  python retrieve.py "疫情" --from 2024-01-01
  python retrieve.py "反讽" --json               # 机器可读输出
  python retrieve.py --rebuild                   # 强制重建索引
  python retrieve.py "X" --stats                 # 查看索引统计
  python retrieve.py --cache-info                # 看缓存位置/体积（D1）
  python retrieve.py --clean-cache               # 清缓存（含包内遗留）

索引缓存（D1）：
  缓存是派生数据，**写在 skill 包外**——原先落在 scripts/ 下，害得单份安装
  白占 11 MB。现默认 ~/.workbuddy/cache/shifeng-persona-v2/，包体保持 ~250 KB，
  首次检索自动重建（数秒），语料变更按 路径+mtime+size+条数+首末uid 自动失效。
  可用环境变量 SHIFENG_CACHE 指定目录。
"""

import argparse
import html
import json
import math
import hashlib
import os
import pickle
import re
import sys
import tempfile
import unicodedata

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
# 语料定位优先级：环境变量 > skill 包内 > 本工作区 > 上层目录
CANDIDATES = [
    os.environ.get("SHIFENG_CORPUS", ""),
    os.path.join(HERE, "..", "corpus", "final_corpus.jsonl"),
    os.path.join(HERE, "..", "..", "final_corpus.jsonl"),
    os.path.join(HERE, "..", "..", "..", "shifeng_corpus", "final_corpus.jsonl"),
]
DEFAULT_CORPUS = ""
for _c in CANDIDATES:
    if _c and os.path.exists(_c):
        DEFAULT_CORPUS = os.path.abspath(_c)
        break
if not DEFAULT_CORPUS:
    DEFAULT_CORPUS = os.path.abspath(CANDIDATES[1])

# 旧版把缓存写在包内（scripts/_bm25_index.pkl），单份安装白占 ~11 MB。
# 现只作"遗留物侦测"用，不再读写。
LEGACY_INDEX = os.path.join(HERE, "_bm25_index.pkl")


def cache_dir():
    """索引缓存目录——**必须落在 skill 包外**（D1）。

    优先级：环境变量 SHIFENG_CACHE > ~/.workbuddy/cache/shifeng-persona-v2
    > 系统临时目录。包体因此保持 ~250 KB，缓存首次运行自动重建。
    """
    for c in (os.environ.get("SHIFENG_CACHE", ""),
              os.path.join(os.path.expanduser("~"), ".workbuddy", "cache",
                           "shifeng-persona-v2"),
              os.path.join(tempfile.gettempdir(), "shifeng-persona-v2")):
        if not c:
            continue
        try:
            os.makedirs(c, exist_ok=True)
            return os.path.abspath(c)
        except OSError:
            continue
    return os.path.abspath(tempfile.gettempdir())


def index_path(corpus_path):
    """按语料绝对路径哈希命名：不同语料互不覆盖，同一语料跨安装可复用。"""
    key = os.path.abspath(corpus_path).lower().encode("utf-8")
    return os.path.join(cache_dir(), "bm25_%s.pkl" % hashlib.sha1(key).hexdigest()[:12])

# BM25 参数
K1 = 1.5
B = 0.75

# 字段 → 权重
FIELDS = [
    ("stance", 3.0),
    ("concepts", 2.5),
    ("title", 2.0),
    ("text", 1.0),
]

# 中文虚词：仅用于 unigram 降噪，bigram 不过滤
STOP = set("的了是在有我你他她它们这那和与及就都也很还要会到对为以于之而其不没")

CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
WORD = re.compile(r"[a-z0-9][a-z0-9\.\-]*", re.I)
TAG_STRIP = re.compile(r"<[^>]+>")


# ---------------------------------------------------------------- 分词

def tokenize(s):
    """中英混合分词：CJK 取 unigram + bigram（+三字整词），拉丁按词。
    unigram 保证单字查询（如「税」）也能命中；bigram 保证词组区分度。"""
    if not s:
        return []
    s = unicodedata.normalize("NFKC", str(s)).lower()
    toks = []
    for m in WORD.finditer(s):
        w = m.group(0)
        if len(w) > 1 or w.isdigit():
            toks.append(w)
    for seg in CJK_RUN.findall(s):
        n = len(seg)
        if n == 1:
            if seg not in STOP:
                toks.append(seg)
            continue
        for ch in seg:                       # unigram（去虚词）
            if ch not in STOP:
                toks.append(ch)
        for i in range(n - 1):               # bigram
            toks.append(seg[i:i + 2])
        if n == 3:                           # 三字整词
            # 注意：n==2 时"整词"与上面的 bigram 完全相同，若再 append 会让该词 tf 双计，
            # 使 2 字词（如"自由"）相对长词被系统性高估。故这里只补 n==3。
            toks.append(seg)
    return toks


# ---------------------------------------------------------------- 载入

def strip_html(s):
    if not s:
        return ""
    s = TAG_STRIP.sub("", s)
    return html.unescape(s).strip()


def _t(v):
    """字段归一化：语料里 themes/mentions 等字段有时是 str，有时是 list。"""
    if v is None:
        return ""
    if isinstance(v, (list, tuple, set)):
        return " ".join(str(x) for x in v if x is not None).strip()
    return str(v).strip()


def _int(v, default=0):
    """字段归一化：voteup/comments 在语料里可能是 str / int / None，统一转 int。"""
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def load_corpus(path):
    """读取 jsonl → 组装成带检索字段的 doc dict 列表。"""
    docs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            raw_text = _t(r.get("text"))
            if not raw_text:
                raw_text = strip_html(r.get("html") or "")
            if not raw_text:
                continue                      # 空文（no_text）不入索引
            title = _t(r.get("title"))
            qtitle = _t(r.get("question_title"))
            if qtitle and qtitle not in title:
                title = (title + " " + qtitle).strip()
            docs.append({
                "uid": _t(r.get("uid")),
                "kind": _t(r.get("kind")),
                "created": _t(r.get("created"))[:10],
                "voteup": _int(r.get("voteup")),
                "comments": _int(r.get("comments")),
                "url": _t(r.get("url")),
                "category": _t(r.get("category")),
                "confidence": float(r.get("confidence", 0.0) or 0.0),
                "stance": _t(r.get("stance")),
                "themes": _t(r.get("themes")),
                "mentions": _t(r.get("mentions")),
                "text": raw_text,
                "_title": title,
            })
    return docs


# ---------------------------------------------------------------- 索引

def build_index(docs):
    """为每个 doc 的四个字段预分词，缓存到磁盘（按语料 mtime+size 失效）。"""
    from collections import Counter
    index = []
    for d in docs:
        entry = {"uid": d["uid"]}
        for fname, _ in FIELDS:
            if fname == "text":
                raw = d["text"]
            elif fname == "stance":
                raw = d["stance"]
            elif fname == "concepts":
                raw = (d.get("themes", "") + " " + d.get("mentions", "")).strip()
            else:
                raw = d.get("_title", "")
            tf = Counter(tokenize(raw))
            entry[fname] = tf
            entry[fname + "_len"] = sum(tf.values())
        index.append(entry)
    return index


def get_index(docs, rebuild=False, corpus_path=None):
    """为每个 doc 的四个字段预分词并缓存到磁盘。

    缓存签名 = 实际语料路径 + mtime + size + 条数 + 首末 uid 指纹。
    （旧版只取 DEFAULT_CORPUS 的 mtime/size：用 --corpus 指向别的语料时，
    只要体积与条数碰巧一致，就会静默复用错索引。）
    """
    path = os.path.abspath(corpus_path or DEFAULT_CORPUS)
    try:
        st = os.stat(path)
        fp = (docs[0]["uid"] if docs else "", docs[-1]["uid"] if docs else "")
        sig = (path, st.st_mtime, st.st_size, len(docs), fp)
    except OSError:
        sig = None
    cache_path = index_path(path)
    if not rebuild and os.path.exists(cache_path):
        try:
            with open(cache_path, "rb") as f:
                cached = pickle.load(f)
            if cached.get("sig") == sig:
                return cached["index"]
        except Exception:
            pass                              # 缓存损坏 → 静默重建
    idx = build_index(docs)
    try:
        with open(cache_path, "wb") as f:
            pickle.dump({"sig": sig, "index": idx}, f)
    except Exception:
        pass                                  # 缓存失败不影响检索
    return idx


# ---------------------------------------------------------------- 检索

def filter_docs(docs, index, category=None, kind=None, date_from=None,
                date_to=None, min_conf=None):
    keep = []
    for d, e in zip(docs, index):
        if category and d["category"] != category:
            continue
        if kind and d["kind"] != kind:
            continue
        if date_from and d["created"] and d["created"] < date_from:
            continue
        if date_to and d["created"] and d["created"] > date_to:
            continue
        if min_conf is not None and float(d["confidence"]) < min_conf:
            continue
        keep.append((d, e))
    return keep


def search(query, docs, index, topk=5, category=None, kind=None,
           date_from=None, date_to=None, min_conf=None, snippet_width=180):
    pairs = filter_docs(docs, index, category, kind, date_from, date_to, min_conf)
    if not pairs:
        return []
    qtoks = tokenize(query)
    if not qtoks:
        return []
    qset = list(set(qtoks))

    # 在当前子集内统计 df 与平均长度（比用全局 IDF 更准，1686 条重算可忽略耗时）
    df = {f: {} for f, _ in FIELDS}
    totlen = {f: 0 for f, _ in FIELDS}
    for _, e in pairs:
        for f, _ in FIELDS:
            for t in e[f]:
                df[f][t] = df[f].get(t, 0) + 1
            totlen[f] += e[f + "_len"]
    N = len(pairs)
    avgdl = {f: (totlen[f] / N if N else 1.0) for f, _ in FIELDS}
    avgdl = {f: (v if v > 0 else 1.0) for f, v in avgdl.items()}

    results = []
    qnorm = query.strip().lower()
    for d, e in pairs:
        score = 0.0
        hits = 0
        for f, w in FIELDS:
            tf = e[f]
            if not tf:
                continue
            dl = e[f + "_len"] or 1
            for t in qset:
                n = tf.get(t)
                if not n:
                    continue
                docfreq = df[f].get(t, 0)
                idf = math.log(1 + (N - docfreq + 0.5) / (docfreq + 0.5))
                denom = n + K1 * (1 - B + B * dl / avgdl[f])
                score += w * idf * (n * (K1 + 1)) / denom
                hits += 1
        if score <= 0:
            continue
        # 短语整体出现（连续子串）额外加分：精确命中优先于零散词命中
        hay = (d["_title"] + " " + d["stance"] + " " + d["text"]).lower()
        if len(qnorm) >= 2 and qnorm in hay:
            score *= 1.6
        score += min(d["voteup"], 300) * 0.0015   # 轻微向高赞倾斜，打破平局
        results.append({
            "score": round(score, 3),
            "hits": hits,
            "uid": d["uid"],
            "kind": d["kind"],
            "category": d["category"],
            "confidence": d["confidence"],
            "created": d["created"],
            "voteup": d["voteup"],
            "url": d["url"],
            "title": d["_title"],
            "stance": d["stance"],
            "themes": d["themes"],
            "mentions": d["mentions"],
            "snippet": make_snippet(d["text"], qset, snippet_width),
        })
    results.sort(key=lambda x: (-x["score"], x["created"]))
    return results[:topk]


def make_snippet(text, qtoks, width=180):
    """围绕最长命中 token 取上下文窗口，而不是无脑截首部。"""
    pos, best = -1, ""
    for t in sorted(qtoks, key=len, reverse=True):
        if len(t) < 2:
            continue
        p = text.find(t)
        if p >= 0 and (pos < 0 or len(t) > len(best)):
            pos, best = p, t
    if pos < 0:
        return text[:width] + ("…" if len(text) > width else "")
    start = max(0, pos - width // 3)
    end = min(len(text), start + width)
    return ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")


# ---------------------------------------------------------------- 输出

def render_md(results, query, filters):
    lines = ["## 石枫语料检索结果", ""]
    meta = ["**查询**：`%s`" % query]
    for k, v in filters.items():
        if v:
            meta.append("**%s**：%s" % (k, v))
    meta.append("**命中**：%d 条" % len(results))
    lines.append(" ｜ ".join(meta))
    lines.append("")
    if not results:
        lines.append("> 无命中。可放宽过滤条件（如去掉 --category）或换关键词。")
        return "\n".join(lines)
    for i, r in enumerate(results, 1):
        head = "### [%d] `%s` · %s · conf %.2f · 赞%d · %s" % (
            i, r["category"], r["created"], float(r["confidence"]),
            r["voteup"], r["kind"])
        lines.append(head)
        if r["title"]:
            lines.append("**题**：%s" % r["title"])
        lines.append("")
        lines.append("> %s" % r["snippet"].replace("\n", " "))
        lines.append("")
        if r["stance"]:
            lines.append("- **立场摘要**：%s" % r["stance"])
        if r["themes"]:
            lines.append("- **主题**：%s" % r["themes"])
        if r["mentions"]:
            lines.append("- **提及**：%s" % r["mentions"])
        lines.append("- **链接**：<%s>" % r["url"])
        lines.append("")
    return "\n".join(lines)


def print_stats(docs, index):
    from collections import Counter
    cats = Counter(d["category"] for d in docs)
    kinds = Counter(d["kind"] for d in docs)
    years = Counter(d["created"][:4] for d in docs if d["created"])
    out = ["=== 索引统计 ===", "文档总数：%d" % len(docs), "",
           "按 category："]
    for k, v in cats.most_common():
        out.append("  %-10s %d" % (k, v))
    out.append("")
    out.append("按 kind：")
    for k, v in kinds.most_common():
        out.append("  %-10s %d" % (k, v))
    out.append("")
    out.append("按年份：")
    for k, v in sorted(years.items()):
        out.append("  %s  %d" % (k, v))
    toks = sum(sum(e[f + "_len"] for f, _ in FIELDS) for e in index)
    out.append("")
    out.append("索引 token 总数：%d" % toks)
    cp = index_path(DEFAULT_CORPUS)
    out.append("缓存：%s（%s）" % (
        cp, ("%.1f MB" % (os.path.getsize(cp) / 1048576)) if os.path.exists(cp) else "未生成"))
    out.append("缓存目录在 skill 包外：%s" % ("是" if not cp.startswith(HERE) else "否 ⚠️"))
    print("\n".join(out))


def print_cache_info(corpus, shown_corpus=None):
    """D1：缓存定位自检——确认缓存落在包外、包内无遗留大文件。"""
    cp = index_path(corpus)
    print("=== 索引缓存 ===")
    print("查成语料：%s" % (shown_corpus or corpus))
    print("缓存文件：%s" % cp)
    print("缓存体积：%s" % (("%.1f MB" % (os.path.getsize(cp) / 1048576))
                        if os.path.exists(cp) else "未生成（首次检索自动重建）"))
    print("缓存目录：%s" % cache_dir())
    print("在 skill 包外：%s（包目录 %s）" % (
        "是 ✅" if not cp.startswith(HERE) else "否 ⚠️", HERE))
    legacy = os.path.exists(LEGACY_INDEX)
    print("包内遗留缓存：%s" % ("存在 ⚠️ 会撑大安装体积，跑 --clean-cache 清掉"
                          if legacy else "无 ✅"))
    print("可用环境变量 SHIFENG_CACHE 改写缓存目录。")


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description="石枫语料 BM25 检索（纯标准库）")
    ap.add_argument("query", nargs="?", help="查询词")
    ap.add_argument("--corpus", default=DEFAULT_CORPUS, help="语料路径")
    ap.add_argument("-k", "--topk", type=int, default=5, help="返回条数（默认5）")
    ap.add_argument("--category", help="过滤：stance/satire/fiction")
    ap.add_argument("--kind", help="过滤：article/answer/pin")
    ap.add_argument("--from", dest="date_from", help="起始日期 YYYY-MM-DD")
    ap.add_argument("--to", dest="date_to", help="截止日期 YYYY-MM-DD")
    ap.add_argument("--min-conf", type=float, help="最低置信度")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    ap.add_argument("--rebuild", action="store_true", help="强制重建索引")
    ap.add_argument("--stats", action="store_true", help="打印索引统计")
    ap.add_argument("--cache-info", action="store_true", help="显示缓存位置与体积（D1）")
    ap.add_argument("--clean-cache", action="store_true", help="删除缓存（含包内遗留大文件）")
    ap.add_argument("--width", type=int, default=180, help="片段长度")
    args = ap.parse_args()

    corpus = os.path.abspath(args.corpus)

    if args.clean_cache:
        for p in (index_path(corpus), LEGACY_INDEX):
            try:
                if os.path.exists(p):
                    n = os.path.getsize(p)
                    os.remove(p)
                    print("已删除 %s（%.1f MB）" % (p, n / 1048576))
            except OSError as e:
                print("删除失败 %s：%s" % (p, e), file=sys.stderr)
        print("缓存目录：%s" % cache_dir())
        return

    if args.cache_info:
        print_cache_info(corpus, args.corpus)
        if not args.query:
            return
        print("")

    if not os.path.exists(corpus):
        print("找不到语料：%s" % corpus, file=sys.stderr)
        sys.exit(1)

    docs = load_corpus(corpus)
    index = get_index(docs, rebuild=args.rebuild, corpus_path=corpus)
    if len(index) != len(docs):
        index = build_index(docs)

    if args.stats:
        print_stats(docs, index)
        if not args.query:
            return
        print("")

    if not args.query:
        ap.print_help()
        return

    res = search(args.query, docs, index, topk=args.topk,
                 category=args.category, kind=args.kind,
                 date_from=args.date_from, date_to=args.date_to,
                 min_conf=args.min_conf, snippet_width=args.width)

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        filters = {
            "category": args.category, "kind": args.kind,
            "时间": "%s ~ %s" % (args.date_from or "起点", args.date_to or "今日"),
        }
        print(render_md(res, args.query, filters))


if __name__ == "__main__":
    main()
