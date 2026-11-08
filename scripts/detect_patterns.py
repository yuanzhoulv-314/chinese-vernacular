#!/usr/bin/env python3
"""扫描中文文本里的高频 AI 句式，在稿子旁边产出两个文件。

只做句型匹配，不碰标点、markdown 符号和排版。命中不直接改写，
每条都给上下文、判断依据、建议方向和保留条件，由模型决定改不改。

输出：
  <文件名>_review.md  点评稿，正文每段后面插入点评块，供参考。
  <文件名>_edit.md    原稿的干净副本，供改写，改完即成稿。
原稿不动。
"""

import argparse
import re
import sys
from pathlib import Path

RULES = [
    {
        "id": "A",
        "name": "伪递进与伪升华",
        "items": [
            ("不仅…更/还", r"不仅[^。！？\n]{0,40}?(更|还)",
             "用递进姿态包装两个同级判断。", "留后项，前项降成一句前提。",
             "两部分确实构成递进，后者是前者的结果或升级。"),
            ("不只是…而是", r"不只是[^。！？\n]{0,40}?(而是|更是)",
             "二分否定强调，否定面往往没有信息。", "先判对立是否真实，假对立删前项。",
             "否定面在纠正一个真实误解。"),
            ("值得关注的是", r"(真正|最)?值得(关注|注意)的是|值得一提的是|需要注意的是",
             "评注性引导语，宣称重要而不给理由。", "删引导语，让事实自己说话。",
             "下文确实有一处反直觉的事实，需要提示读者别错过。"),
            ("更重要的是", r"更(重要|关键)的是|最核心的是",
             "用排序词冒充论证，轻重靠位置而不是靠词。", "删掉排序词，轻重交给段落顺序。",
             "前后两项确有主次，且删掉后读者会误判轻重。"),
            ("背后是/本质上", r"背后的?(原因|逻辑|机制)?(是|在于)|本质(上|是)|归根结底",
             "用抽象名词收束，读者拿不到可核对的机制。", "写具体机制，不写“本质”。",
             "原文已有机制说明，这里只是收口。"),
            ("离不开", r"离不开",
             "用依赖关系代替因果说明。", "写清谁在支撑，删掉离不开。",
             "确实是必要条件，删掉会损失判断。"),
            ("体现了/彰显了", r"(体现|彰显|印证|折射)(了|出)",
             "句尾盖章，事实本身已经说明，不需要再评价。", "整句删除，事实不需要盖章。",
             "后接的是具体效果而不是空泛评价。"),
            ("标志着/奠定基础", r"标志着|奠定了[^。！？\n]{0,8}基础",
             "历史定位话术，常用在普通时间点后面。", "换成日期加动作。",
             "确有制度或时间上的节点意义，且有交代。"),
            ("从…到…，从…到…", r"从[^。！？\n]{1,15}到[^。！？\n]{1,15}[，,]\s*从[^。！？\n]{1,15}到",
             "伪跨度，用两个端点假装覆盖了中间。", "点名一个具体跨度，删掉另一组。",
             "两头确有并列的两件事，中间没有省略。"),
            ("提供新思路/开启新篇章", r"提供(了)?新的?(思路|可能|路径)|开启(了)?新(的)?(篇章|阶段)|让[^。！？\n]{1,20}成为可能",
             "评价性收尾，不描述任何可操作的东西。", "写具体可做的动作。",
             "后文确实给出了可操作的具体做法。"),
            ("真正值得X的", r"真正值得[^。！？\n]{0,8}的",
             "先替读者定性，再给内容，典型的评注式起句。", "删掉真正值得，直接写事实。",
             "后文确实要给一个判断，需要先立评价标准。"),
            ("更根本的一层", r"更(根本|深|深层)(的)?(一)?(层|问题|原因)",
             "层层递进的话术，层数由修辞决定而不是由论证决定。", "删掉层级词，直接写这一层说的新东西。",
             "确实分层论述，且每一层都有独立论据。"),
            ("从某种意义上说", r"从某种意义上|在某种程度上|某种程度上",
             "限定词打头，通常后面接的是一般性判断。", "删掉限定，或者写出限定条件。",
             "确有需要限定的边界，且边界写清楚了。"),
            ("并非偶然", r"(并非|绝非)偶然",
             "抒情式断言，原因藏在情绪里。", "给出原因，删掉感叹。",
             "前文已经交代了原因，这里只是收束。"),
        ],
    },
    {
        "id": "B",
        "name": "空转转折与伪对立",
        "items": [
            ("不是…而是", r"不是[^。！？\n]{1,40}?而是",
             "典型的假对比：否定面常被用来抬语气。", "先写A的具体表现，再写B，否定面全篇最多一次。",
             "否定面在纠正一个真实误解，两部分都提供信息。"),
            ("不是…，是…", r"不是[^。！？\n]{1,30}?[，,]\s*(这|那)?是",
             "假对比的省略式，转折关系被压缩成停顿。", "补出真正的转折关系，或者只留后项。",
             "前后确实是同一组对立，且读者需要区分。"),
            ("不在…而在…", r"不(在|是)[^。！？\n]{1,30}?[，,]\s*(而)?在",
             "否定加修正，修正的部分常是套话。", "只保留修正后的判断。",
             "否定面在纠正一个真实误解。"),
            ("与其说…不如说", r"与其说[^。！？\n]{1,40}?不如说",
             "用两层说法覆盖同一个判断。", "只留结论。",
             "两种说法确有差别，且差别对结论有影响。"),
            ("与其…不如…", r"与其[^。！？\n]{1,25}?不如",
             "把建议包装成二选一，另一头通常是稻草人。", "只留建议。",
             "两个选项都是真实存在的选择，且需要对比。"),
            ("真正的问题在于", r"(然而|但|可是)[^。！？\n]{0,10}?真正的?问题",
             "先否定表层解释，再给出真实原因，属于预设转折。", "删转折，直接说问题。",
             "前文确实提出过一个表层解释需要推翻。"),
            ("问题在于/关键在于", r"(问题|关键)在于",
             "把判断包装成发现，读者拿不到依据。", "直接陈述卡点。",
             "后接的是具体可检验的卡点。"),
            ("表面上…实际上", r"表面上[^。！？\n]{1,30}?(实际上|其实)",
             "两层叙述，表层信息常常是编出来的对称。", "只写实际，表层没有用就删。",
             "表层表现确实会被读者看到，需要先破除。"),
            ("看似…实则", r"看似[^。！？\n]{1,30}?(实则|其实|实际上)",
             "同上，且往往一句里塞两个判断。", "拆成两句，或者只留实际的一层。",
             "对照本身是作者要讲的点。"),
            ("一边是…一边是", r"一边是[^。！？\n]{1,30}?一边是",
             "对仗式铺陈，主体被虚化成一边。", "用具体主体替换一边。",
             "两边的对照需要保留对仗节奏，比如标题。"),
        ],
    },
    {
        "id": "C",
        "name": "免责收束与过度对冲",
        "items": [
            ("但也得承认另一面", r"但(也)?(得|要|必须|应)(承认|看到|说明)[^。！？\n]{0,12}(另一面|反面|另一层)",
             "标准的骑墙句式，先立判断再自拆。", "删掉回撤，或者把两面写成两个条件。",
             "任务本身是评估或辩论。"),
            ("否则…站不住", r"否则[^。！？\n]{0,15}(站不住|不成立|说不通)",
             "用自我辩护收束，作者在跟自己辩论。", "删掉这一句，判断本身够不够硬已经写在正文里。",
             "前文确实只有单侧论据，需要提示读者。"),
            ("当然…不一定", r"当然[^。！？\n]{0,25}(也)?不一定",
             "结尾回撤，把前面的断言稀释掉。", "删掉回撤，把适用条件写进前提。",
             "任务本身是评估或风险提示，平衡是职责。"),
            ("因人而异/各有利弊", r"因人而异|各有利弊|见仁见智",
             "万能否定，谁也没得罪，读者什么也没得到。", "选边并给条件。",
             "确实在讨论偏好问题，且已给出判断依据。"),
            ("需要指出的是/客观来说", r"需要指出的是|客观(来|地)说|客观地看",
             "评注性引导语，删掉不影响句意。", "删引导语。",
             "后面接的确实是需要提醒的反常识事实。"),
            ("这不意味着/不等同于", r"这(并)?不意味着|这不等同于|不能单凭|不应将其理解",
             "预防性免责，前面没有对应的误解。", "删掉，除非前文真的埋了会被误读的说法。",
             "前文确有被误读的风险，且澄清有具体对象。"),
            ("谨慎解读/有待研究", r"谨慎解读|有待(进一步)?(研究|验证|观察)",
             "把结论交给未来，等于没下结论。", "删掉，或者写出具体缺口。",
             "缺口是真实的，且写明了缺口在哪。"),
            ("最终还需要验证", r"(最终|仍|还)需要[^。！？\n]{0,15}(验证|检验|核实)",
             "任务不是评估却加验证口，等于自我否定。", "整句删。",
             "任务本身是评估或尽调。"),
            ("一定程度上", r"(一定|某种)程度上",
             "限定词叠在判断前面，通常可删。", "限定词只留一个。",
             "确有程度差异，需要保留分寸。"),
            ("仅供参考/以实际为准", r"仅供参考|以实际(情况)?为准",
             "免责尾注，没有信息量。", "删。",
             "文本是规程、合同或说明书。"),
        ],
    },
    {
        "id": "D",
        "name": "机械序列与路标",
        "items": [
            ("首先…其次", r"首先[^。！？\n]{0,80}?其次",
             "编号式推进，顺序不是内容本身要求的。", "用时间或因果承接，删编号。",
             "确实需要编号交代操作顺序。"),
            ("第一…第二", r"第一[，,、][^。！？\n]{0,60}?第二[，,、]",
             "同上，正文里的序号常常是排版惯性。", "改成分段，段落自己证明顺序。",
             "并列项本身就是清单，读者要靠序号定位。"),
            ("第X层/第X点", r"第[一二三四五六七八九十0-9]{1,3}(层|点|步|条)[，,、]",
             "把论证切成编号块，块与块之间常常只是并列，没有推进。", "改成分段，用关系词承接，删掉编号。",
             "确实是清单或步骤，读者需要靠编号回指。"),
            ("让我们/话不多说", r"让我们|接下来我们|话不多说",
             "路标句，只预告不讲内容。", "删，直接上内容。",
             "真的在引导操作步骤。"),
            ("以下是…需要知道的", r"以下(是|分为)[^。！？\n]{0,15}(需要|值得|你)",
             "同样的路标句变体。", "删，直接给内容。",
             "确有多项并列内容需要总起。"),
            ("在开始之前", r"在开始之前|在此之前[^。！？\n]{0,8}说明",
             "起跑式铺垫。", "删。",
             "确实需要前置条件说明。"),
            ("综上/总而言之", r"综上(所述)?|总而言之|总的来说|一句话总结",
             "总结套话，正文已经说过。", "删，停在最后一条事实。",
             "前文很长且需要收束结论。"),
            ("到这里已经", r"到这里[，,][^。！？\n]{0,12}已经",
             "自我回顾，读者不需要被告知读到哪了。", "删。",
             "文本是教程，需要阶段确认。"),
        ],
    },
    {
        "id": "E",
        "name": "时代背景开场",
        "items": [
            ("随着…发展", r"随着[^。！？\n]{1,25}?(的)?(不断)?(发展|普及|深入|推进)",
             "背景铺垫，信息量为零。", "从一个具体事件或数字起笔。",
             "趋势本身是论点的一部分，后面有数据支撑。"),
            ("在…的今天", r"在[^。！？\n]{1,20}?的(今天|时代)|在这个时代",
             "同上，时间背景被虚化。", "删，或者写具体年份。",
             "时代对比本身就是文章的结构。"),
            ("当今社会/如今已经", r"当今社会|如今[，,][^。！？\n]{0,15}?已经",
             "套话开头。", "换成某年某月发生了什么。",
             "确有时间跨度需要交代。"),
            ("这是一个…的时代", r"这是一个[^。！？\n]{1,15}?的时代",
             "格言式定调。", "删。",
             "文章就是讨论时代特征，且后文有论据。"),
            ("你有没有/你是否", r"你有没有(发现|想过|注意)|你是否曾经",
             "假互动开场。", "改成直接陈述。",
             "确实面向读者提问，且下文就答。"),
        ],
    },
    {
        "id": "F",
        "name": "万能收尾",
        "items": [
            ("未来可期/拭目以待", r"未来可期|拭目以待|值得期待",
             "展望式收尾，不提供新信息。", "删，停在最后一件事实。",
             "确有已公布的计划，且写明时间。"),
            ("让我们共同/携手", r"让我们共同|携手[^。！？\n]{0,10}(共进|前行|创造)",
             "号召式收尾。", "删。",
             "文本是倡议书或公开信。"),
            ("希望对你有所帮助", r"希望[^。！？\n]{0,6}(文章|内容|本文)[^。！？\n]{0,10}(有帮助|有所启发|有所收获)",
             "对话残留，不属于正文。", "删。",
             "文本是书信或回复。"),
            ("总之…是关键", r"总之[，,][^。！？\n]{0,25}?(是|在于)[^。！？\n]{0,12}?(关键|核心)",
             "总结加定性的双重套话。", "删，结论写进正文。",
             "确实需要一句话结论，且前文有分歧要收束。"),
            ("任重道远", r"任重道远|道路还(很)?长|来日方长",
             "官样收尾。", "删。",
             "公文或致辞。"),
            ("以上就是全部内容", r"以上(就)?是[^。！？\n]{0,10}?(全部|所有)内容",
             "告知结束，属于对话残留。", "删。",
             "教程需要明确收束。"),
            ("欢迎留言/点赞关注", r"欢迎留言|你怎么看|点赞关注|点个赞",
             "引流收尾。", "删，除非用户要做互动。",
             "用户明确要做互动运营。"),
        ],
    },
    {
        "id": "G",
        "name": "排比与对偶",
        "items": [
            ("连续的字短语排比", r"[^。！？\n，,]{2,16}的[，,]\s*[^。！？\n，,]{2,16}的[，,]\s*[^。！？\n，,]{2,16}的",
             "三个以上同构的字短语连排，节奏替代了推理。", "砍到两项，或者改成一长一短的散句。",
             "三项各自独立，删掉会缺项。"),
            ("既是…也是/既要…又要", r"既是[^。！？\n]{1,25}?也是|既要[^。！？\n]{1,25}?又要",
             "成对出现，两边都成立时等于没有取舍。", "保留成立的那一边。",
             "两面都成立且都需要交代。"),
            ("没有…没有…没有", r"没有[^。！？\n]{1,15}?[，,]\s*没有[^。！？\n]{1,15}?[，,]\s*没有",
             "否定排比，用节奏替代信息。", "留一项，其余删。",
             "三项各自独立，删掉会缺项。"),
            ("既…又", r"既[^。！？\n]{1,15}?[，,]\s*又",
             "同上，弱化版。", "只留更重要的那一边。",
             "两面都必须保留。"),
            ("自问自答", r"为什么[^。！？\n]{0,20}？[^。！？\n]{0,5}(因为|答案|原因)",
             "设问后立刻自答，答案往往就是常识。", "删问句，只留答。",
             "确实是读者会问的问题，答案反直觉。"),
        ],
    },
    {
        "id": "H",
        "name": "句式壳子与翻译腔",
        "items": [
            ("作为…，", r"作为[^，。\n]{2,18}?，",
             "欧化前置，把身份从句子主干里抽出来。", "删掉作为，直接说身份。",
             "确需先立身份再讲职责。"),
            ("被视为/被认为", r"被(视为|认为|广泛认为|普遍认为)",
             "被动加模糊归因，责任被藏起来。", "写明谁认为，或者删。",
             "施事者确实未知，且不确定性重要。"),
            ("对…进行/作出…", r"对[^。！？\n]{1,15}?进行|作出[^。！？\n]{0,8}?(调整|说明|分析|判断)|加以[^。！？\n]{1,8}",
             "壳子动词，动作被名词化。", "换成实义动词直接带宾语。",
             "文本是公文或规程，需要正式体。"),
            ("在…方面/层面", r"在[^。！？\n]{1,15}?(方面|层面|维度)(上)?",
             "空转的限定，通常可以换成具体环节。", "删，或者写具体环节。",
             "确实在比较不同维度。"),
            ("基于…的", r"基于[^。！？\n]{1,15}?的",
             "介词结构前置，主语被推远。", "写条件和动作。",
             "确实需要交代依据。"),
            ("通过…来/借助…实现", r"通过[^。！？\n]{1,20}?来|借助[^。！？\n]{1,15}?实现",
             "手段句套壳，主谓宾被拆散。", "还原成主谓宾。",
             "手段与目的都需要交代。"),
            ("使得…得以", r"使得[^。！？\n]{1,20}?得以",
             "书面套壳。", "换让。",
             "正式文体。"),
            ("具有…的特征", r"具有[^。！？\n]{1,12}?(的)?(特征|特点)|有[^。！？\n]{1,8}?的必要",
             "名词化判断，等于没说。", "换成直言。",
             "确需描述属性。"),
        ],
    },
    {
        "id": "I",
        "name": "元话语",
        "items": [
            ("本文将/下面我们", r"本文将|本文(主要|旨在)|下面我们(从|就)",
             "自我指涉，读者不需要被告知结构。", "删。",
             "长文需要目录式引导。"),
            ("说到底", r"说到底|归根到底",
             "把结论包装成常识，抹掉论证过程。", "删掉这层壳，直接写结论和它的依据。",
             "前文确实有论证，这里只是收束。"),
            ("正如前面所说", r"正如(前面|上文)(所说|所述)|如前所述",
             "回指，重复已说过的内容。", "删。",
             "确实需要回指前文的某条前提。"),
            ("简单来说/换句话说", r"简单来说|换句话说|也就是说",
             "换词重述，信息重复。", "全篇留一次，其余删。",
             "换一种说法确有帮助。"),
            ("有人可能会说", r"有人可能会说|你可能会问|你或许会问",
             "预设反驳，用来给自己铺台阶。", "删，除非真在回应异议。",
             "确有读者异议需要正面处理。"),
            ("顺便提一句", r"顺便(提一句|说一句)|多说一句",
             "插入性闲聊，属于对话残留。", "删。",
             "文本是书信或随笔。"),
        ],
    },
]

