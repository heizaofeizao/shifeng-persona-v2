# -*- coding: utf-8 -*-
"""style_check.py — 文风指纹闸门（P6 · v3）

把「像不像石枫」从形容词变成可比对的数字，三层次一起量：
  L1 标点层  —— 逗号/句号/问号/叹号/破折号/省略号/引号/【讲解冒号】的千字密度
  L2 句法层  —— 句长均/中位、长句率、多逗号率、句首连接率、句末反问率、引述包抄率
  L3 篇章层  —— 论证装置、机械分层标记闸门、【结尾闸门·禁回扣/禁号召/禁升华】

【分层基线】密度指标会被长文稀释，短答必须用短答基线，否则误伤。
基线取自非虚构语料实测（剔除译稿与小说），区间为各层单篇 p10~p90：
  short = answer<300字    242 条   （默认，对付日常应答）
  mid   = answer 300~800字 247 条   （**四段式回答落在这里，最常用**）
  pin   = 想法 pins        840 条
  long  = answer>=800字    252 条
**不传 --profile 时按字数自动选档**——拿短答的尺去量中长回答是最常见的误伤来源。

【v3 新增 · 讲解冒号】语料实测：讲解冒号在短答中位数 **0**（82% 篇目一个都没有）、
在中答中位数同为 **0**（p90 才 3.6/千字）。所以"论述讲解冒号"（如「绕不开两条：……」）
在回答里基本必错，除非你在写长文（long p50=1.6）。用逗号断句或直接另起一句。
注意：引述冒号（：后紧跟 “…”/《》/链接）不算，那与讲解无关。

【v3 新增 · 结尾闸门】语料实测短答末句含升华/总结词仅 **0.9%**、pin 仅 1.4%。
他的结尾是「平实泄气」或「狠话直落」或「疑问悬停」，**从不回扣开头、从不发出号召**。
典型雷区：「……先把X扶正，再谈Y吧」这类作文式闭合——命中的三条典型信号是
①末句带「吧」等祈使 ②末句含升华/总结词 ③末段复现开头段的独特短语。

【v4 新增 · 论战结构】议题涉目田/白左/城市小资等靶子词时，自动加检「德性攻击四拍」：
点靶 → 揭梦 → 论德 → 反转。**只有第 1 拍（点名骂）＝喷子腔，判不合格**；缺第 4 拍
「反转（享受者→寄食者/破坏者）」判告警。细则与真实语料见 modules/style-invective.md。

用法：
    python scripts/style_check.py draft.txt                # 自动选档 + 自动查论战结构
    python scripts/style_check.py draft.txt --profile long # 手动指定
    python scripts/style_check.py draft.txt --invective    # 强制输出论战结构段
    type draft.txt | python scripts/style_check.py -
"""
import sys, re

# ── L1 标点层：{指标: (低, 高)}，千字密度。「冒号」= 讲解冒号，引述冒号不计 ──
#    区间取自各层单篇 p10~p90（单篇方差大，用分位而非均值）。
PUNCT_BASE = {
    'short': {'逗号': (19, 47), '句号': (8, 31), '问号': (0, 19), '叹号': (0, 1.0),
              '破折号': (0, 1.2), '省略号': (0, 1.3), '引号': (0, 21), '讲解冒号': (0, 3.0)},
    'mid':   {'逗号': (25, 44), '句号': (12, 26), '问号': (0, 11), '叹号': (0, 1.0),
              '破折号': (0, 2.8), '省略号': (0, 1.7), '引号': (1, 19), '讲解冒号': (0, 3.6)},
    'pin':   {'逗号': (18, 43), '句号': (7, 27), '问号': (0, 18), '叹号': (0, 1.0),
              '破折号': (0, 1.5), '省略号': (0.3, 5.3), '引号': (0, 23), '讲解冒号': (0, 3.0)},
    'long':  {'逗号': (28, 44), '句号': (12, 23), '问号': (0, 6), '叹号': (0, 0.6),
              '破折号': (0.6, 3.1), '省略号': (0, 1.1), '引号': (2, 15), '讲解冒号': (0, 3.8)},
}
# ── L2 句法层：{指标: (低, 高)}，其中带 % 的为「句占比」，其余为字/句长 ──
SYNTAX_BASE = {
    'short': {'句长中位': (20, 72), '句长均': (24, 62), '长句率': (9, 67),
              '多逗号率': (0, 50), '句首连接率': (0, 33), '句末反问率': (0, 60),
              '引述包抄率': (0, 60)},
    'mid':   {'句长中位': (28, 53), '句长均': (31, 56), '长句率': (23, 69),
              '多逗号率': (0, 37), '句首连接率': (0, 27), '句末反问率': (0, 43),
              '引述包抄率': (4, 50)},
    'pin':   {'句长中位': (23, 65), '句长均': (27, 57), '长句率': (17, 67),
              '多逗号率': (0, 33), '句首连接率': (0, 33), '句末反问率': (0, 56),
              '引述包抄率': (0, 67)},
    'long':  {'句长中位': (31, 56), '句长均': (37, 59), '长句率': (33, 67),
              '多逗号率': (10, 34), '句首连接率': (4, 25), '句末反问率': (0, 25),
              '引述包抄率': (7, 50)},
}
CONNECTIVES = ['当然', '其实', '毕竟', '本来', '反正', '无非', '既然', '倒是', '恰恰',
               '归根结底', '也就是说', '反而是', '不过是', '问题是', '说到底']
