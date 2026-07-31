#!/usr/bin/env python3
"""Generate a bilingual (ZH+EN) utterance corpus for bootstrap voice training.

GPT-SoVITS wants 20-30 min of speech; the seed bank in `bootstrap_timbre.py` is
only ~3 min. This fills the gap by expanding slot-filled templates into a few
hundred varied utterances, mixing two kinds of text on purpose:

  * **in-domain** lines in the KOL's actual register (review / haul / GRWM / CTA),
    so the fine-tune learns the prosody the voice will really be used with; and
  * **phonetically-spread** general sentences, so rarer phonemes still appear and
    the voice does not overfit to a narrow product-review cadence.

Output is one utterance per line -- feed straight to `bootstrap_timbre.py --text-file`.

Usage
-----
    python tools/voice_crawl/corpus_builder.py --minutes 30 -o corpus.txt
    python tools/voice_crawl/corpus_builder.py --minutes 25 --ratio-zh 0.6 -o corpus.txt
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path

# Rough synthesis rates measured on edge-tts output at default rate:
# ZH ~4.3 chars/s, EN ~2.9 words/s. Used only to hit --minutes approximately.
ZH_CHARS_PER_SEC = 4.3
EN_WORDS_PER_SEC = 2.9

ZH_TEMPLATES = [
    "這罐{product}我用了{weeks}週，{verdict}，{caveat}。",
    "醜話說前面，{product}我{repurchase}，因為{reason}。",
    "{product}台灣賣{price_tw}，美國是{price_us}，我幫你找到{price_deal}。",
    "你們想看我拿{product}跟{product2}做對比嗎？想要連結留言跟我說一聲。",
    "今天的{scene}，我用的是{product}，質地{texture}，味道{scent}。",
    "有人問我{skin}適不適合{product}，我的建議是{advice}。",
    "說真的，{product}紅到我以為是智商稅，結果{surprise}。",
    "這次團購{product}折到{price_deal}，我自己也補了{count}罐。",
    "早安，今天想跟你們聊聊{topic}，因為最近真的太多人問了。",
    "我{skin}用{product}{weeks}週的心得是：{verdict}，但{caveat}。",
    "如果你在{product}跟{product2}之間猶豫，我會選{choice}，原因很簡單。",
    "謝謝你們的留言，我看到了，{topic}的部分我整理好再跟大家分享。",
    "老實講，{product}的{aspect}表現讓我有點意外，{surprise}。",
    "這支影片沒有業配，{product}是我自己花{price_tw}買的。",
    "提醒一下，{product}用量要抓好，不然{caveat}。",
]

EN_TEMPLATES = [
    "I have been using {product_en} for {weeks} weeks now, and honestly {verdict_en}.",
    "Let me be blunt about {product_en}: I {repurchase_en}, mainly because {reason_en}.",
    "It retails for {price_us} in the States, but I found it for {price_deal}.",
    "Would you like to see me compare {product_en} against {product2_en} side by side?",
    "For today's {scene_en} I am wearing {product_en}, and the texture is {texture_en}.",
    "A lot of you asked whether {product_en} works for {skin_en} skin, so here is my take.",
    "Genuinely, I assumed {product_en} was overhyped, and then {surprise_en}.",
    "This is not a sponsored video; I paid {price_us} for {product_en} myself.",
    "Good morning everyone, today I want to talk about {topic_en} because so many of you asked.",
    "If you are torn between {product_en} and {product2_en}, I would go with the first one.",
    "Quick reminder: use a smaller amount of {product_en}, otherwise {caveat_en}.",
    "Thank you all for the comments, I read every single one of them.",
    "The {aspect_en} on {product_en} genuinely surprised me this month.",
    "Roughly {pct} percent of the messages I got were asking the exact same question.",
    "Before we start, let me quickly show you what came in the package this week.",
]

# Slot fillers chosen for spread across initials/finals (ZH) and vowels (EN).
ZH_SLOTS = {
    "product": ["這罐精華", "那支粉底", "這款防曬", "那瓶化妝水", "這條唇膏", "那盒面膜",
                "這支眉筆", "那罐乳液", "這款洗面乳", "那支睫毛膏", "這瓶香水", "那盒腮紅"],
    "product2": ["另一罐精華", "開架的版本", "貴婦品牌那支", "藥妝店那款", "去年那瓶"],
    "weeks": ["兩", "三", "四", "六", "八", "十"],
    "verdict": ["真的有感", "普普通通", "出乎意料地好", "沒有到很驚豔", "值得回購", "略嫌雞肋"],
    "caveat": ["敏感肌要小心", "夏天可能會悶", "價格偏高", "香味有點重", "需要耐心等效果",
               "用量要抓準", "包裝不太方便"],
    "repurchase": ["不會回購", "一定會回購", "還在考慮要不要回購"],
    "reason": ["質地太厚重", "效果太慢", "性價比很高", "成分很扎實", "味道我不愛"],
    "price_tw": ["八百九", "一千兩百", "兩千五", "六百八", "三千四"],
    "price_us": ["二十九塊美金", "四十五塊美金", "六十八塊美金", "十九塊美金"],
    "price_deal": ["七折", "五九九", "買一送一", "六五折", "現省八百"],
    "scene": ["出門妝", "居家保養", "上班通勤", "約會打扮", "運動之後"],
    "texture": ["清爽好推", "偏厚重", "水感十足", "有點黏膩", "絲滑不黏"],
    "scent": ["淡淡的花香", "幾乎沒有味道", "有點藥味", "清新的柑橘調"],
    "skin": ["油肌", "乾肌", "混合肌", "敏感肌", "痘痘肌"],
    "advice": ["先試用小樣", "白天再用比較安全", "搭配保濕一起", "可以直接入手", "建議先觀望"],
    "surprise": ["真的滿好用的", "完全不適合我", "比想像中溫和", "確實有它的道理"],
    "count": ["兩", "三", "五"],
    "topic": ["換季保養", "底妝挑選", "平價好物", "防曬觀念", "醫美心得", "髮質保養"],
    "choice": ["第一罐", "第二罐", "貴的那支", "平價的那款"],
    "aspect": ["持妝度", "遮瑕力", "保濕感", "延展性", "服貼度"],
}

EN_SLOTS = {
    "product_en": ["this serum", "that foundation", "the sunscreen", "this toner",
                   "that lip balm", "the sheet mask", "this cleanser", "that mascara",
                   "the moisturiser", "this brow pencil", "that highlighter"],
    "product2_en": ["the drugstore version", "the luxury one", "last year's formula",
                    "the refill size", "the travel version"],
    "weeks": ["two", "three", "four", "six", "eight", "twelve"],
    "verdict_en": ["it genuinely works", "it is fairly average", "I was pleasantly surprised",
                   "it did nothing for me", "it is worth repurchasing"],
    "repurchase_en": ["would not buy it again", "will absolutely repurchase",
                      "am still undecided about it"],
    "reason_en": ["the texture is far too heavy", "results took much too long",
                  "the value is excellent", "the ingredient list is solid",
                  "the fragrance bothered me"],
    "price_us": ["twenty nine dollars", "forty five dollars", "sixty eight dollars",
                 "nineteen dollars", "one hundred and ten dollars"],
    "price_deal": ["thirty percent off", "buy one get one free", "just twelve dollars",
                   "half the usual price"],
    "scene_en": ["get ready with me", "morning routine", "office commute",
                 "date night look", "post workout routine"],
    "texture_en": ["light and easy to blend", "quite thick", "extremely watery",
                   "slightly sticky", "silky and never greasy"],
    "skin_en": ["oily", "dry", "combination", "sensitive", "acne prone"],
    "surprise_en": ["it genuinely impressed me", "it broke me out immediately",
                    "it turned out gentler than expected"],
    "topic_en": ["seasonal skincare", "choosing a base", "affordable finds",
                 "sun protection", "hair care"],
    "caveat_en": ["it will pill under makeup", "it feels heavy by midday",
                  "it can sting slightly"],
    "aspect_en": ["longevity", "coverage", "hydration", "blendability"],
    "pct": ["sixty", "seventy five", "ninety", "forty"],
}

# General sentences for phonetic spread beyond the product-review register.
ZH_GENERAL = [
    "昨天下午雷雨特別大，整條街的積水淹到腳踝。",
    "他認為法官不應該用那種語氣質問證人。",
    "清晨六點，公園裡只有幾隻麻雀在跳來跳去。",
    "這本小說的敘事節奏很慢，但結局非常震撼。",
    "全球暖化造成的影響，已經不只是天氣變熱而已。",
    "我搭捷運轉公車，大概要花五十分鐘才會到。",
    "廚房飄出蔥薑蒜爆香的味道，讓人立刻餓了。",
    "統計顯示，超過三分之二的受訪者選擇了第一個方案。",
    "冬天的海邊風很強，走路都要側著身子。",
    "老師說，理解比死背重要得多。",
]
EN_GENERAL = [
    "The thunderstorm yesterday flooded the entire street up to our ankles.",
    "He argued that judges should never question a witness in that tone.",
    "At six in the morning the park held nothing but a few restless sparrows.",
    "The novel moves slowly, but the ending is genuinely devastating.",
    "Global warming affects far more than simply how hot the summer gets.",
    "I take the subway and then a bus, which is roughly fifty minutes.",
    "The smell of garlic and ginger in hot oil made everyone hungry at once.",
    "Statistics showed that over two thirds of respondents chose the first option.",
    "The wind at the winter shore is strong enough to make you walk sideways.",
    "Our teacher insisted that understanding matters far more than memorising.",
]


def est_seconds(line: str) -> float:
    if any("一" <= c <= "鿿" for c in line):
        return max(len(line) / ZH_CHARS_PER_SEC, 1.0)
    return max(len(line.split()) / EN_WORDS_PER_SEC, 1.0)


def expand(templates, slots, rng, n) -> list[str]:
    out, seen, guard = [], set(), 0
    while len(out) < n and guard < n * 60:
        guard += 1
        t = rng.choice(templates)
        line = t
        for key in slots:
            token = "{" + key + "}"
            if token in line:
                line = line.replace(token, rng.choice(slots[key]))
        if "{" in line:  # a slot had no filler -> template/slot mismatch
            continue
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", required=True, help="output corpus path")
    ap.add_argument("--minutes", type=float, default=30.0, help="target spoken minutes")
    ap.add_argument("--ratio-zh", type=float, default=0.5, help="fraction of ZH lines")
    ap.add_argument("--general-ratio", type=float, default=0.2,
                    help="fraction drawn from the general phonetic-spread bank")
    ap.add_argument("--seed", type=int, default=20260730, help="deterministic output")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    target = args.minutes * 60

    # Over-generate, then trim to the duration target.
    zh = expand(ZH_TEMPLATES, ZH_SLOTS, rng, 600)
    en = expand(EN_TEMPLATES, EN_SLOTS, rng, 600)
    # Shuffle (do NOT sample with replacement): identical text synthesizes to
    # byte-identical audio, so a repeated line is a duplicate training clip that
    # merely overweights its phonemes.
    pool_zh = ZH_GENERAL[:]
    pool_en = EN_GENERAL[:]
    rng.shuffle(pool_zh)
    rng.shuffle(pool_en)

    lines, used, total = [], set(), 0.0
    i_zh = i_en = i_gz = i_ge = 0
    while total < target and (i_zh < len(zh) or i_en < len(en)):
        use_general = rng.random() < args.general_ratio
        use_zh = rng.random() < args.ratio_zh
        if use_general and use_zh and i_gz < len(pool_zh):
            line = pool_zh[i_gz]; i_gz += 1
        elif use_general and not use_zh and i_ge < len(pool_en):
            line = pool_en[i_ge]; i_ge += 1
        elif use_zh and i_zh < len(zh):
            line = zh[i_zh]; i_zh += 1
        elif i_en < len(en):
            line = en[i_en]; i_en += 1
        elif i_zh < len(zh):
            line = zh[i_zh]; i_zh += 1
        else:
            break
        if line in used:
            continue
        used.add(line)
        lines.append(line)
        total += est_seconds(line)

    header = [
        f"# Bootstrap corpus - target {args.minutes:.0f} min, seed {args.seed}",
        f"# {len(lines)} utterances, estimated {total/60:.1f} min of speech",
        "# Feed to: bootstrap_timbre.py <kol_id> --voice <v> --text-file <this file>",
    ]
    Path(args.out).write_text("\n".join(header + lines) + "\n", encoding="utf-8")

    n_zh = sum(1 for l in lines if any("一" <= c <= "鿿" for c in l))
    print(f"wrote {args.out}")
    print(f"  {len(lines)} utterances  (~{total/60:.1f} min estimated)")
    print(f"  ZH {n_zh} / EN {len(lines)-n_zh}")
    print(f"  unique: {len(set(lines))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