IGNORED_LINE = re.compile(r"^\s*>")
FENCE = re.compile(r"^```")
FRONTMATTER = re.compile(r"\A---\s*\n.*?\n---\s*$", re.S | re.M)


def mask_ignored(text):
    """把忽略区域替换成等长空白，保持行号和偏移不变。"""
    lines = text.split("\n")
    out = []
    in_fence = False
    started = False
    for i, line in enumerate(lines):
        if i == 0 and line.strip() == "---":
            started = True
            out.append(" " * len(line))
            continue
        if started:
            if line.strip() == "---":
                started = False
            out.append(" " * len(line))
            continue
        if FENCE.match(line.strip()):
            in_fence = not in_fence
            out.append(" " * len(line))
            continue
        if in_fence or IGNORED_LINE.match(line):
            out.append(" " * len(line))
            continue
        out.append(line)
    masked = "\n".join(out)
    # 行内代码
    masked = re.sub(r"`[^`\n]*`", lambda m: " " * len(m.group(0)), masked)
    return masked


def line_no(text, pos):
    return text.count("\n", 0, pos) + 1


def snippet(text, start, end, pad=40):
    a = max(0, start - pad)
    b = min(len(text), end + pad)
    piece = text[a:b].replace("\n", " ").strip()
    piece = re.sub(r"\s+", " ", piece)
    return ("…" if a > 0 else "") + piece + ("…" if b < len(text) else "")


