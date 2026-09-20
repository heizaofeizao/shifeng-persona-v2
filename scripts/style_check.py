# -*- coding: utf-8 -*-
"""style_check.py — 文风指纹闸门（P6 · v5）

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

【v5 新增 · L2b 欧式长句 + L2c 反口语化】2026-09-20 用户诊断：「还是缺乏欧式长句」「过于口语化」。
四篇定稿实测坐实：长复句率 14~20%（达标）但**关联配套/的定语链/分号长复句 全为 0**——
句子是靠「逗号串短分句」撑长的，不是靠「关联词嵌套 + 长定语 + 名词化」撑长的。**长度够 ≠ 肌理对。**
L2b 因此以**下限**为主（欠界即告警，溢界上限放宽到 p90×1.5~2，宁可略过他不要欠他）；
L2c 硬禁句式**逐条回语料核验**（篇占比 ≤0.2%），句尾语气词只禁 呗啦哦哟咯嗯呀（合计仅 23 次/24302 句），
**呢(585)/吗(531)/吧(107)/啊(69)/嘛(48) 一律放行**——禁错等于把他最像的地方改掉。详见 modules/style-euro.md。

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
# ── L2b 欧式长句层（v5 新增）：{指标: (下线, 上线)} ──
#    **这一层与 L2 相反：L2 查"句子够不够长"，L2b 查"句子书面性够不够"。**
#    2026-09-20 立：实测四篇定稿「长复句率达标但关联配套/的链/分号全为 0」——
#    长度靠逗号串短分句撑起来的，句法血统不对。基线 mid 为 p50，上线放宽到 p90×1.5~2。
#    详见 modules/style-euro.md。
EURO_BASE = {
    'short': {'长复句率': (5, 70), '关联配套': (0.3, 9.0), '的定语链': (0.3, 9.0),
              '名词化': (0.4, 9.0)},
    'mid':   {'长复句率': (12, 55), '关联配套': (1.0, 6.0), '的定语链': (0.6, 6.0),
              '名词化': (0.8, 6.0)},
    'pin':   {'长复句率': (6, 70), '关联配套': (0.4, 9.0), '的定语链': (0.3, 9.0),
              '名词化': (0.4, 9.0)},
    'long':  {'长复句率': (20, 60), '关联配套': (1.4, 5.0), '的定语链': (0.8, 5.0),
              '名词化': (1.0, 5.0)},
}
RE_EU_LINK = re.compile(
    r'(?:虽然[^。！？\n]{0,60}?[但然]|因为[^。！？\n]{0,60}?所以|尽管[^。！？\n]{0,50}?[但却仍]|'
    r'如果[^。！？\n]{0,50}?[那么就便]|不仅[^。！？\n]{0,50}?[而且还也]|之所以[^。！？\n]{0,50}?是因为|'
    r'无论[^。！？\n]{0,40}?都|即使[^。！？\n]{0,40}?也|当[^。！？\n]{0,30}?[时际]|'
    r'既然[^。！？\n]{0,50}?[那么就]|只要[^。！？\n]{0,50}?就|只有[^。！？\n]{0,50}?才|'
    r'一旦[^。！？\n]{0,40}?就|不是[^。！？\n]{0,40}?而是|并非[^。！？\n]{0,40}?而是|'
    r'既[^。！？\n]{0,30}?又)')
RE_EU_CHAIN = re.compile(r'[^，。！？；：\n]{0,18}的[^，。！？；：\n]{1,18}的[^，。！？；：\n]{1,18}的')
# 名词化用**白名单**而非「…性/…化」通配——通配会把「文化」「变化」判成名词化（实测误报）。
EU_NOM_WORDS = ['可能性', '必要性', '重要性', '复杂性', '正当性', '合理性', '有效性', '必然性',
                '不可复制性', '现代性', '世俗性', '合法性', '整体性', '连续性', '脆弱性', '荒谬性',
                '诚实性', '同质性', '异质性', '排他性', '自发性', '制度化', '原子化', '世俗化',
                '理性化', '机械化', '工业化', '专业化', '碎片化', '边缘化', '科层化', '商品化',
                '庸俗化', '同质化', '均质化']
RE_EU_NOM = re.compile(
    r'(?:对[^。！？\n]{0,25}?的(?:批判|分析|理解|讨论|研究|反思|认识|态度|判断|评价|想象|'
    r'需求|要求|解释|界定|坚持|重视|认同|拒斥|约束|推崇)|' + '|'.join(EU_NOM_WORDS) + r')')
RE_EU_SEMI = re.compile(r'；[^。！？\n]{25,}?。')

# ── L2c 反口语化层（v5 新增）──
#    硬禁表：**每条均已回语料核验，篇占比 ≤0.2%（全语料最多 2 篇）**。
#    ⚠ 教训同 UNWANTED：加词前先 grep 语料，否则会把他说过的话判成错。
#  ⚠ 分组条目会掩盖单词语料频次（守卫按「每条 ≤0.5% 篇占比」校验，分组必然超标），
#    故**一律拆成单词条**，便于逐条审计。
COLLOQ_BAN = [
    (r'你去[^。！？\n]{0,20}?就(?:明白|知道|懂)', '第二人称命令式讲解「你去…就明白」0篇'),
    (r'哪门子', '口语反诘「哪门子」0篇'),
    (r'想都别想', '口语「想都别想」0篇'),
    (r'组合拳', '网络成语「组合拳」0篇'),
    (r'打下来', '网络成语「打下来」0篇'),
    (r'摊上', '口语「摊上」0篇（他写遭遇/面临）'),
    (r'反正吧', '口语软垫「反正吧」0篇'),
    (r'背锅', '网络词「背锅」0篇'),
    (r'干货', '网络词「干货」0篇'),
    (r'那不就', '口语反问「那不就」0篇'),
    (r'这会儿', '北方口语「这会儿」0篇'),
    (r'大伙', '北方口语「大伙」0篇'),
    (r'老实说', '口语垫词「老实说」0篇'),
    (r'怎么着', '北方口语「怎么着」1篇'),
    (r'甭', '北方口语「甭」1篇'),
    (r'拉倒', '北方口语「拉倒」1篇'),
    (r'甩锅', '网络词「甩锅」1篇'),
    (r'硬核', '网络词「硬核」1篇'),
    (r'得了呗', '口语收尾「得了呗」1篇'),
    (r'得了吧', '口语收尾「得了吧」1篇'),
    (r'我觉得吧', '口语垫词「我觉得吧」1篇'),
    (r'事儿', '北方口语「事儿」2篇'),
    (r'干嘛', '口语垫词「干嘛」2篇'),
    (r'这不就', '口语反问「这不就」2篇'),
    (r'玩意儿', '北方口语「玩意儿」3篇'),
    (r'咋', '北方口语「咋」3篇'),
]
COLLOQ_BAN_MAXRATE = 0.005   # 守卫阈值：每条的语料篇占比不得超过 0.5%
# 句尾语气词：**只禁他近乎不用的**。呢(585次)是他的签名尾巴，吗/吧/啊/嘛 亦在用，一律允许。
COLLOQ_TAIL_BAN = re.compile(r'[呗啦哦哟咯嗯呀][。！？]')
# 密度型（他在用但低频）：每组每篇 ≤1 处
COLLOQ_DOSE = {
    '网络靶子词(破防/emo/躺平/内卷)': (r'破防|emo|躺平|内卷', 1),
    '垫词(说白了/说穿了)': (r'说白了|说穿了', 1),
    '口语动词(折腾/搞得/弄得)': (r'折腾|搞得|弄得', 1),
    '第二人称起句(你看/你想/你说)': (r'(?:^|。|？|！|；)\s*(?:你看|你想|你说)', 1),
    '对举(一边…一边)': (r'一边[^。！？\n]{0,25}?一边', 1),
}
# 口语词总密度上限（mid 基线 p90=3.60/千字）
COLLOQ_WORDS = ['说白了', '其实吧', '就是说', '咋', '怎么着', '玩意', '事儿', '那会儿', '这会儿',
                '大伙', '咱', '甭', '得了吧', '拉倒', '是吧', '对吧', '你觉得', '超级', '什么的',
                '说实话', '老实说', '我觉得吧', '干嘛', '搞不好', '一大堆']
COLLOQ_CAP = {'short': 5.7, 'mid': 3.6, 'pin': 4.5, 'long': 1.7}

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
# ── 互联网黑话：**必须逐词回语料验证**（2026-09-20 修）──
# 原表 8 词里 4 个是误报：赋能 2 篇 / 闭环 2 篇 / 破局 1 篇 / 生态位 10 篇
# ——他自己就写「民族保守主义的生态位」「逻辑闭环」「AI 赋能产业」，命中即误伤。
# 教训：黑名单是「他没说过」的断言，加词前先 grep 语料，否则闸门会把你骗去改本来对的地方。
UNWANTED = ['抓手', '底层逻辑', '认知升级', '颗粒度']
# ── v3 结尾闸门词表 ──
END_SUMM = ['总而言之', '总之', '综上', '说到底', '归根结底', '这才是', '方为正道',
            '才是正道', '共勉', '让我们', '愿我们', '我们应该', '所以我们要',
            '因此我们', '值得铭记', '最后的结论']
END_IMPER = ['不要', '别忘', '应该', '该当', '不妨', '请记住', '务必', '切莫',
             '何乐而不为', '不可不', '不如']
# ── v4 论战结构：德性攻击四拍（detail 见 modules/style-invective.md）──
INV_TARGET = ['目田', '白左', '进步人', '进步壬', '社民进步', '进步教徒', '自由派',
              '辉格派', '城市小资', '体面中产', '公众号写手', '费拉', '赢学', '入关学',
              # 2026-09-20 补：以下均为语料实测在用的靶子说法（大V 8篇 / 中产 53篇 /
              # 公众号 22篇 / 体面人 5篇 / 博主 3篇），原表只收长尾词、漏掉高频词。
              '大V', '大v', '博主', '公众号', '中产', '体面人']
INV_DREAM = ['沉浸在', '岁月静好', '幻象', '幻梦', '美梦', '做梦', '眷恋', '虔诚地相信',
             '地球村', '黄金时代', '旧梦', '朦胧幻想', '自我感动']
INV_VIRTUE = ['德性', '德行', '美德', '德不配位', '不事生产', '空无一物', '摆设的道德',
              '自知之明', '体面感', '庸俗', '堕落', '奴隶的美德']
INV_REVERSE = ['寄生虫', '贵族幻象', '错觉', '于是以为', '自以为', '实则', '其实是在',
               '拆毁', '维系下去', '进步之神', '糟蹋', '坐吃山空',
               # 2026-09-20 补：语料实测 11 篇
               '守夜人']
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


def euro(t):
    """L2b 欧式长句：返回 {指标: 值}。长复句率为 %，其余为千字密度。"""
    N = max(len(t), 1)
    d = {}
    d['长复句率'] = sum(1 for s in grammar_split(t) if len(s) > 60) / max(len(grammar_split(t)), 1) * 100
    d['关联配套'] = len(RE_EU_LINK.findall(t)) / N * 1000
    d['的定语链'] = len(RE_EU_CHAIN.findall(t)) / N * 1000
    d['名词化'] = len(RE_EU_NOM.findall(t)) / N * 1000
    d['_分号长复句'] = len(RE_EU_SEMI.findall(t))
    d['_配套例'] = [m.group()[:34] for m in RE_EU_LINK.finditer(t)][:4]
    d['_链例'] = [m.group()[:34] for m in RE_EU_CHAIN.finditer(t)][:3]
    return d


def colloquial(t):
    """L2c 反口语化：返回 (硬禁命中list, 超剂量list, 语气词list, 总密度, 密度上限)。"""
    hard = []
    for pat, why in COLLOQ_BAN:
        hit = re.findall(pat, t)
        if hit:
            hard.append(f'{hit[0]}（{why}）')
    over = []
    for nm, (pat, lim) in COLLOQ_DOSE.items():
        n = len(re.findall(pat, t))
        if n > lim:
            over.append(f'{nm} 出现 {n} 次（每篇 ≤{lim}）')
    tail = COLLOQ_TAIL_BAN.findall(t)
    dens = sum(t.count(w) for w in COLLOQ_WORDS) / max(len(t), 1) * 1000
    return hard, over, tail, dens


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
    print(f'## 文风指纹比对 v5  （样本 {len(t)} 字 · {tag}）\n')
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

    print('\n── L2b 欧式长句层（v5 · 下限为主：他文风里最容易欠的一维）──')
    eb = EURO_BASE.get(profile, EURO_BASE['short'])
    eu = euro(t)
    print(f'{"指标":<10}{"实测":>9}{"基线(下~上)":>16}  判定')
    for name, (lo, hi) in eb.items():
        v = eu[name]
        # 密度上限对短文本会失真：450 字里 3 处配套 = 6.7/千字，但 3 处本身完全正常。
        # 故给密度型指标一个「最少允许 3 处」的折算下限，避免拿密度尺误伤短中篇。
        eff_hi = hi if name == '长复句率' else max(hi, 3.0 * 1000 / max(len(t), 1))
        ok = 'OK' if lo <= v <= eff_hi else ('低 ⚠' if v < lo else '高 ⚠')
        if '⚠' in ok:
            side = '欠' if v < lo else '溢'
            warns.append(f'L2b {name} {v:.2f} {side}界({lo}~{eff_hi:.2f})')
        unit = '%' if name == '长复句率' else ''
        print(f'{name:<10}{v:>8.1f}{unit:<1}{f"{lo}~{eff_hi:.1f}":>16}  {ok}')
    semi = eu['_分号长复句']
    sok = semi >= 1
    print(f'{"分号长复句":<10}{semi:>8d} 处{"≥1":>15}  {"OK" if sok else "低 ⚠"}')
    if not sok:
        warns.append('L2b 分号长复句 0 处（应 ≥1——两个平行长分句用「；」对举，勿用句号剁开）')
    if eu['_配套例']:
        print(f'   配套例：{" ／ ".join(eu["_配套例"][:3])}')
    if eu['_链例']:
        print(f'   的链例：{" ／ ".join(eu["_链例"][:3])}')
    if eu['关联配套'] < eb['关联配套'][0] or eu['的定语链'] < eb['的定语链'][0]:
        print('   ↳ 补法见 modules/style-euro.md §二：前件显式写关联词（无论/尽管/不仅…也）；')
        print('     抽象名词前挂「对…的」定语层。**长度够≠肌理对**：逗号串短分句撑长的不算。')

    print('\n── L2c 反口语化层（v5）──')
    hard, over, tail, dens = colloquial(t)
    cap = COLLOQ_CAP.get(profile, 3.6)
    if hard:
        for h in hard:
            print(f'  ⚠ 硬禁句式：{h}——语料篇占比 ≤0.2%，他不这么写')
            warns.append(f'L2c 硬禁 {h.split("（")[0]}')
    if tail:
        print(f'  ⚠ 句尾语气词：{"、".join(tail)}——他只用语料级签名尾巴 呢/吗/吧/啊/嘛；'
              f'呗啦哦哟咯嗯呀 合计仅 23 次/24302 句 ≈ 0')
        warns.append(f'L2c 句尾语气词 {"/".join(tail)}')
    if over:
        for o in over:
            print(f'  ⚠ 超剂量：{o}')
            warns.append(f'L2c 超剂量 {o.split(" 出现")[0]}')
    dok = dens <= cap
    print(f'口语词总密度：{dens:.2f}/千字  {"OK" if dok else "高 ⚠"}（上限 {cap} = 该层 p90）')
    if not dok:
        warns.append(f'L2c 口语密度 {dens:.2f}>{cap}')
    if not (hard or tail or over) and dok:
        print('  OK 无口语化破功。')

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

    # v3 讲解冒号详情（**只在越界时才报警**：mid/long 基线本就允许 3~4/千字，
    #   早期版本在档内也打 ⚠，与"告警项 0 处"自相矛盾）
    if m['_colons'] and m['讲解冒号'] > pb['讲解冒号'][1]:
        print(f'\n⚠ 讲解冒号 {len(m["_colons"])} 处 / {m["讲解冒号"]:.1f}千字'
              f'（本档上限 {pb["讲解冒号"][1]}）——改写为逗号断句或直接另起一句：')
        for c in m['_colons'][:6]:
            print(f'   · …{c}…')
    elif m['_colons']:
        print(f'\n· 讲解冒号 {len(m["_colons"])} 处（{m["讲解冒号"]:.1f}/千字，本档允许 '
              f'0~{pb["讲解冒号"][1]}）')

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
        elif not ih['点靶']:
            print('  · 未命中靶子词 → 本篇不判为开火语境（若确在开火，靶子说法可能不在词表内）。')
        else:
            core = [k for k in ('论德', '反转') if ih[k]]
            if len(core) == 2:
                print('  OK 骨架拍齐备（第3「论德」+第4「反转」为必须，第1/2拍可缺）。')
            else:
                print(f'  · 骨架拍仅 {len(core)}/2，建议补齐「论德」+「反转」。')
            print('  · 词表为**词形匹配**，标「—」的拍不代表内容缺失，须人工复核。')

    print(f'\n→ 告警项 {len(warns)} 处' + ('  ✅ 整体贴合' if not warns else '  ⚠ 需回修'))
    for w in warns:
        print(f'   · {w}')
    return 0 if not warns else 1

if __name__ == '__main__':
    sys.exit(main())