OPENERS = ['所以', '然而', '如果', '当然', '因此', '因为', '至于', '正如',
           '但是', '就像', '那么', '这样', '这种', '不过', '其实', '毕竟', '反正', '既然']
ANALOGY = ['正如', '就像', '好比', '一样', '类似', '如同']
CONCESSION = ['客观来说', '说到底', '其实', '当然', '固然', '虽说', '虽然', '诚然']
DISSECT = ['拎', '扒', '戳', '撕', '揭', '剥', '拆']
# ── L3 篇章层：机械分层标记（语料实测 ≈0~1.1/万字，短答里出现即破功）──
BAN_STRUCT = ['首先', '其次', '再次', '综上所述', '总而言之', '总的来说', '总之',
              '值得注意的是', '不难看出', '由此可见', '一方面', '另一方面',
              '换言之', '换句话说']
BAN_SOFT = ['显然', '事实上', '众所周知', '不可否认', '毋庸置疑']
UNWANTED = ['赋能', '抓手', '闭环', '底层逻辑', '认知升级', '破局', '生态位', '颗粒度']
# ── v3 结尾闸门词表 ──
END_SUMM = ['总而言之', '总之', '综上', '说到底', '归根结底', '这才是', '方为正道',
            '才是正道', '共勉', '让我们', '愿我们', '我们应该', '所以我们要',
            '因此我们', '值得铭记', '最后的结论']
END_IMPER = ['不要', '别忘', '应该', '该当', '不妨', '请记住', '务必', '切莫',
             '何乐而不为', '不可不', '不如']
# ── v4 论战结构：德性攻击四拍（detail 见 modules/style-invective.md）──
INV_TARGET = ['目田', '白左', '进步人', '进步壬', '社民进步', '进步教徒', '自由派',
              '辉格派', '城市小资', '体面中产', '公众号写手', '费拉', '赢学', '入关学']
INV_DREAM = ['沉浸在', '岁月静好', '幻象', '幻梦', '美梦', '做梦', '眷恋', '虔诚地相信',
             '地球村', '黄金时代', '旧梦', '朦胧幻想', '自我感动']
INV_VIRTUE = ['德性', '德行', '美德', '德不配位', '不事生产', '空无一物', '摆设的道德',
              '自知之明', '体面感', '庸俗', '堕落', '奴隶的美德']
INV_REVERSE = ['寄生虫', '贵族幻象', '错觉', '于是以为', '自以为', '实则', '其实是在',
               '拆毁', '维系下去', '进步之神', '糟蹋', '坐吃山空']
INV_LIST = ['空调', '手机', '床单', '打卡', '露营', '冲浪', '登山', '大house', '烤火鸡',
            '逛商场', '爬雪山', '网红', '短视频', '外卖']
# 引述冒号：：后（跳过空格）紧跟 引号/书名号/括号/链接/年份（贴图说明或标题）
RE_COLON = re.compile('：')


def lecture_colons(t):
    """只数「讲解冒号」——后面直接接正文分句的冒号。引述/链接/标题/列举 均不计。"""
    out = []
    for m in RE_COLON.finditer(t):
        j = m.end()
        while j < len(t) and t[j] in ' \t':
            j += 1
        nxt = t[j:j + 4]
        if not nxt:
            continue
        if nxt[0] in '“「《（(':     # 引述冒号
            continue
        if nxt[0] == '\n':            # 换行块（贴图/标题）
            continue
        if nxt.startswith('http'):    # 链接
            continue
        if re.match(r'^\d{4}年', nxt):  # 年份（贴图说明）
            continue
        if re.match(r'^[一二三四五六七八九十0-9①-⑩]', nxt):  # 列举
            continue
        out.append(t[max(0, m.start() - 12):m.start() + 14].replace('\n', ' '))
    return out