def scan(text):
    masked = mask_ignored(text)
    found = []
    for rule in RULES:
        for label, pat, why, fix, keep in rule["items"]:
            for m in re.finditer(pat, masked):
                found.append({
                    "class_id": rule["id"],
                    "class_name": rule["name"],
                    "label": label,
                    "start": m.start(),
                    "end": m.end(),
                    "hit": text[m.start():m.end()],
                    "why": why,
                    "fix": fix,
                    "keep": keep,
                })
    found.sort(key=lambda x: (x["start"], -(x["end"] - x["start"])))
    kept = []
    for item in found:
        overlap = False
        for k in kept:
            lo = max(item["start"], k["start"])
            hi = min(item["end"], k["end"])
            if hi <= lo:
                continue
            shorter = min(item["end"] - item["start"], k["end"] - k["start"])
            if (hi - lo) > 0.5 * shorter:
                overlap = True
                break
        if not overlap:
            kept.append(item)
    return kept


def build_report(path, text, hits, min_hits):
    by_class = {}
    for h in hits:
        by_class.setdefault(h["class_id"], []).append(h)

    reported = {k: v for k, v in by_class.items() if len(v) >= min_hits}
    dropped = {k: v for k, v in by_class.items() if len(v) < min_hits}
    names = {r["id"]: r["name"] for r in RULES}

    lines = []
    lines.append("# 句式扫描报告")
    lines.append("")
    lines.append("| 项目 | 值 |")
    lines.append("| --- | --- |")
    lines.append(f"| 文件 | {path} |")
    lines.append(f"| 字数 | {len(text)} |")
    lines.append(f"| 规则 | {len(RULES)} 类 {sum(len(r['items']) for r in RULES)} 条 |")
    lines.append(f"| 报出阈值 | 同类命中 {min_hits} 次及以上 |")
    lines.append("")
    lines.append("命中只说明可疑，不构成改写指令。每条都由模型按判断依据和保留条件自行裁决。")
    lines.append("")

    lines.append("## 命中统计")
    lines.append("")
    lines.append("| 类别 | 命中数 | 处理 |")
    lines.append("| --- | --- | --- |")
    for rid in sorted(by_class):
        n = len(by_class[rid])
        lines.append(f"| {rid} {names[rid]} | {n} | {'报出' if n >= min_hits else '压掉'} |")
    lines.append("")

    if reported:
        lines.append("## 命中明细")
        lines.append("")
        for rid in sorted(reported):
            hits_c = sorted(reported[rid], key=lambda x: x["start"])
            lines.append(f"### {rid} {names[rid]}（{len(hits_c)} 处）")
            lines.append("")
            for idx, h in enumerate(hits_c, 1):
                ln = line_no(text, h["start"])
                lines.append(f"**{rid}-{idx:02d} 第 {ln} 行 · {h['label']}**")
                lines.append("")
                lines.append(f"- 命中：{h['hit']}")
                lines.append(f"- 上下文：{snippet(text, h['start'], h['end'])}")
                lines.append(f"- 可疑点：{h['why']}")
                lines.append(f"- 建议方向：{h['fix']}")
                lines.append(f"- 保留条件：{h['keep']}")
                lines.append("")
    else:
        lines.append("## 命中明细")
        lines.append("")
        lines.append("没有类别达到报出阈值。")
        lines.append("")

    if dropped:
        lines.append("## 压掉的单次命中")
        lines.append("")
        lines.append("| 类别 | 命中数 | 位置 |")
        lines.append("| --- | --- | --- |")
        for rid in sorted(dropped):
            locs = "、".join(str(line_no(text, h["start"])) for h in dropped[rid])
            lines.append(f"| {rid} {names[rid]} | {len(dropped[rid])} | 第 {locs} 行 |")
        lines.append("")
        lines.append("这些位置同类只出现一次，按频次规则不进入明细。模型读到具体段落时自行判断。")
        lines.append("")

    return "\n".join(lines)


