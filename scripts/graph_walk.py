#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
概念图谱游走 —— P4

解决的问题：knowledge_graph.json（395 节点 / 303 边）此前完全闲置。
没有它时，模型推演"X 会让他想到什么"走的是**通用语义邻近**——
那是任何人的联想，不是石枫的联想。

有了它，推演沿**他自己的概念共现拓扑**走：他脑子里"哈耶克"旁边站的是
"米塞斯/罗斯巴德/霍普"，不是 LLM 先验里那串东西。这是三重验证里
「排他性」的机器保障——保证产出是他的联想，不是通用保守主义的联想。

用法：
  python graph_walk.py "哈耶克"              # 一跳邻居
  python graph_walk.py "哈耶克" --depth 2    # 二跳
  python graph_walk.py "哈耶克" "儒家" --path  # 两概念间的桥接路径
  python graph_walk.py "利维坦" --json
  python graph_walk.py --top                 # 列出高频概念总榜
"""

import argparse
import json
import os
import sys
from collections import deque

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_GRAPH = ""
for _c in [
    os.environ.get("SHIFENG_GRAPH", ""),
    os.path.join(HERE, "..", "corpus", "knowledge_graph.json"),
    os.path.join(HERE, "..", "..", "knowledge_graph.json"),
    os.path.join(HERE, "..", "..", "..", "shifeng_corpus", "knowledge_graph.json"),
]:
    if _c and os.path.exists(_c):
        DEFAULT_GRAPH = os.path.abspath(_c)
        break

# 同一人物的不同译名 —— 图谱里是分裂的，查询前归一化，否则邻接被稀释
ALIAS = {
    "伯克": "柏克",
    "杰弗逊": "杰斐逊",
    "拉塞尔·柯克": "柯克",
    "帕特里克·德尼恩": "德尼恩",
    "德尼恩": "德尼恩",
    "赛国": "赛里斯",
}


def norm(s):
    return ALIAS.get(s.strip(), s.strip())


class Graph:
    def __init__(self, path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.freq = {}
        for nd in data.get("nodes", []):
            k = norm(nd.get("id", ""))
            if k:
                self.freq[k] = self.freq.get(k, 0) + int(nd.get("freq", 0))
        self.adj = {}
        for e in data.get("edges", []):
            a, b = norm(e.get("a", "")), norm(e.get("b", ""))
            w = int(e.get("weight", 1))
            if not a or not b or a == b:
                continue
            self.adj.setdefault(a, {})[b] = self.adj.setdefault(a, {}).get(b, 0) + w
            self.adj.setdefault(b, {})[a] = self.adj.setdefault(b, {}).get(a, 0) + w

    def neighbors(self, node, depth=1):
        """BFS 到指定深度，返回 {节点: (最短跳数, 累计权重, 路径)}"""
        node = norm(node)
        if node not in self.adj and node not in self.freq:
            return None
        seen = {node: (0, 0, [node])}
        q = deque([(node, 0)])
        while q:
            cur, d = q.popleft()
            if d >= depth:
                continue
            for nb, w in sorted(self.adj.get(cur, {}).items(), key=lambda x: -x[1]):
                if nb in seen:
                    continue
                seen[nb] = (d + 1, seen[cur][1] + w, seen[cur][2] + [nb])
                q.append((nb, d + 1))
        seen.pop(node, None)
        return seen

    def path(self, a, b):
        a, b = norm(a), norm(b)
        if a not in self.adj or b not in self.adj:
            return None
        if a == b:
            return [a]
        prev = {a: None}
        q = deque([a])
        while q:
            cur = q.popleft()
            if cur == b:
                break
            for nb in self.adj.get(cur, {}):
                if nb not in prev:
                    prev[nb] = cur
                    q.append(nb)
        if b not in prev:
            return None
        out, cur = [], b
        while cur is not None:
            out.append(cur)
            cur = prev[cur]
        return out[::-1]


def main():
    ap = argparse.ArgumentParser(description="概念图谱游走（P4）")
    ap.add_argument("concept", nargs="?", help="起始概念")
    ap.add_argument("target", nargs="?", help="目标概念（配合 --path）")
    ap.add_argument("--graph", default=DEFAULT_GRAPH)
    ap.add_argument("--depth", type=int, default=1, help="游走深度（默认1）")
    ap.add_argument("--limit", type=int, default=15, help="每层最多列出（默认15）")
    ap.add_argument("--path", action="store_true", help="求两概念间的最短桥接路径")
    ap.add_argument("--top", action="store_true", help="列出高频概念总榜")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not args.graph or not os.path.exists(args.graph):
        print("找不到图谱：%r" % args.graph, file=sys.stderr)
        sys.exit(1)
    g = Graph(args.graph)

    if args.top:
        items = sorted(g.freq.items(), key=lambda x: -x[1])[:args.limit]
        if args.json:
            print(json.dumps(items, ensure_ascii=False, indent=2))
            return
        print("## 高频概念总榜（前 %d）" % args.limit)
        print("")
        print("| # | 概念 | 频次 |")
        print("|---|---|---|")
        for i, (k, v) in enumerate(items, 1):
            print("| %d | %s | %d |" % (i, k, v))
        return

    if not args.concept:
        ap.print_help()
        return

    if args.path:
        if not args.target:
            print("--path 需要给出目标概念", file=sys.stderr)
            sys.exit(1)
        p = g.path(args.concept, args.target)
        if args.json:
            print(json.dumps({"path": p}, ensure_ascii=False))
            return
        if not p:
            print("## 桥接：%s ⇄ %s" % (args.concept, args.target))
            print("")
            print("> 图谱中无连通路径——他没把这两样东西放在一块儿讲过。")
            return
        print("## 桥接：%s ⇄ %s" % (args.concept, args.target))
        print("")
        print(" > ".join(p))
        print("")
        print("共 %d 跳。这条链是他自己文本里的共现路径，可作为论证串联的骨架。" % (len(p) - 1))
        return

    nb = g.neighbors(args.concept, depth=args.depth)
    if nb is None:
        print("## 概念邻接：%s" % args.concept)
        print("")
        print("> 图谱中无此概念。可试别名或换关键词（`--top` 看总榜）。")
        return

    rows = sorted(nb.items(), key=lambda x: (x[1][0], -x[1][1]))[:args.limit]
    if args.json:
        print(json.dumps({
            "concept": args.concept, "freq": g.freq.get(norm(args.concept), 0),
            "neighbors": [{"id": k, "hops": v[0], "weight": v[1],
                           "freq": g.freq.get(k, 0), "path": v[2]}
                          for k, v in rows],
        }, ensure_ascii=False, indent=2))
        return

    print("## 概念邻接：%s" % args.concept)
    print("")
    print("该概念在语料中出现 **%d** 次。以下是**他自己的共现网络**中与之相连的概念"
          % g.freq.get(norm(args.concept), 0))
    print("（不是通用语义联想，是从其 1686 条原文共现统计得来）。")
    print("")
    print("| 概念 | 跳数 | 共现权重 | 该概念频次 |")
    print("|---|---|---|---|")
    for k, (hops, w, _) in rows:
        print("| %s | %d | %d | %d |" % (k, hops, w, g.freq.get(k, 0)))
    print("")
    print("### 怎么用")
    print("")
    print("- 推演时**沿这张表串概念**，别用你自己的联想补位")
    print("- 共现权重越高，越是他会自然并置的论证资源")
    print("- 需要把两个远距离概念连起来时，用 `--path` 找他自己的桥接链")


if __name__ == "__main__":
    main()