def grammar_split(t):
    return [s.strip() for s in re.split(r'(?<=[。！？!?；;])', t) if len(s.strip()) >= 4]


def metrics(t):
    N = max(len(t), 1)
    m = {}
    for ch, nm in [('，', '逗号'), ('。', '句号'), ('？', '问号'), ('！', '叹号'),
                   ('——', '破折号'), ('……', '省略号'), ('“', '引号')]:
        m[nm] = t.count(ch) / N * 1000
    col = lecture_colons(t)
    m['讲解冒号'] = len(col) / N * 1000
    m['_colons'] = col
    S = grammar_split(t)
    n = max(len(S), 1)
    lens = sorted(len(s) for s in S)
    m['句长中位'] = lens[len(lens) // 2] if lens else 0
    m['句长均'] = sum(lens) / n if lens else 0
    m['长句率'] = sum(1 for x in lens if x > 40) / n * 100
    m['多逗号率'] = sum(1 for s in S if s.count('，') >= 3) / n * 100
    m['句首连接率'] = sum(1 for s in S if any(s.startswith(w) for w in OPENERS)) / n * 100
    m['句末反问率'] = sum(1 for s in S if s.endswith('？')) / n * 100
    m['引述包抄率'] = sum(1 for s in S if '“' in s) / n * 100
    m['_类比句'] = sum(1 for s in S if any(w in s for w in ANALOGY))
    m['_让步句'] = sum(1 for s in S if any(w in s for w in CONCESSION))
    m['_解剖句'] = sum(1 for s in S if any(w in s for w in DISSECT))
    m['_实例'] = len(re.findall(r'@|《|》（|年|省|市|国$', t))
    m['_n句'] = len(S)
    m['我'] = t.count('我') - t.count('我们')
    m['我们'] = t.count('我们')
    m['_conn'] = [c for c in CONNECTIVES if c in t]
    m['_open'] = [w for w in OPENERS if w in t]
    m['_ban'] = [w for w in BAN_STRUCT if w in t]
    m['_soft'] = [w for w in BAN_SOFT if w in t]
    m['_unw'] = [w for w in UNWANTED if w in t]
    return m


def first_move(t):
    """判定起笔方式（篇章层）"""
    s = re.split(r'(?<=[。！？])', t.strip())
    head = s[0] if s else t[:40]
    if head.lstrip().startswith('“') or '“' in head[:30]:
        return '引述包抄', True
    if any(head.startswith(w) for w in ['客观来说', '说到底', '其实', '当然', '固然', '虽说', '虽然', '诚然']):
        return '让步/自贬起手', True
    if any(head.startswith(w) for w in OPENERS):
        return '连接词起笔（可）', True
    if head.rstrip().endswith('？') and ('还是' in head or '是不是' in head):
        return '设问立论（评论员腔）', False
    return '直陈判断（可）', True


def ending(t):
    """v3 结尾闸门：返回 (末句, 末段, [问题列表])"""
    ps = [p.strip() for p in re.split(r'\n+', t) if p.strip()]
    last_par = ps[-1] if ps else t.strip()
    sents = [s for s in re.split(r'(?<=[。？！；])', last_par) if s.strip()]
    last = sents[-1] if sents else last_par
    probs = []
    # 1) 升华/总结收尾
    hit_s = [w for w in END_SUMM if w in last]
    if hit_s:
        probs.append(f'升华/总结收尾（命中 {"、".join(hit_s)}）——语料基线仅 0.9%，他不用这招')
    # 2) 号召/祈使收尾（……吧 / 让我们……）
    if re.search(r'吧[。！？]?\s*$', last) or last.rstrip().endswith('吧'):
        probs.append('收束为「……吧」祈使句——他极少用号召式结尾')
    elif re.search(r'[？?]\s*$', last):
        pass  # 疑问悬停是允许的（短答 24.8%）
    else:
        hit_i = [w for w in END_IMPER if w in last]
        if len(hit_i) >= 1 and re.search(r'(不如|不妨|应该|不要|请|务必)', last):
            probs.append(f'末句带祈使/劝诫（命中 {"、".join(hit_i)}）——他不用劝导腔收尾')
    # 3) 回扣开头（首末段共享「4 字短语」≥2，且非全文反复出现的话题短语）
    #    用 2-gram 会误报（"的那""我看"这类碎片），必须用 4-gram 才有诊断力。
    first_par = ps[0] if ps else ''
    def grams(s, k=4):
        z = re.sub(r'[^\u4e00-\u9fa5]', '', s)
        return {z[i:i + k] for i in range(len(z) - k + 1)}
    whole = re.sub(r'[^\u4e00-\u9fa5]', '', t)
    if len(ps) >= 3:
        shared = {g for g in (grams(first_par) & grams(last_par))
                  if whole.count(g) < 3}          # 全文 ≥3 次 = 话题短语，不算
        if len(shared) >= 2:
            probs.append(f'末段回扣开头（复现短语 {"、".join(list(shared)[:3])}）——他是「讲完就停」，不做首尾闭合')
    return last, last_par, probs


def invective(t):
    """论战结构自检：德性攻击四拍 = 点靶 → 揭梦 → 论德 → 反转。
    仅当文本确含「靶子词」时才视为开火（否则普通回答不该被判罚）。
    返回 (hits, warns)；warns 只针对「开了火但结构残缺」的走形。"""
    hits = {
        '点靶': [w for w in INV_TARGET if w in t],
        '揭梦': [w for w in INV_DREAM if w in t],
        '论德': [w for w in INV_VIRTUE if w in t],
        '反转': [w for w in INV_REVERSE if w in t],
        '清单': [w for w in INV_LIST if w in t],
    }
    warns = []
    if not hits['点靶']:
        return hits, warns
    # 开火之后：后两拍是骨架
    if not hits['论德'] and not hits['反转']:
        warns.append('论战 纯点名攻击，无德性/反转拍——喷子腔（须补第3+4拍）')
    elif not hits['反转']:
        warns.append('论战 缺第4拍「反转」（享受者→寄食者/破坏者）——本模式灵魂拍')
    if not hits['揭梦'] and not hits['反转']:
        warns.append('论战 缺第2拍「揭梦」（拆穿其时代幻觉）')
    return hits, warns


def auto_profile(t):
    """按字数自动选档：<300 短答 · 300~800 中答 · >=800 长文。
    绝不拿短答的尺量中长回答——那是最常见的误伤来源。"""
    n = len(t)
    if n < 300:
        return 'short'
    if n < 800:
        return 'mid'
    return 'long'


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    inv_force = '--invective' in sys.argv[1:]
    profile = None
    if '--profile' in sys.argv[1:]:
        i = sys.argv.index('--profile')
        if i + 1 < len(sys.argv):
            profile = sys.argv[i + 1]
    src = args[0] if args else '-'
    t = (src == '-' and sys.stdin.read() or (src != '-' and open(src, encoding='utf-8').read()) or '').strip()
    auto = profile is None
    if auto:
        profile = auto_profile(t)
    pb = PUNCT_BASE.get(profile, PUNCT_BASE['short'])
    sb = SYNTAX_BASE.get(profile, SYNTAX_BASE['short'])
    m = metrics(t)
    warns = []

    tag = f'profile={profile}' + ('（自动）' if auto else '')
    print(f'## 文风指纹比对 v3  （样本 {len(t)} 字 · {tag}）\n')
    print('── L1 标点层（千字密度）──')
    print(f'{"指标":<8}{"实测":>9}{"基线区间":>16}  判定')
    for name, (lo, hi) in pb.items():
        v = m[name]
        ok = 'OK' if lo <= v <= hi else ('低 ⚠' if v < lo else '高 ⚠')
        if '⚠' in ok:
            warns.append(f'L1 {name} {v:.1f} 越界({lo}~{hi})')
        print(f'{name:<8}{v:>9.2f}{f"{lo}~{hi}":>16}  {ok}')

    print('\n── L2 句法层（句长 / 句占比）──')
    print(f'{"指标":<10}{"实测":>9}{"基线区间":>16}  判定')
    for name, (lo, hi) in sb.items():
        v = m[name]
        ok = 'OK' if lo <= v <= hi else ('低 ⚠' if v < lo else '高 ⚠')
        if '⚠' in ok:
            warns.append(f'L2 {name} {v:.1f} 越界({lo}~{hi})')
        unit = '%' if name.endswith('率') else ''
        print(f'{name:<10}{v:>8.1f}{unit:<1}{f"{lo}~{hi}":>16}  {ok}')

    print('\n── L3 篇章层 ──')
    mv, ok0 = first_move(t)
    print(f'起笔方式：{mv}' + ('' if ok0 else '  ⚠ 评论员腔（改写为引述包抄/让步起手/直陈判断）'))
    if not ok0:
        warns.append('L3 起笔为设问立论（评论员腔）')
    dev = m['_类比句'] + m['_解剖句'] + (1 if m['引述包抄率'] >= 5 else 0)
    print(f'论证装置：类比句 {m["_类比句"]} · 解剖动词句 {m["_解剖句"]} · '
          f'引述包抄率 {m["引述包抄率"]:.0f}%  → 合计 {dev}')
    if dev < 2:
        print('  ⚠ 论证装置过少——他惯用「引述包抄 / 类比 / 拆词」，纯抽象概括不像他。')
        warns.append('L3 论证装置过少（<2）')
    if m['_ban']:
        print(f'  ⚠ 机械分层标记命中：{"、".join(m["_ban"])}  → 语料实测≈0，命中即破功。')
        warns.append(f'L3 机械分层标记 {"/".join(m["_ban"])}')
    if len(m['_soft']) >= 2:
        print(f'  ⚠ 评价旁白过多：{"、".join(m["_soft"])}')
        warns.append('L3 评价旁白过多')
    if m['_unw']:
        print(f'  ⚠ 互联网黑话：{"、".join(m["_unw"])}——他不用这类词。')
        warns.append(f'L3 互联网黑话 {"/".join(m["_unw"])}')
    if not (m['_ban'] or len(m['_soft']) >= 2 or m['_unw']):
        print('  OK 无禁用结构。')

    # v3 讲解冒号详情
    if m['_colons']:
        print(f'\n⚠ 讲解冒号 {len(m["_colons"])} 处（短答 82% 篇目为 0）——'
              f'改写为逗号断句或直接另起一句：')
        for c in m['_colons'][:6]:
            print(f'   · …{c}…')

    # v3 结尾闸门
    last, last_par, eprobs = ending(t)
    print(f'\n── 结尾闸门（v3）──\n末句：{last[:60]}')
    if eprobs:
        for p in eprobs:
            print(f'  ⚠ {p}')
            warns.append(f'L3 结尾 {p.split("——")[0]}')
    else:
        print('  OK 结尾无升华/号召/回扣。')

    print(f'\n高频口癖命中（{len(m["_conn"])}/{len(CONNECTIVES)}）：{"、".join(m["_conn"]) or "无"}')
    if len(m['_conn']) < 3:
        print('  ⚠ 命中过少——腔调偏「通用保守派评论员」，缺他的口癖。')
        warns.append(f'口癖仅 {len(m["_conn"])} 个')
    print(f'句首连接词：{"、".join(m["_open"]) or "无"}')
    ratio = m['我'] / m['我们'] if m['我们'] else float('inf')
    rflag = '' if (m['我们'] and 1.2 <= ratio <= 6) else '  ⚠ 缺"我们"维度或比例失衡'
    if rflag:
        warns.append(f'我/我们={m["我"]}/{m["我们"]}')
    print(f'第一人称 我/我们 = {m["我"]}/{m["我们"]}  （基线 ≈2.7:1）{rflag}')

    # v4 论战结构（德性攻击四拍）——命中靶子词或显式 --invective 时输出
    ih, iw = invective(t)
    if ih['点靶'] or inv_force:
        print('\n── 论战结构（v4 · 德性攻击四拍）──')
        stages = ['点靶', '揭梦', '论德', '反转']
        line = ' · '.join(
            f'{k} {"✓" if ih[k] else "—"}' + (f'({len(ih[k])})' if ih[k] else '')
            for k in stages)
        print(f'  {line}')
        for k in stages:
            if ih[k]:
                print(f'   {k}: {"、".join(ih[k][:6])}')
        print(f'   享受物清单: {"、".join(ih["清单"][:8]) if ih["清单"] else "无（可加，越具体越像）"}')
        if iw:
            for w in iw:
                print(f'  ⚠ {w}')
                warns.append(w)
        else:
            print('  OK 四拍齐备（或不在开火语境）。')

    print(f'\n→ 告警项 {len(warns)} 处' + ('  ✅ 整体贴合' if not warns else '  ⚠ 需回修'))
    for w in warns:
        print(f'   · {w}')
    return 0 if not warns else 1

if __name__ == '__main__':
    sys.exit(main())