def paragraph_spans(text):
    spans = []
    pos = 0
    for part in text.split("\n\n"):
        spans.append((pos, pos + len(part), part))
        pos += len(part) + 2
    return spans


def hit_with_context(text, hit, lo, hi, pad=5):
    """命中片段前后各带几个字，上下文不跨段。"""
    a = max(lo, hit["start"] - pad)
    b = min(hi, hit["end"] + pad)
    left = re.sub(r"\s+", " ", text[a:hit["start"]])
    body = re.sub(r"\s+", " ", text[hit["start"]:hit["end"]])
    right = re.sub(r"\s+", " ", text[hit["end"]:b])
    piece = ("…" if a > lo else "") + left + body + right + ("…" if b < hi else "")
    return re.sub(r"\*\*|`", "", piece)


def annotate(text, hits, min_hits):
    """把点评块插进原文，生成点评稿。"""
    by_class = {}
    for h in hits:
        by_class.setdefault(h["class_id"], []).append(h)
    reported = {rid for rid, v in by_class.items() if len(v) >= min_hits}

    blocks = []
    for start, end, para in paragraph_spans(text):
        seg = [para]
        inside = [h for h in hits
                  if h["class_id"] in reported and start <= h["start"] < end]
        for h in sorted(inside, key=lambda x: x["start"]):
            seg.append("")
            seg.append(f"> 【AI句式：{h['class_name']}】{h['label']}")
            seg.append(f"> 命中：{hit_with_context(text, h, start, end)}")
            seg.append(f"> 可疑点：{h['why']}")
            seg.append(f"> 建议方向：{h['fix']}")
            seg.append(f"> 保留条件：{h['keep']}")
        blocks.append("\n".join(seg))

    header = ("<!-- 本文件由 detect_patterns.py 生成。正文中以 > 【AI句式 开头的块是点评，"
              "不是要保留的内容或修改对象。改写时以同原稿为准核对事实。 -->")
    return header + "\n\n" + "\n\n".join(blocks).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description="给中文稿子加 AI 句式点评，生成点评稿与待改副本")
    parser.add_argument("file", type=Path, help="待扫描的 .md 或 .txt")
    parser.add_argument("--min-hits", type=int, default=2, help="同类命中达到几次才报，默认 2")
    parser.add_argument("--out", type=Path, help="点评稿路径，默认同目录下 <文件名>_review.md")
    parser.add_argument("--report", action="store_true", help="另外把 Markdown 报告打印到终端")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    text = args.file.read_text(encoding="utf-8")
    hits = scan(text)

    stem = args.file.stem
    review = args.out or args.file.with_name(f"{stem}_review.md")
    review.write_text(annotate(text, hits, args.min_hits), encoding="utf-8")

    edit = args.file.with_name(f"{stem}_edit.md")
    if edit.exists() and edit.read_text(encoding="utf-8") != text:
        print(f"待改副本已存在且已被改动，跳过覆盖：{edit}")
    else:
        edit.write_text(text, encoding="utf-8")

    by_class = {}
    for h in hits:
        by_class.setdefault(h["class_id"], []).append(h)
    shown = {k: len(v) for k, v in by_class.items() if len(v) >= args.min_hits}
    hidden = sum(len(v) for k, v in by_class.items() if len(v) < args.min_hits)
    print(f"点评稿 {review}，待改副本 {edit}：报出 {len(shown)} 类 {sum(shown.values())} 处，压掉 {hidden} 处")

    if args.report:
        print()
        print(build_report(str(args.file), text, hits, args.min_hits))


if __name__ == "__main__":
    main()
