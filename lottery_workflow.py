# -*- coding: utf-8 -*-
"""一键生成本期预测工作流。

流程：自动拉取官方历史数据 -> 更新数据与配置 -> 重新统计 -> 生成 Word/PDF
报告 -> 输出本期预测和 60% 覆盖计划。
"""

import json
import argparse
import itertools
import math
import os
import random
import statistics
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path


BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
CONFIG_PATH = BASE / "config.json"
RESULT_PATH = BASE / "analysis_results.json"
MODEL_STATE_PATH = BASE / "model_state.json"
PREDICTION_LOG_PATH = BASE / "prediction_log.json"

DLT_URL = (
    "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
    "?gameNo=85&provinceId=0&pageSize=100&isVerify=1&pageNo={page}"
)
SSQ_URL = (
    "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
    "?name=ssq&issueCount=600&issueStart=&issueEnd=&dayStart=&dayEnd="
)
DLT_REFERER = "https://www.lottery.gov.cn/kj/kjlb.html?dlt"
SSQ_REFERER = "https://www.cwl.gov.cn/ygkj/wqkjgg/ssq/"
WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
SIM_SEED = 20260807


def load_json_file(path, default=None):
    if not path.exists():
        return default if default is not None else {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


DEFAULT_MODEL_STATE = {
    "weights": {"bayes": 0.35, "hot": 0.25, "cold": 0.20, "trend": 0.20},
    "position_boost": 0.20,
    "pool_size": {"dlt_front": 14, "ssq_red": 16},
    "layer3_size": {"dlt": 9, "ssq": 9},
}


def load_model_state():
    state = load_json_file(MODEL_STATE_PATH)
    merged = json.loads(json.dumps(DEFAULT_MODEL_STATE))
    for key, value in DEFAULT_MODEL_STATE.items():
        if key in state:
            merged[key] = state[key]
    return merged


def save_model_state(state):
    save_json_file(MODEL_STATE_PATH, state)


def fetch_json(url, referer):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Referer": referer,
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    cmd = [
        "curl",
        "-s",
        "-L",
        "-A",
        headers["User-Agent"],
        "-H",
        "Referer: " + referer,
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=90)
    if proc.returncode == 0:
        try:
            return json.loads(proc.stdout)
        except Exception:
            pass
    if os.name == "nt":
        raise RuntimeError(proc.stderr or "网络请求失败")
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        raise RuntimeError(proc.stderr or "网络请求失败")


def fetch_dlt_history(limit=500):
    rows = []
    page = 1
    while len(rows) < limit:
        data = fetch_json(DLT_URL.format(page=page), DLT_REFERER)
        value = data.get("value") or {}
        items = value.get("list") or []
        if not items:
            break
        for item in items:
            nums = (item.get("lotteryDrawResult") or "").split()
            if len(nums) < 7:
                continue
            front = sorted(int(x) for x in nums[:5])
            back = sorted(int(x) for x in nums[5:7])
            rows.append(
                {
                    "issue": item["lotteryDrawNum"],
                    "date": item["lotteryDrawTime"],
                    "front": front,
                    "back": back,
                }
            )
        if len(items) < 100:
            break
        page += 1
    return rows[:limit]


def fetch_ssq_history(limit=500):
    data = fetch_json(SSQ_URL, SSQ_REFERER)
    rows = []
    for item in data.get("result") or []:
        red = sorted(int(x) for x in (item.get("red") or "").split(","))
        blue = int(item.get("blue") or 0)
        rows.append(
            {
                "issue": item["code"],
                "date": item["date"],
                "red": red,
                "blue": blue,
            }
        )
    return rows[:limit]


def load_rows(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def save_rows(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def merge_rows(new_rows, old_rows, key, limit=500):
    merged = {r[key]: r for r in new_rows}
    for r in old_rows:
        merged.setdefault(r[key], r)
    ordered = sorted(merged.values(), key=lambda r: int(r[key]), reverse=True)
    return ordered[:limit]


def fmt_dlt_result(row):
    front = " ".join(f"{x:02d}" for x in row["front"])
    back = " ".join(f"{x:02d}" for x in row["back"])
    return f"{front} + {back}"


def fmt_ssq_result(row):
    red = " ".join(f"{x:02d}" for x in row["red"])
    return f"{red} + {row['blue']:02d}"


def build_schedule(latest_row, game):
    days = {"dlt": [0, 2, 5], "ssq": [1, 3, 6]}[game]
    cur = datetime.strptime(latest_row["date"][:10], "%Y-%m-%d") + timedelta(days=1)
    issue_num = int(latest_row["issue"]) + 1
    items = []
    while len(items) < 1:
        if cur.weekday() in days:
            issue = f"{issue_num:05d}" if game == "dlt" else str(issue_num)
            items.append({"issue": issue, "date": f"{cur:%Y-%m-%d}（{WEEKDAY_CN[cur.weekday()]}）"})
            issue_num += 1
        cur += timedelta(days=1)
    return items


def update_data_and_config():
    print("==> 拉取官方大乐透历史数据")
    dlt_new = fetch_dlt_history(500)
    print("==> 拉取官方双色球历史数据")
    ssq_new = fetch_ssq_history(500)

    dlt_path = DATA_DIR / "dlt_history_500.json"
    ssq_path = DATA_DIR / "ssq_history_500.json"
    dlt_rows = merge_rows(dlt_new, load_rows(dlt_path), "issue")
    ssq_rows = merge_rows(ssq_new, load_rows(ssq_path), "issue")
    save_rows(dlt_path, dlt_rows)
    save_rows(ssq_path, ssq_rows)

    dlt_latest = dlt_rows[0]
    ssq_latest = ssq_rows[0]
    dlt_schedule = build_schedule(dlt_latest, "dlt")
    ssq_schedule = build_schedule(ssq_latest, "ssq")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    config = {
        "generated_at": now + " CST",
        "data_window": f"最近500期官方开奖数据（截至 {now[:10]}）",
        "dlt_latest": {
            "issue": dlt_latest["issue"],
            "date": dlt_latest["date"],
            "result": fmt_dlt_result(dlt_latest),
        },
        "ssq_latest": {
            "issue": ssq_latest["issue"],
            "date": ssq_latest["date"],
            "result": fmt_ssq_result(ssq_latest),
        },
        "dlt_future": [s["issue"] for s in dlt_schedule],
        "ssq_future": [s["issue"] for s in ssq_schedule],
        "dlt_schedule": dlt_schedule,
        "ssq_schedule": ssq_schedule,
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print("最新大乐透：", config["dlt_latest"]["issue"], config["dlt_latest"]["result"])
    print("最新双色球：", config["ssq_latest"]["issue"], config["ssq_latest"]["result"])
    print("大乐透下一期：", config["dlt_future"][0])
    print("双色球下一期：", config["ssq_future"][0])
    return config


def run_analysis_and_report():
    print("==> 运行统计分析与生成报告")
    import build_delivery

    build_delivery.main()


def comb(n, k):
    return math.comb(n, k) if 0 <= k <= n else 0


def hyp(N, K, n, x):
    return comb(K, x) * comb(N - K, n - x) / comb(N, n)


def single_any_prize():
    fp = [hyp(35, 5, 5, x) for x in range(6)]
    bp = [hyp(12, 2, 2, y) for y in range(3)]
    dlt_p = sum(
        fp[f] * bp[b]
        for f in range(6)
        for b in range(3)
        if dlt_win(f, b)
    )
    rp = [hyp(33, 6, 6, x) for x in range(7)]
    ssq_p = sum(
        rp[r] * (1 / 16 if blue else 15 / 16)
        for r in range(7)
        for blue in (0, 1)
        if ssq_win(r, blue)
    )
    return dlt_p, ssq_p


def dlt_win(fh, bh):
    return (
        (fh == 5 and bh == 2)
        or (fh == 5 and bh == 1)
        or (fh == 5 and bh == 0)
        or (fh == 4 and bh == 2)
        or (fh == 4 and bh == 1)
        or (fh == 3 and bh == 2)
        or (fh == 4 and bh == 0)
        or (fh == 3 and bh == 1)
        or (fh == 2 and bh == 2)
        or (fh == 3 and bh == 0)
        or (fh == 1 and bh == 2)
        or (fh == 2 and bh == 1)
        or (fh == 0 and bh == 2)
    )


def ssq_win(rh, bh):
    return (
        rh == 6
        or rh == 5
        or rh == 4
        or (rh == 3 and bh)
        or (bh and rh <= 2)
    )


def binomial_sf(k, n, p):
    return sum(math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i)) for i in range(k, n + 1))


def rows_oldest_first(rows):
    return list(reversed(rows))


def percentile_ranks(vals):
    if len(vals) <= 1:
        return [0.5]
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0] * len(vals)
    for rank, idx in enumerate(order):
        ranks[idx] = rank / (len(vals) - 1)
    return ranks


def zone_bayes(train, zone_name, k_total, k_per_draw, window=500, alpha=1.0):
    """走势 + 冷热 + 贝叶斯后验的综合评分，和值不参与选号。"""
    tr = train[-window:] if len(train) > window else train
    counts = [0] * k_total
    counts_30 = [0] * k_total
    counts_100 = [0] * k_total
    recent5 = [0] * k_total
    last = [-1] * k_total
    pos_counts = [[0] * k_total for _ in range(k_per_draw)]
    sums = []
    n = len(tr)
    start_5 = max(0, n - 5)
    start_30 = max(0, n - 30)
    start_100 = max(0, n - 100)
    for idx, row in enumerate(tr):
        raw = row[zone_name]
        balls = raw if isinstance(raw, list) else [raw]
        sums.append(sum(balls))
        for b in balls:
            counts[b - 1] += 1
            last[b - 1] = idx
            if idx >= start_100:
                counts_100[b - 1] += 1
            if idx >= start_30:
                counts_30[b - 1] += 1
            if idx >= start_5:
                recent5[b - 1] += 1
        for p, num in enumerate(sorted(balls)):
            pos_counts[p][num - 1] += 1
    mean = statistics.mean(sums)
    std = statistics.stdev(sums) if n > 1 else 1.0
    expected_rate = k_per_draw / k_total
    expected_gap = k_total / k_per_draw
    exp_all = k_per_draw * n / k_total
    pos_prob = [
        [(alpha + pos_counts[p][i]) / (n + k_total * alpha) for i in range(k_total)]
        for p in range(k_per_draw)
    ]
    position_modes = [
        max(range(k_total), key=lambda i: pos_counts[p][i]) + 1
        for p in range(k_per_draw)
    ]
    bayes = [0.0] * k_total
    hot = [0.0] * k_total
    cold = [0.0] * k_total
    trend = [0.0] * k_total
    z500 = [0.0] * k_total
    gap_values = [0] * k_total
    features = []
    for i in range(k_total):
        gap = n - 1 - last[i] if last[i] >= 0 else n
        gap_values[i] = gap
        posterior = (alpha + counts[i]) / (k_total * alpha + k_per_draw * n)
        recent_rate = counts_30[i] / max(1, len(tr[-30:]))
        medium_rate = counts_100[i] / max(1, len(tr[-100:]))
        bayes[i] = posterior
        hot[i] = recent_rate / expected_rate if expected_rate else 0
        cold[i] = gap / expected_gap
        trend[i] = recent_rate - medium_rate
        z500[i] = (counts[i] - exp_all) / math.sqrt(
            n * expected_rate * (1 - expected_rate)
        ) if n else 0
        features.append(
            {
                "number": i + 1,
                "count_500": counts[i],
                "count_100": counts_100[i],
                "count_30": counts_30[i],
                "recent5": recent5[i],
                "gap": gap,
                "z500": round(z500[i], 2),
                "hotCold": (
                    "热"
                    if counts_30[i] >= math.ceil(30 * k_per_draw / k_total * 1.2)
                    else "冷" if gap >= expected_gap * 1.5 else "中"
                ),
                "popularity": "大众" if i + 1 <= 31 else "非大众",
            }
        )
    rank_bayes = percentile_ranks(bayes)
    rank_hot = percentile_ranks(hot)
    rank_cold = percentile_ranks(cold)
    rank_trend = percentile_ranks(trend)
    state = load_model_state()
    w = state["weights"]
    scores = [
        w["bayes"] * rank_bayes[i] + w["hot"] * rank_hot[i]
        + w["cold"] * rank_cold[i] + w["trend"] * rank_trend[i]
        for i in range(k_total)
    ]
    for i, feat in enumerate(features):
        feat["score"] = round(scores[i], 4)
    return {
        "scores": scores,
        "bayes": bayes,
        "counts": counts,
        "features": features,
        "mean": mean,
        "std": std,
        "n": n,
        "k_per_draw": k_per_draw,
        "k_total": k_total,
        "expected_rate": expected_rate,
        "position_prob": pos_prob,
        "position_modes": position_modes,
    }


def position_fit(zone, nums):
    """位置定律：本注在历史每个位置上是否接近最可能号码，只作正向促进。"""
    nums = sorted(nums)
    probs = [zone["position_prob"][p][num - 1] for p, num in enumerate(nums)]
    expected = zone["expected_rate"]
    return statistics.mean(probs) / expected if expected else 1.0


def zone_top_combos(zone, pool_size, k, top_n):
    boost = load_model_state()["position_boost"]
    top_idx = sorted(
        range(zone["k_total"]), key=lambda i: zone["scores"][i], reverse=True
    )[:pool_size]
    scored = []
    for comb_idx in itertools.combinations(top_idx, k):
        nums = tuple(sorted(i + 1 for i in comb_idx))
        score = sum(zone["scores"][i] for i in comb_idx)
        score *= 1 + boost * position_fit(zone, nums)
        scored.append((score, nums))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:top_n]


def candidate_combos(game, train, n=30):
    """先生成 30 注候选，再用位置判断与组合重选。"""
    pool = load_model_state()["pool_size"]
    if game == "dlt":
        front = zone_bayes(train, "front", 35, 5)
        back = zone_bayes(train, "back", 12, 2)
        front_top = zone_top_combos(front, pool["dlt_front"], 5, 30)
        back_top = zone_top_combos(back, 12, 2, 6)
        candidates = []
        for i, (f_score, f_nums) in enumerate(front_top):
            b_score, b_nums = back_top[i % len(back_top)]
            candidates.append(
                {
                    "combo": (f_nums, b_nums),
                    "score": f_score + b_score,
                    "main_score": f_score,
                    "back_score": b_score,
                }
            )
        return candidates, {"front": front, "back": back}

    red = zone_bayes(train, "red", 33, 6)
    blue = zone_bayes(train, "blue", 16, 1)
    red_top = zone_top_combos(red, pool["ssq_red"], 6, 30)
    blue_top = zone_top_combos(blue, 16, 1, 6)
    candidates = []
    for i, (r_score, r_nums) in enumerate(red_top):
        b_score, b_nums = blue_top[i % len(blue_top)]
        candidates.append(
            {
                "combo": (r_nums, (b_nums[0],)),
                "score": r_score + b_score,
                "main_score": r_score,
                "back_score": b_score,
            }
        )
    return candidates, {"red": red, "blue": blue}


def pick_bayes_combo(game, train):
    """多定律独立评分 + 位置促进，各定律只正向叠加，不互相抵消。"""
    candidates, zones = candidate_combos(game, train, n=30)
    best = candidates[0]
    if game == "dlt":
        return {
            "combo": best["combo"],
            "front": zones["front"],
            "back": zones["back"],
            "front_score": best["main_score"],
            "back_score": best["back_score"],
            "candidates": candidates,
        }
    return {
        "combo": best["combo"],
        "red": zones["red"],
        "blue": zones["blue"],
        "red_score": best["main_score"],
        "blue_score": best["back_score"],
        "candidates": candidates,
    }


def region_ranges(game, zone_name):
    if game == "dlt":
        return {
            "front": [(1, 12), (13, 24), (25, 35)],
            "back": [(1, 4), (5, 8), (9, 12)],
        }[zone_name]
    return {
        "red": [(1, 11), (12, 22), (23, 33)],
        "blue": [(1, 5), (6, 11), (12, 16)],
    }[zone_name]


def balanced_layer(zone, pool, target, min_per_region, ranges):
    """按三区域配额选层，保证每一层都覆盖三个区域。"""
    pool = sorted(set(pool))
    selected = set()
    for lo, hi in ranges:
        cands = [n for n in pool if lo <= n <= hi]
        cands.sort(key=lambda n: zone["scores"][n - 1], reverse=True)
        selected.update(cands[:min(len(cands), min_per_region)])
    remaining = [n for n in pool if n not in selected]
    remaining.sort(key=lambda n: zone["scores"][n - 1], reverse=True)
    need = target - len(selected)
    if need > 0:
        selected.update(remaining[:need])
    result = sorted(selected)
    while len(result) > target:
        result = sorted(result, key=lambda n: zone["scores"][n - 1])[1:]
    if len(result) < target:
        extra = [n for n in pool if n not in result]
        extra.sort(key=lambda n: zone["scores"][n - 1], reverse=True)
        result.extend(extra[: target - len(result)])
    return sorted(result)


def region_round(zone, pool, ranges, removes):
    """只按区域独立排除，不混区筛选。"""
    result, _ = region_round_trace(zone, pool, ranges, removes)
    return result


def region_round_trace(zone, pool, ranges, removes):
    """按区域独立排除，并返回每层每个区域被去掉的号码。"""
    result = list(pool)
    drops = []
    for (lo, hi), remove_count in zip(ranges, removes):
        region_nums = [n for n in result if lo <= n <= hi]
        if len(region_nums) <= remove_count + 1:
            drops.append([])
            continue
        region_nums.sort(key=lambda n: zone["scores"][n - 1])
        drop = region_nums[:remove_count]
        drops.append(sorted(drop))
        drop_set = set(drop)
        result = [n for n in result if n not in drop_set]
    return sorted(result), drops


def pick_funnel_combo(game, train):
    """四区域独立漏斗：前区三区+后区，每层只在各自区域内排除。"""
    state = load_model_state()
    boost = state["position_boost"]
    if game == "dlt":
        main_zone, main_k, main_K = "front", 5, 35
        back_zone, back_k, back_K = "back", 2, 12
    else:
        main_zone, main_k, main_K = "red", 6, 33
        back_zone, back_k, back_K = "blue", 1, 16

    ranges = region_ranges(game, main_zone)
    z_full = zone_bayes(train, main_zone, main_K, main_k, window=500)
    layer1, drops1 = region_round_trace({"scores": z_full["bayes"]}, list(range(1, main_K + 1)), ranges, [2, 2, 2])
    z150 = zone_bayes(train, main_zone, main_K, main_k, window=150)
    layer2, drops2 = region_round_trace({"scores": z150["bayes"]}, layer1, ranges, [3, 3, 3])
    z60 = zone_bayes(train, main_zone, main_K, main_k, window=60)
    layer3, drops3 = region_round_trace({"scores": z60["bayes"]}, layer2, ranges, [4, 4, 4])
    if len(layer3) < main_k + 3:
        extra = [n for n in layer2 if n not in layer3]
        extra.sort(key=lambda n: z60["bayes"][n - 1], reverse=True)
        layer3 = sorted(layer3 + extra[: main_k + 3 - len(layer3)])
    target_unusual = 2 if game == "dlt" else 3
    by60 = {f["number"]: f for f in z60["features"]}
    unusual_in_l3 = sum(1 for n in layer3 if by60.get(n, {}).get("hotCold") != "热")
    if unusual_in_l3 < target_unusual:
        unusual_candidates = [
            n for n in layer2
            if n not in layer3 and by60.get(n, {}).get("hotCold") != "热"
        ]
        unusual_candidates.sort(key=lambda n: z60["bayes"][n - 1], reverse=True)
        need = target_unusual - unusual_in_l3
        layer3 = sorted(layer3 + unusual_candidates[:need])
    unusual_in_l3 = sum(1 for n in layer3 if by60.get(n, {}).get("hotCold") != "热")
    ideal_unusual = min(target_unusual, unusual_in_l3)

    back_ranges = [(1, back_K)]
    zb_full = zone_bayes(train, back_zone, back_K, back_k, window=500)
    bl1, bd1 = region_round_trace({"scores": zb_full["bayes"]}, list(range(1, back_K + 1)), back_ranges, [2 if game == "dlt" else 6])
    zb150 = zone_bayes(train, back_zone, back_K, back_k, window=150)
    bl2, bd2 = region_round_trace({"scores": zb150["bayes"]}, bl1, back_ranges, [3])
    zb60 = zone_bayes(train, back_zone, back_K, back_k, window=60)
    bl3, bd3 = region_round_trace({"scores": zb60["bayes"]}, bl2, back_ranges, [4])
    if len(bl3) < back_k + 1:
        extra = [n for n in bl2 if n not in bl3]
        extra.sort(key=lambda n: zb60["bayes"][n - 1], reverse=True)
        bl3 = sorted(bl3 + extra[: back_k + 1 - len(bl3)])

    def unconventional_bonus(nums):
        feats = z_full["features"]
        by = {f["number"]: f for f in feats}
        non = sum(1 for n in nums if n > 31)
        cold = sum(1 for n in nums if by.get(n, {}).get("hotCold") == "冷")
        unusual = sum(1 for n in nums if by.get(n, {}).get("hotCold") != "热")
        ideal_unusual = 2 if game == "dlt" else 3
        penalty = 0.02 * abs(unusual - ideal_unusual)
        reward = 0.05 if unusual == ideal_unusual else 0
        return reward - penalty

    def unusual_count(nums):
        return sum(1 for n in nums if by60.get(n, {}).get("hotCold") != "热")

    def region_missing(nums):
        counts = [sum(1 for n in nums if lo <= n <= hi) for lo, hi in ranges]
        return sum(1 for c in counts if c == 0)

    ranked_main = []
    for comb_idx in itertools.combinations(layer3, main_k):
        nums = tuple(sorted(comb_idx))
        base_score = sum(z60["bayes"][n - 1] for n in nums)
        base_score *= 1 + boost * position_fit(z_full, nums)
        ranked_main.append((base_score, nums))
    ranked_main.sort(key=lambda x: x[0], reverse=True)
    top_main = ranked_main[:200]
    best_main = min(
        top_main,
        key=lambda item: (
            region_missing(item[1]),
            abs(unusual_count(item[1]) - ideal_unusual),
            -item[0],
        ),
    )[1]

    if game == "dlt":
        best_back = None
        best_back_score = -1
        for comb_idx in itertools.combinations(bl3, 2):
            nums = tuple(sorted(comb_idx))
            score = sum(zb60["bayes"][n - 1] for n in nums)
            score *= 1 + boost * position_fit(zb_full, nums)
            if score > best_back_score:
                best_back_score = score
                best_back = nums
        combo = (best_main, best_back)
    else:
        best_blue = max(bl3, key=lambda n: zb60["bayes"][n - 1])
        combo = (best_main, (best_blue,))

    feats_by = {f["number"]: f for f in z_full["features"]}
    non_nums = [n for n in best_main if n > 31]
    cold_nums = [n for n in best_main if feats_by.get(n, {}).get("hotCold") == "冷"]
    hot_nums = [n for n in best_main if feats_by.get(n, {}).get("hotCold") == "热"]
    unusual_nums = [n for n in best_main if feats_by.get(n, {}).get("hotCold") != "热"]
    reasons = []
    if non_nums:
        reasons.append("包含非大众号 " + " ".join(f"{n:02d}" for n in non_nums))
    if cold_nums:
        reasons.append("包含长遗漏冷号 " + " ".join(f"{n:02d}" for n in cold_nums))
    if hot_nums:
        reasons.append("包含近期热号 " + " ".join(f"{n:02d}" for n in hot_nums))
    reasons.append(
        f"反常规度适中：非热号 {len(unusual_nums)} 个（含中性/冷号），"
        "整体看起来不太可能但不至于完全离谱"
    )
    reasons.append(
        f"第3层候选主 {len(layer3)} 个号码，组合为 {comb(len(layer3), main_k)} 注，"
        "该组合综合数学分最高且反常规度较高"
    )
    selection_reason = "；".join(reasons)

    history_keys = set()
    for row in train:
        if game == "dlt":
            history_keys.add((tuple(row["front"]), tuple(row["back"])))
        else:
            history_keys.add((tuple(row["red"]), row["blue"]))

    def exact_key(cmb):
        if game == "dlt":
            return (cmb[0], cmb[1])
        return (cmb[0], cmb[1][0])

    repeat_adjusted = False
    attempts = 0
    while exact_key(combo) in history_keys and attempts < 5:
        attempts += 1
        main_list = list(combo[0])
        main_list.sort(key=lambda n: z60["scores"][n - 1])
        replaced = False
        for n in main_list:
            for cand in sorted(layer3, key=lambda x: z60["scores"][x - 1], reverse=True):
                if cand in main_list:
                    continue
                new_main = tuple(sorted((set(main_list) - {n}) | {cand}))
                new_combo = (new_main, combo[1])
                if exact_key(new_combo) not in history_keys:
                    combo = new_combo
                    repeat_adjusted = True
                    replaced = True
                    break
            if replaced:
                break
        if not replaced:
            break

    def recent_tier_hit(cmb, row):
        if game == "dlt":
            fh = len(set(cmb[0]) & set(row["front"]))
            bh = len(set(cmb[1]) & set(row["back"]))
            return (fh, bh) == (2, 1)
        rh = len(set(cmb[0]) & set(row["red"]))
        return rh == 2 and cmb[1][0] == row["blue"]

    recent = train[-5:]
    recent_repeat_adjusted = False
    attempts = 0
    while any(recent_tier_hit(combo, row) for row in recent) and attempts < 5:
        attempts += 1
        main_list = list(combo[0])
        main_list.sort(key=lambda n: z60["scores"][n - 1])
        replaced = False
        for n in main_list:
            for cand in sorted(layer3, key=lambda x: z60["scores"][x - 1], reverse=True):
                if cand in main_list:
                    continue
                new_main = tuple(sorted((set(main_list) - {n}) | {cand}))
                new_combo = (new_main, combo[1])
                if not any(recent_tier_hit(new_combo, row) for row in recent):
                    combo = new_combo
                    recent_repeat_adjusted = True
                    replaced = True
                    break
            if replaced:
                break
        if not replaced:
            break

    def tier_priority(cmb, row):
        if game == "dlt":
            fh = len(set(cmb[0]) & set(row["front"]))
            bh = len(set(cmb[1]) & set(row["back"]))
            if fh == 5 and bh == 2:
                return 1
            if fh == 5 and bh == 1:
                return 2
            if fh == 5 and bh == 0:
                return 3
            if fh == 4 and bh == 2:
                return 4
            if fh == 4 and bh == 1:
                return 5
            if fh == 3 and bh == 2:
                return 6
            if (
                (fh == 4 and bh == 0)
                or (fh == 3 and bh == 1)
                or (fh == 2 and bh == 2)
                or (fh == 1 and bh == 2)
                or (fh == 0 and bh == 2)
            ):
                return 7
            return None
        rh = len(set(cmb[0]) & set(row["red"]))
        blue_hit = cmb[1][0] == row["blue"]
        if rh == 6 and blue_hit:
            return 1
        if rh == 6 and not blue_hit:
            return 2
        if rh == 5 and blue_hit:
            return 3
        if (rh == 5 and not blue_hit) or (rh == 4 and blue_hit):
            return 4
        if (rh == 4 and not blue_hit) or (rh == 3 and blue_hit):
            return 5
        if (rh == 2 or rh == 1) and blue_hit:
            return 6
        return None

    prize_window = {1: 300, 2: 200, 3: 150, 4: 100, 5: 60, 6: 5, 7: 5}
    n_train = len(train)

    def has_recent_high_prize(cmb):
        for idx, row in enumerate(train):
            tier = tier_priority(cmb, row)
            if tier and (n_train - 1 - idx) <= prize_window[tier]:
                return True
        return False

    prize_repeat_adjusted = False
    attempts = 0
    while has_recent_high_prize(combo) and attempts < 5:
        attempts += 1
        main_list = list(combo[0])
        main_list.sort(key=lambda n: z60["scores"][n - 1])
        replaced = False
        for n in main_list:
            for cand in sorted(layer3, key=lambda x: z60["scores"][x - 1], reverse=True):
                if cand in main_list:
                    continue
                new_main = tuple(sorted((set(main_list) - {n}) | {cand}))
                new_combo = (new_main, combo[1])
                if not has_recent_high_prize(new_combo):
                    combo = new_combo
                    prize_repeat_adjusted = True
                    replaced = True
                    break
            if replaced:
                break
        if not replaced:
            break

    exclusions = {
        "main": [
            {"layer": 1, "regions": drops1},
            {"layer": 2, "regions": drops2},
            {"layer": 3, "regions": drops3},
        ],
        "back": [
            {"layer": 1, "regions": bd1},
            {"layer": 2, "regions": bd2},
            {"layer": 3, "regions": bd3},
        ],
    }

    return {
        "game": game,
        "combo": combo,
        "candidate_main_count": math.comb(len(layer3), main_k),
        "selection_reason": selection_reason,
        "exclusions": exclusions,
        "repeat_adjusted": repeat_adjusted,
        "recent_repeat_adjusted": recent_repeat_adjusted,
        "prize_repeat_adjusted": prize_repeat_adjusted,
        "layers": {
            "main": [layer1, layer2, layer3],
            "back": [bl1, bl2, bl3],
        },
        "zones": {
            "main_full": z_full,
            "main_150": z150,
            "main_60": z60,
            "back_full": zb_full,
            "back_150": zb150,
            "back_60": zb60,
        },
    }


def method_ticket(game, train, method, seed=20260812):
    """每种方法各出一注，主推方法为贝叶斯模型平均。"""
    if method == "funnel":
        funnel_pred = pick_funnel_combo(game, train)
        return {
            "method": "funnel",
            "note": "四区域独立分层漏斗",
            "combo": funnel_pred["combo"],
            "exclusions": funnel_pred.get("exclusions"),
        }
    state = load_model_state()
    boost = state["position_boost"]
    if game == "dlt":
        main_zone, main_k, main_K = "front", 5, 35
        back_zone, back_k, back_K = "back", 2, 12
    else:
        main_zone, main_k, main_K = "red", 6, 33
        back_zone, back_k, back_K = "blue", 1, 16

    z500 = zone_bayes(train, main_zone, main_K, main_k, window=500)
    z150 = zone_bayes(train, main_zone, main_K, main_k, window=150)
    z60 = zone_bayes(train, main_zone, main_K, main_k, window=60)
    zb500 = zone_bayes(train, back_zone, back_K, back_k, window=500)
    zb150 = zone_bayes(train, back_zone, back_K, back_k, window=150)
    zb60 = zone_bayes(train, back_zone, back_K, back_k, window=60)

    def pick_main(scores):
        top = sorted(range(1, main_K + 1), key=lambda n: scores[n - 1], reverse=True)[:14]
        ranges = region_ranges(game, main_zone)
        for lo, hi in ranges:
            if not any(lo <= n <= hi for n in top):
                best_region = max(
                    range(lo, hi + 1), key=lambda n: scores[n - 1]
                )
                if best_region not in top:
                    lowest = min(top, key=lambda n: scores[n - 1])
                    top.remove(lowest)
                    top.append(best_region)
        ranked = []
        for comb_idx in itertools.combinations(top, main_k):
            nums = tuple(sorted(comb_idx))
            s = sum(scores[n - 1] for n in nums)
            s *= 1 + boost * position_fit(z500, nums)
            ranked.append((s, nums))
        ranked.sort(key=lambda x: x[0], reverse=True)
        by60 = {f["number"]: f for f in z60["features"]}
        unusual_in_pool = sum(
            1 for n in top if by60.get(n, {}).get("hotCold") != "热"
        )
        ideal = min(2 if game == "dlt" else 3, unusual_in_pool)
        top20 = ranked[:200]
        def region_missing(nums):
            counts = [
                sum(1 for n in nums if lo <= n <= hi) for lo, hi in ranges
            ]
            return sum(1 for c in counts if c == 0)

        return min(
            top20,
            key=lambda item: (
                region_missing(item[1]),
                abs(
                    sum(
                        1 for n in item[1] if by60.get(n, {}).get("hotCold") != "热"
                    ) - ideal
                ),
                -item[0],
            ),
        )[1], top

    if method == "bayes_avg":
        avg = [
            (z500["bayes"][i] + z150["bayes"][i] + z60["bayes"][i]) / 3
            for i in range(main_K)
        ]
        main, main_pool = pick_main(avg)
        note = "贝叶斯模型平均 + 位置后验 + 适中反常规，主推"
    elif method == "hot":
        hot = [f["count_30"] / max(1, min(30, z60["n"])) for f in z60["features"]]
        main, main_pool = pick_main(hot)
        note = "短周期热度加权"
    elif method == "cold":
        cold = [f["gap"] / (main_K / main_k) for f in z60["features"]]
        main, main_pool = pick_main(cold)
        note = "遗漏回归"
    elif method == "position":
        pos_score = [
            max(z500["position_prob"][p][i] for p in range(main_k))
            for i in range(main_K)
        ]
        main, main_pool = pick_main(pos_score)
        note = "位置分布后验"
    else:
        rng = random.Random(seed)
        by60 = {f["number"]: f for f in z60["features"]}
        ideal_unusual = 2 if game == "dlt" else 3
        ranges = region_ranges(game, main_zone)

        def region_missing(nums):
            counts = [
                sum(1 for n in nums if lo <= n <= hi) for lo, hi in ranges
            ]
            return sum(1 for c in counts if c == 0)

        best = None
        best_key = None
        for _ in range(300):
            nums = tuple(sorted(rng.sample(range(1, main_K + 1), main_k)))
            unusual = sum(
                1 for n in nums if by60.get(n, {}).get("hotCold") != "热"
            )
            key = (region_missing(nums), abs(unusual - ideal_unusual))
            if best is None or key < best_key or (key == best_key and rng.random() < 0.5):
                best = nums
                best_key = key
        main = best
        main_pool = list(range(1, main_K + 1))
        note = "随机机选对照"

    if method == "random":
        rng_back = random.Random(seed + 7)
        back_pool = list(range(1, back_K + 1))
        if game == "dlt":
            back = tuple(sorted(rng_back.sample(range(1, back_K + 1), 2)))
        else:
            back = (rng_back.randint(1, back_K),)
    elif method == "position":
        used = []
        back_pool = []
        back = []
        for p in range(back_k):
            order = sorted(
                range(1, back_K + 1),
                key=lambda n: zb500["position_prob"][p][n - 1],
                reverse=True,
            )
            for n in order:
                if n not in used:
                    used.append(n)
                    back_pool.append(n)
                    back.append(n)
                    break
        back_pool = sorted(back_pool)
        back = tuple(sorted(back)) if game == "dlt" else (back[0],)
    else:
        if method == "bayes_avg":
            back_scores = [
                (zb500["bayes"][i] + zb150["bayes"][i] + zb60["bayes"][i]) / 3
                for i in range(back_K)
            ]
        elif method == "hot":
            back_scores = [
                f["count_30"] / max(1, min(30, zb60["n"]))
                for f in zb60["features"]
            ]
        else:
            back_scores = [f["gap"] / (back_K / back_k) for f in zb60["features"]]
        if game == "dlt":
            back = tuple(
                sorted(
                    range(1, back_K + 1),
                    key=lambda n: back_scores[n - 1],
                    reverse=True,
                )[:2]
            )
        else:
            blue = max(range(1, back_K + 1), key=lambda n: back_scores[n - 1])
            back = (blue,)
        back_pool = sorted(
            range(1, back_K + 1),
            key=lambda n: back_scores[n - 1],
            reverse=True,
        )[:min(5, back_K)]
    combo = (main, back)
    return {
        "method": method,
        "note": note,
        "combo": combo,
        "main_pool": sorted(main_pool),
        "back_pool": back_pool,
    }


def all_method_tickets(game, train):
    return [
        method_ticket(game, train, "bayes_avg"),
        method_ticket(game, train, "funnel"),
        method_ticket(game, train, "hot"),
        method_ticket(game, train, "cold"),
        method_ticket(game, train, "position"),
        method_ticket(game, train, "random"),
    ]


def save_pending_predictions():
    """把上一期还没开奖的预测存档，开奖后用于反思对比。"""
    cfg = load_json_file(CONFIG_PATH)
    log = load_json_file(PREDICTION_LOG_PATH)
    if not cfg:
        return log
    specs = [
        ("dlt", "dlt_future", "dlt_history_500.json", "front", "back"),
        ("ssq", "ssq_future", "ssq_history_500.json", "red", "blue"),
    ]
    for game, future_key, data_name, main_zone, back_zone in specs:
        future = cfg.get(future_key) or []
        if not future:
            continue
        issue = future[0]
        if issue in log:
            continue
        rows = load_rows(DATA_DIR / data_name)
        if len(rows) < 2:
            continue
        train = rows_oldest_first(rows[1:])
        funnel = pick_funnel_combo(game, train)
        if not funnel or not funnel["combo"]:
            continue
        combo = funnel["combo"]
        if game == "dlt":
            combo_dict = {"front": list(combo[0]), "back": list(combo[1])}
        else:
            combo_dict = {"red": list(combo[0]), "blue": list(combo[1])}
        layers = funnel["layers"]
        main_nums = set(layers["main"][0])
        layer3_nums = set(layers["main"][2])
        back_nums = set(layers["back"][0]) | set(layers["back"][1])
        main_full = funnel["zones"]["main_full"]
        back_full = funnel["zones"]["back_full"]
        features = {}
        for zone_name in (main_zone, back_zone):
            zone = main_full if zone_name == main_zone else back_full
            features[zone_name] = {
                str(f["number"]): {
                    key: f[key] for key in ("count_30", "gap", "recent5", "z500")
                }
                for f in zone["features"]
            }
        log[issue] = {
            "game": game,
            "issue": issue,
            "generated_at": cfg.get("generated_at"),
            "combo": combo_dict,
            "layers": {
                "main": [list(x) for x in layers["main"]],
                "back": [list(x) for x in layers["back"]],
            },
            "main_considered": sorted(main_nums),
            "layer3_considered": sorted(layer3_nums),
            "back_considered": sorted(back_nums),
            "features": features,
            "position_modes": {
                zone_name: zone["position_modes"]
                for zone_name, zone in (
                    (main_zone, main_full),
                    (back_zone, back_full),
                )
            },
            "model_state": load_model_state(),
            "reflected": False,
        }
    save_json_file(PREDICTION_LOG_PATH, log)
    return log


def zone_expected(game, zone_name):
    if game == "dlt":
        return {"front": (5, 35), "back": (2, 12)}[zone_name]
    return {"red": (6, 33), "blue": (1, 16)}[zone_name]


def analyze_one_reflection(record, actual):
    game = record["game"]
    if game == "dlt":
        main_zone, back_zone = "front", "back"
        pred_main = set(record["combo"]["front"])
        pred_back = set(record["combo"]["back"])
        actual_main = actual["front"]
        actual_back = actual["back"]
        main_hits = len(pred_main & set(actual_main))
        back_hits = len(pred_back & set(actual_back))
        prize = dlt_win(main_hits, back_hits)
    else:
        main_zone, back_zone = "red", "blue"
        pred_main = set(record["combo"]["red"])
        pred_back = set(record["combo"]["blue"])
        actual_main = actual["red"]
        actual_back = [actual["blue"]]
        main_hits = len(pred_main & set(actual_main))
        back_hits = 1 if pred_back == set(actual_back) else 0
        prize = ssq_win(main_hits, bool(back_hits))

    k, k_total = zone_expected(game, main_zone)
    expected_gap = k_total / k
    main_overlap = len(set(actual_main) & set(record["main_considered"]))
    layer3_overlap = (
        len(set(actual_main) & set(record.get("layer3_considered", [])))
        if record.get("layer3_considered") is not None
        else None
    )
    back_overlap = len(set(actual_back) & set(record["back_considered"]))
    features = record["features"][main_zone]
    actual_features = [features.get(str(n), {}) for n in actual_main]
    hot_count = sum(
        1 for f in actual_features if (f.get("count_30") or 0) >= max(2, round(30 * k / k_total))
    )
    gaps = [f.get("gap") or 0 for f in actual_features]
    avg_gap = statistics.mean(gaps) if gaps else 0
    sum_pred = sum(record["combo"][main_zone])
    sum_actual = sum(actual_main)
    pos_modes = record["position_modes"][main_zone]
    actual_sorted = sorted(actual_main)
    pos_hit = sum(1 for p, n in enumerate(actual_sorted) if pos_modes[p] == n)
    pos_near = sum(
        1 for p, n in enumerate(actual_sorted) if abs(pos_modes[p] - n) <= 2
    )

    reasons = []
    if main_overlap < 2:
        reasons.append("实际号码大多不在第1层20个候选范围")
    if layer3_overlap is not None and layer3_overlap == 0:
        reasons.append("第3层8-10个没有覆盖实际号码")
    if avg_gap > expected_gap * 1.5:
        reasons.append("实际号码偏向长遗漏，冷号权重不足")
    if hot_count >= k - 1:
        reasons.append("实际号码偏热，热号权重需要保持")
    if pos_near <= 1:
        reasons.append("位置模式与实开位置错位")
    if abs(sum_actual - sum_pred) > 30:
        reasons.append("和值偏差较大，但和值不是选号机制")
    if not reasons:
        reasons.append("结构接近但号码未命中，属于随机偏差")

    return {
        "game": game,
        "issue": record["issue"],
        "actual_main": sorted(actual_main),
        "actual_back": sorted(actual_back),
        "predicted_main": sorted(pred_main),
        "predicted_back": sorted(pred_back),
        "main_hits": main_hits,
        "back_hits": back_hits,
        "prize": prize,
        "main_overlap": main_overlap,
        "layer3_overlap": layer3_overlap,
        "back_overlap": back_overlap,
        "hot_count": hot_count,
        "avg_gap": round(avg_gap, 1),
        "expected_gap": round(expected_gap, 1),
        "sum_pred": sum_pred,
        "sum_actual": sum_actual,
        "pos_hit": pos_hit,
        "pos_near": pos_near,
        "reasons": reasons,
    }


def apply_small_adjustment(ref):
    state = load_model_state()
    w = state["weights"]
    pool = state["pool_size"]
    k, k_total = zone_expected(ref["game"], "front" if ref["game"] == "dlt" else "red")
    if ref["avg_gap"] > ref["expected_gap"] * 1.5:
        w["cold"] = min(0.40, w["cold"] + 0.03)
        w["hot"] = max(0.10, w["hot"] - 0.02)
        w["bayes"] = max(0.20, w["bayes"] - 0.01)
    if ref["hot_count"] >= k - 1:
        w["hot"] = min(0.40, w["hot"] + 0.02)
        w["cold"] = max(0.10, w["cold"] - 0.01)
    if ref["pos_near"] <= 1:
        state["position_boost"] = min(0.40, state["position_boost"] + 0.05)
    if ref["main_overlap"] < 2:
        key = "dlt_front" if ref["game"] == "dlt" else "ssq_red"
        cap = 24 if ref["game"] == "dlt" else 28
        pool[key] = min(cap, pool[key] + 1)
    if ref.get("layer3_overlap") == 0:
        key3 = "dlt" if ref["game"] == "dlt" else "ssq"
        state["layer3_size"][key3] = min(10, state["layer3_size"][key3] + 1)
    state["pool_size"] = pool
    total = sum(w.values())
    state["weights"] = {key: round(value / total, 4) for key, value in w.items()}
    save_model_state(state)
    return state


def reflect_previous_draws(rows_map):
    log = load_json_file(PREDICTION_LOG_PATH)
    reflections = []
    for issue, record in list(log.items()):
        if record.get("reflected"):
            continue
        game = record["game"]
        actual = next((r for r in rows_map[game] if r["issue"] == issue), None)
        if actual is None:
            continue
        ref = analyze_one_reflection(record, actual)
        state = apply_small_adjustment(ref)
        ref["adjustment"] = {
            "weights": state["weights"],
            "position_boost": state["position_boost"],
            "pool_size": state["pool_size"],
            "layer3_size": state["layer3_size"],
        }
        reflections.append(ref)
        record["reflected"] = True
        record["reflection"] = {
            "main_hits": ref["main_hits"],
            "back_hits": ref["back_hits"],
            "main_overlap": ref["main_overlap"],
            "back_overlap": ref["back_overlap"],
            "reasons": ref["reasons"],
            "adjustment": ref["adjustment"],
        }
    save_json_file(PREDICTION_LOG_PATH, log)
    return reflections


def reflection_lines(reflections):
    lines = []
    if not reflections:
        return lines
    lines.append("## 上一期反思")
    lines.append("")
    for ref in reflections:
        game_name = "大乐透" if ref["game"] == "dlt" else "双色球"
        lines.append(f"### {game_name} {ref['issue']}期")
        lines.append(
            "实际：" + fmt_combo(ref["game"], (ref["actual_main"], ref["actual_back"]))
        )
        lines.append(
            "预测：" + fmt_combo(ref["game"], (ref["predicted_main"], ref["predicted_back"]))
        )
        lines.append(
            f"命中：主区 {ref['main_hits']} 个，后区 {ref['back_hits']} 个，"
            f"是否中奖：{'是' if ref['prize'] else '否'}"
        )
        lines.append(
            f"是否在考虑范围内：第1层20个覆盖主区 {ref['main_overlap']} 个，"
            f"第3层覆盖 {ref['layer3_overlap'] if ref['layer3_overlap'] is not None else 'N/A'} 个，"
            f"后区覆盖 {ref['back_overlap']} 个"
        )
        lines.append(f"偏差原因：{'；'.join(ref['reasons'])}")
        adj = ref["adjustment"]
        pool = adj["pool_size"]
        pool_name = "前区" if ref["game"] == "dlt" else "红球"
        pool_before = pool_name + "候选池"
        lines.append(f"候选池调整：{pool_before}扩大到 {pool['dlt_front'] if ref['game'] == 'dlt' else pool['ssq_red']} 个号码池")
        if ref.get("layer3_overlap") == 0:
            key3 = "dlt" if ref["game"] == "dlt" else "ssq"
            lines.append(f"第3层调整：8-10个区间从 {adj['layer3_size'][key3] - 1} 扩大到 {adj['layer3_size'][key3]} 个")
        lines.append(
            "小调整：贝叶斯 "
            f"{adj['weights']['bayes']:.2f}，热号 {adj['weights']['hot']:.2f}，"
            f"冷号 {adj['weights']['cold']:.2f}，走势 {adj['weights']['trend']:.2f}，"
            f"位置促进 {adj['position_boost']:.2f}"
        )
        lines.append("")
    return lines


def backtest_bayes(game, rows):
    oldest = rows_oldest_first(rows)
    main_hits = []
    back_hits = []
    layer1_hits = []
    layer2_hits = []
    layer3_hits = []
    wins = 0
    n = 0
    for t in range(300, len(oldest)):
        train = oldest[max(0, t - 500):t]
        target = oldest[t]
        pred = pick_funnel_combo(game, train)
        combo = pred["combo"]
        actual_main = target["front"] if game == "dlt" else target["red"]
        for i, layer in enumerate(pred["layers"]["main"]):
            hits = len(set(layer) & set(actual_main))
            (layer1_hits if i == 0 else layer2_hits if i == 1 else layer3_hits).append(hits)
        if game == "dlt":
            fh = len(set(combo[0]) & set(target["front"]))
            bh = len(set(combo[1]) & set(target["back"]))
            main_hits.append(fh)
            back_hits.append(bh)
            wins += 1 if dlt_win(fh, bh) else 0
        else:
            rh = len(set(combo[0]) & set(target["red"]))
            bh = 1 if combo[1][0] == target["blue"] else 0
            main_hits.append(rh)
            back_hits.append(bh)
            wins += 1 if ssq_win(rh, bool(bh)) else 0
        n += 1
    return {
        "windows": n,
        "main_mean": round(statistics.mean(main_hits), 3) if n else None,
        "back_rate": round(statistics.mean(back_hits), 3) if n else None,
        "layer1_mean": round(statistics.mean(layer1_hits), 3) if n else None,
        "layer2_mean": round(statistics.mean(layer2_hits), 3) if n else None,
        "layer3_mean": round(statistics.mean(layer3_hits), 3) if n else None,
        "any_prize_rate": round(wins / n * 100, 2) if n else None,
    }


def backtest_method(game, rows, method):
    oldest = rows_oldest_first(rows)
    wins = 0
    n = 0
    for t in range(300, len(oldest)):
        train = oldest[max(0, t - 500):t]
        target = oldest[t]
        if method == "funnel":
            combo = pick_funnel_combo(game, train)["combo"]
        else:
            combo = method_ticket(game, train, method, seed=100000 + t)["combo"]
        if game == "dlt":
            fh = len(set(combo[0]) & set(target["front"]))
            bh = len(set(combo[1]) & set(target["back"]))
            wins += 1 if dlt_win(fh, bh) else 0
        else:
            rh = len(set(combo[0]) & set(target["red"]))
            bh = combo[1][0] == target["blue"]
            wins += 1 if ssq_win(rh, bh) else 0
        n += 1
    return round(wins / n * 100, 2) if n else None


def backtest_method_miss(game, rows, method):
    oldest = rows_oldest_first(rows)
    miss_actual = {}
    miss_pred = {}
    n = 0
    for t in range(300, len(oldest)):
        train = oldest[max(0, t - 500):t]
        target = oldest[t]
        if method == "funnel":
            combo = pick_funnel_combo(game, train)["combo"]
        else:
            combo = method_ticket(game, train, method, seed=100000 + t)["combo"]
        if game == "dlt":
            act_main, act_back = target["front"], target["back"]
            pred_main, pred_back = combo[0], combo[1]
        else:
            act_main, act_back = target["red"], [target["blue"]]
            pred_main, pred_back = combo[0], list(combo[1])
        for x in act_main:
            if x not in pred_main:
                miss_actual[x] = miss_actual.get(x, 0) + 1
        for x in act_back:
            if x not in pred_back:
                miss_actual[x] = miss_actual.get(x, 0) + 1
        for x in pred_main:
            if x not in act_main:
                miss_pred[x] = miss_pred.get(x, 0) + 1
        for x in pred_back:
            if x not in act_back:
                miss_pred[x] = miss_pred.get(x, 0) + 1
        n += 1
    return {
        "windows": n,
        "missed_actual": sorted(miss_actual.items(), key=lambda kv: (-kv[1], kv[0]))[:10],
        "missed_pred": sorted(miss_pred.items(), key=lambda kv: (-kv[1], kv[0]))[:10],
    }


def analyze_latest_miss(game, rows):
    if len(rows) < 2:
        return {}
    latest = rows[0]
    train = rows_oldest_first(rows[1:])
    methods = ["bayes_avg", "funnel", "hot", "cold", "position", "random"]
    out = {}
    for m in methods:
        if m == "funnel":
            pred = pick_funnel_combo(game, train)
            main_pool = pred["layers"]["main"][2]
            back_pool = pred["layers"]["back"][2]
            combo = pred["combo"]
        else:
            ticket = method_ticket(game, train, m, seed=100000 + int(latest["issue"]) % 1000)
            main_pool = ticket.get("main_pool", [])
            back_pool = ticket.get("back_pool", [])
            combo = ticket["combo"]
        if game == "dlt":
            act_main, act_back = latest["front"], latest["back"]
            pred_main, pred_back = combo[0], combo[1]
        else:
            act_main, act_back = latest["red"], [latest["blue"]]
            pred_main, pred_back = combo[0], list(combo[1])
        hit_pred = sorted(
            set([x for x in pred_main if x in act_main] + [
                x for x in pred_back if x in act_back
            ])
        )
        missed_pred = sorted(
            set([x for x in pred_main if x not in act_main] + [
                x for x in pred_back if x not in act_back
            ])
        )
        main_zone_name = "前区" if game == "dlt" else "红球"
        back_zone_name = "后区" if game == "dlt" else "蓝球"
        actual_miss = []
        for x in act_main:
            if x in pred_main:
                continue
            actual_miss.append(
                {
                    "ball": x,
                    "zone": main_zone_name,
                    "stage": "进入候选池但最终未选" if x in main_pool else "被方法排除",
                }
            )
        for x in act_back:
            if x in pred_back:
                continue
            actual_miss.append(
                {
                    "ball": x,
                    "zone": back_zone_name,
                    "stage": "进入候选池但最终未选" if x in back_pool else "被方法排除",
                }
            )
        out[m] = {
            "issue": latest["issue"],
            "actual_main": sorted(act_main),
            "actual_back": sorted(act_back),
            "pred_main": sorted(pred_main),
            "pred_back": sorted(pred_back),
            "hit_pred": sorted(hit_pred),
            "missed_pred": sorted(missed_pred),
            "actual_miss": actual_miss,
        }
    return out


def hypergeom_at_least_one(K, k, n):
    if n <= 0 or n > K:
        return 0.0
    return 1 - math.comb(K - n, k) / math.comb(K, k)


def funnel_lines(pred, game):
    lines = []
    name = "大乐透" if game == "dlt" else "双色球"
    main_zone = "front" if game == "dlt" else "red"
    back_zone = "back" if game == "dlt" else "blue"
    main_k = 5 if game == "dlt" else 6
    main_K = 35 if game == "dlt" else 33
    back_k = 2 if game == "dlt" else 1
    back_K = 12 if game == "dlt" else 16
    ranges = region_ranges(game, main_zone)
    lines.append(f"### {name}")
    labels = ["第1层（20个）", "第2层（15个）", f"第3层（{len(pred['layers']['main'][2])}个）"]
    for i, (label, nums) in enumerate(zip(labels, pred["layers"]["main"])):
        expected = main_k * len(nums) / main_K
        p1 = hypergeom_at_least_one(main_K, main_k, len(nums))
        counts = [
            sum(1 for n in nums if lo <= n <= hi) for lo, hi in ranges
        ]
        lines.append(
            f"- {label}：{'  '.join(f'{n:02d}' for n in nums)}"
        )
        lines.append(
            f"  三区域 {counts[0]}/{counts[1]}/{counts[2]}；"
            f"随机覆盖期望命中 {expected:.2f} 个，至少命中1个约 {p1 * 100:.1f}%"
        )
    for i, nums in enumerate(pred["layers"]["back"]):
        label = "后区第" + str(i + 1) + "层"
        expected = back_k * len(nums) / back_K
        p1 = hypergeom_at_least_one(back_K, back_k, len(nums))
        lines.append(
            f"- {label}（{len(nums)}个）：{'  '.join(f'{n:02d}' for n in nums)}；"
            f"至少命中1个约 {p1 * 100:.1f}%"
        )
    lines.append("")
    return lines


def exclusion_lines(pred, game):
    name = "大乐透" if game == "dlt" else "双色球"
    ex = pred.get("exclusions") or {}
    labels = ["一区", "二区", "三区"]
    lines = [f"### {name} 每一层排除明细"]
    for item in ex.get("main", []):
        parts = []
        for idx, nums in enumerate(item["regions"], 1):
            if nums:
                parts.append(
                    labels[idx - 1] + "去掉 " + " ".join(f"{n:02d}" for n in nums)
                )
        all_removed = [n for region in item["regions"] for n in region]
        lines.append(
            f"- 第{item['layer']}层：{'；'.join(parts) if parts else '未排除'}，"
            f"共去掉 {len(all_removed)} 个"
        )
    for item in ex.get("back", []):
        nums = item["regions"][0] if item["regions"] else []
        text = " ".join(f"{n:02d}" for n in nums) if nums else "未排除"
        lines.append(f"- 后区第{item['layer']}层：去掉 {text}，共去掉 {len(nums)} 个")
    lines.append("")
    return lines


def write_next_prediction(config, dlt_pred, ssq_pred, backtests, reflections=None, method_rows=None, method_stats=None, method_miss=None, latest_miss=None):
    reflections = reflections or []
    method_rows = method_rows or {}
    method_stats = method_stats or {}
    method_miss = method_miss or {}
    latest_miss = latest_miss or {}
    dlt_issue = config["dlt_future"][0]
    ssq_issue = config["ssq_future"][0]
    dlt_date = next(s["date"] for s in config["dlt_schedule"] if s["issue"] == dlt_issue)
    ssq_date = next(s["date"] for s in config["ssq_schedule"] if s["issue"] == ssq_issue)

    dlt_combo = dlt_pred["combo"]
    ssq_combo = ssq_pred["combo"]
    dlt_main = dlt_pred["zones"]["main_full"]
    dlt_back = dlt_pred["zones"]["back_full"]
    ssq_main = ssq_pred["zones"]["main_full"]
    ssq_back = ssq_pred["zones"]["back_full"]
    dlt_front_sum = sum(dlt_combo[0])
    dlt_back_sum = sum(dlt_combo[1])
    ssq_red_sum = sum(ssq_combo[0])
    dlt_p, ssq_p = single_any_prize()
    state = load_model_state()
    dlt_l3 = state["layer3_size"]["dlt"]
    ssq_l3 = state["layer3_size"]["ssq"]

    def n2(x):
        return f"{x:02d}"

    def top_nums(features, key, n=3):
        return [f["number"] for f in sorted(features, key=lambda f: f[key], reverse=True)[:n]]

    def hot_cold_label(zone, num, f):
        k, K = zone["k_per_draw"], zone["k_total"]
        expected_count = 30 * k / K
        expected_gap = K / k
        if f["count_30"] >= math.ceil(expected_count * 1.2):
            return "热"
        if f["gap"] >= expected_gap * 1.5:
            return "冷"
        return "中"

    def popularity_label(num):
        return "大众" if num <= 31 else "非大众"

    def feature_lines(zone, nums, label):
        by_num = {f["number"]: f for f in zone["features"]}
        lines = [f"- 所选{label}走势："]
        lines.append(f"  | 号码 | 近30期次数 | 当前遗漏 | 近5期次数 | 热冷 | 大众度 |")
        lines.append(f"  | --- | --- | --- | --- | --- | --- |")
        for num in nums:
            f = by_num[num]
            lines.append(
                f"  | {n2(num)} | {f['count_30']} | {f['gap']} | {f['recent5']} | "
                f"{hot_cold_label(zone, num, f)} | {popularity_label(num)} |"
            )
        return lines

    def position_lines(zone, nums, label):
        nums = sorted(nums)
        lines = [f"- 所选{label}位置对照（历史位置只作观察）："]
        lines.append("  | 位置 | 本注号码 | 历史该位置最大可能 |")
        lines.append("  | --- | --- | --- |")
        for p, num in enumerate(nums):
            lines.append(f"  | 第{p + 1}位 | {n2(num)} | {n2(zone['position_modes'][p])} |")
        return lines
    dlt_wins = round(backtests["dlt"]["any_prize_rate"] / 100 * backtests["dlt"]["windows"])
    ssq_wins = round(backtests["ssq"]["any_prize_rate"] / 100 * backtests["ssq"]["windows"])
    dlt_pval = binomial_sf(dlt_wins, backtests["dlt"]["windows"], dlt_p)
    ssq_pval = binomial_sf(ssq_wins, backtests["ssq"]["windows"], ssq_p)

    lines = [
        "# 下一期一注预测（贝叶斯后验 + 走势 + 冷热号）",
        "",
        f"生成时间：{config['generated_at']}",
        f"最新大乐透：{config['dlt_latest']['issue']}期 · {config['dlt_latest']['result']}",
        f"最新双色球：{config['ssq_latest']['issue']}期 · {config['ssq_latest']['result']}",
        "",
        "## 一、贝叶斯定律在这里的作用",
        "有用。贝叶斯后验能把“历史出现次数”和“样本少带来的不确定性”一起估计，",
        "比只数频率更稳健。但它改变不了公平开奖的真实概率，所以本工作流把它用于：",
        "1. 给每个球估计后验出现倾向；",
        "2. 叠加近期遗漏，避免把长冷号当成必然；",
        "3. 和值只作事后参考，不参与选号；开奖机不会朝“常见和值范围”靠拢。",
        "4. 同时观察近30期热度、当前遗漏和近5期活跃度，但只作为评分参考，不当作规律。",
        "5. 各条定律独立推理，最终只正向促进，不互相抵消；位置定律负责猜“最可能在哪个位置”。",
        "6. 物理边界：开奖机是混沌系统，公开数据没有机器参数，物理定律只能作边界判断，不能假装模拟机器。",
        "",
        "## 二、大乐透下一期一注",
        f"期号：{dlt_issue} · {dlt_date}",
        "一注：" + fmt_combo("dlt", dlt_combo),
        f"候选主：{dlt_pred['candidate_main_count']} 注（第3层{len(dlt_pred['layers']['main'][2])}个前区号码中选5）",
        f"选择原因：{dlt_pred['selection_reason']}",
        f"前区和值：{dlt_front_sum}（仅参考，不参与选号；历史均值 {dlt_main['mean']:.1f} ± {dlt_main['std']:.1f}）",
        f"后区和值：{dlt_back_sum}（仅参考，不参与选号；历史均值 {dlt_back['mean']:.1f} ± {dlt_back['std']:.1f}）",
        f"单注任意奖概率：{dlt_p*100:.2f}%（这是数学事实，不是模型给的保证）",
        "",
        "## 三、双色球下一期一注",
        f"期号：{ssq_issue} · {ssq_date}",
        "一注：" + fmt_combo("ssq", ssq_combo),
        f"候选主：{ssq_pred['candidate_main_count']} 注（第3层{len(ssq_pred['layers']['main'][2])}个红球号码中选6）",
        f"选择原因：{ssq_pred['selection_reason']}",
        f"红球和值：{ssq_red_sum}（仅参考，不参与选号；历史均值 {ssq_main['mean']:.1f} ± {ssq_main['std']:.1f}）",
        f"单注任意奖概率：{ssq_p*100:.2f}%（这是数学事实，不是模型给的保证）",
        "",
        "## 五、分层漏斗选号（20→15→8-10→单注）",
        "",
        "每层都按三区域划分，并逐层做数学概率分析：",
        "",
    ]
    lines.extend(funnel_lines(dlt_pred, "dlt"))
    lines.extend(exclusion_lines(dlt_pred, "dlt"))
    lines.extend(funnel_lines(ssq_pred, "ssq"))
    lines.extend(exclusion_lines(ssq_pred, "ssq"))
    lines.append("逐层变化分析（200期历史回测）：")
    lines.append(
        "- 大乐透：第1层平均命中 "
        f"{backtests['dlt']['layer1_mean']}（随机期望 2.857），"
        f"第2层 {backtests['dlt']['layer2_mean']}（随机期望 2.143），"
        f"第3层 {backtests['dlt']['layer3_mean']}（随机期望 {5*dlt_l3/35:.3f}）"
    )
    lines.append(
        "- 双色球：第1层平均命中 "
        f"{backtests['ssq']['layer1_mean']}（随机期望 3.636），"
        f"第2层 {backtests['ssq']['layer2_mean']}（随机期望 2.727），"
        f"第3层 {backtests['ssq']['layer3_mean']}（随机期望 {6*ssq_l3/33:.3f}）"
    )
    lines.append(
        "- 原因：每缩小一层，漏掉实际号码的风险也会增加；如果命中率下降，说明当前收敛方向没有数学优势。"
    )
    lines.append(
        "- 每次开奖都不需要符合逻辑，随机性本身就是逻辑；模型只能事后解释，不能事前锁定。"
    )
    lines.append(
        "- 热冷与大众度：每注保留大众热球，也保留反常规冷门球；这改变撞号心理和奖金期望，不改变中奖概率。"
    )
    lines.append(
        "- 双色球近5期同等开球偏好统计2+1和1+1，0+1不计入，因为只中蓝球重复较常见。"
    )
    lines.append("")
    lines.extend(
        [
        "## 六、层覆盖目标说明",
        "",
        "第1层要达到100%覆盖全部实际球，唯一办法是包含全部35/33个号码，那漏斗就失去收敛意义。",
        "当前第1层20个“至少命中1个”约99%，但不能保证5/6个全中；第2层、第3层同理。",
        "这里每一层都写真实覆盖概率，不承诺100%、50%、20%的固定目标。",
        "",
        "## 七、为什么不能提高单注概率",
        "",
        "在公平开奖下，每一注合法组合的头奖概率和任意奖概率都是固定常数。",
        "无论用贝叶斯、走势、冷热号还是位置定律，都无法改变单注概率。",
        "本流程只负责给出一注经过回测验证的确定推荐，不做“提高概率”的承诺。",
        "一等奖人数少不是“逻辑问题”，而是组合数太大：双色球总组合约1772万，即使卖出约1亿注，期望头奖人数也只有约5-6人。",
        "",
        "## 八、回测验证（这一注方法是否经得起考验）",
        "",
        "用同样的分层漏斗规则，在历史数据里逐期只用当期之前的数据生成一注，再对应当期开奖：",
        "",
        "| 项目 | 大乐透 | 双色球 |",
        "| --- | --- | --- |",
        "| 回测窗口数 | " + str(backtests["dlt"]["windows"]) + " | " + str(backtests["ssq"]["windows"]) + " |",
        "| 主区平均命中 | " + str(backtests["dlt"]["main_mean"]) + "（随机期望 0.714） | " + str(backtests["ssq"]["main_mean"]) + "（随机期望 1.091） |",
        "| 第1层20个平均命中 | " + str(backtests["dlt"]["layer1_mean"]) + "（随机期望 2.857） | " + str(backtests["ssq"]["layer1_mean"]) + "（随机期望 3.636） |",
        "| 第2层15个平均命中 | " + str(backtests["dlt"]["layer2_mean"]) + "（随机期望 2.143） | " + str(backtests["ssq"]["layer2_mean"]) + "（随机期望 2.727） |",
        "| 第3层平均命中 | " + str(backtests["dlt"]["layer3_mean"]) + "（随机期望 " + f"{5*dlt_l3/35:.3f}" + "） | " + str(backtests["ssq"]["layer3_mean"]) + "（随机期望 " + f"{6*ssq_l3/33:.3f}" + "） |",
        "| 后区命中率 | " + str(backtests["dlt"]["back_rate"]) + "（随机期望 0.333） | " + str(backtests["ssq"]["back_rate"]) + "（随机期望 0.063） |",
        "| 任意奖级命中率 | " + str(backtests["dlt"]["any_prize_rate"]) + "%（随机理论约6.67%） | " + str(backtests["ssq"]["any_prize_rate"]) + "%（随机理论约6.71%） |",
        "| 二项检验 p 值 | " + f"{dlt_pval:.2f}" + " | " + f"{ssq_pval:.2f}" + " |",
        "",
        "结论：",
        "- 如果命中率接近或略高于随机理论值，说明方法稳定、不依赖运气性采样，但仍在随机波动范围内；",
        "- 如果明显低于随机，说明该规则当前没有优势；回测数字会直接显示，不做粉饰。",
        "- p 值大于 0.05 表示差异不显著：当前回测能证明“方法稳定、不是随手乱编”，但不能证明“它能持续提高中奖率”。",
        "",
        "说明：彩票是独立随机事件，任何单注在开奖前等可能。这里给的是“经过历史回测的一注”，不是“必中一注”。",
        ]
    )
    marker = "## 一、贝叶斯定律在这里的作用"
    if marker in lines:
        idx = lines.index(marker)
        lines = lines[:idx] + reflection_lines(reflections) + lines[idx:]
    hist_note = []
    if dlt_pred.get("repeat_adjusted"):
        hist_note.append("- 大乐透：所选整注曾与历史开奖结果重复，已自动替换1个号码")
    if ssq_pred.get("repeat_adjusted"):
        hist_note.append("- 双色球：所选整注曾与历史开奖结果重复，已自动替换1个号码")
    if dlt_pred.get("recent_repeat_adjusted"):
        hist_note.append("- 大乐透：近5期曾命中相同低奖级2+1，已替换1个号码（偏好过滤，不提高概率）")
    if ssq_pred.get("recent_repeat_adjusted"):
        hist_note.append("- 双色球：近5期曾命中相同低奖级2+1，已替换1个号码（偏好过滤，不提高概率）")
    if dlt_pred.get("prize_repeat_adjusted"):
        hist_note.append("- 大乐透：所选整注曾按历史奖级命中过一至七等，已按距离偏好替换1个号码（含近5期六/七等奖）")
    if ssq_pred.get("prize_repeat_adjusted"):
        hist_note.append("- 双色球：所选整注曾按历史奖级命中过一至六等，已按距离偏好替换1个号码（六等奖偏好统计2+1和1+1，0+1不计入）")
    if hist_note:
        idx = lines.index("## 五、分层漏斗选号（20→15→8-10→单注）")
        lines = lines[:idx] + hist_note + [""] + lines[idx:]
    if method_rows:
        method_names = {
            "bayes_avg": "贝叶斯模型平均（主推）",
            "funnel": "我的分层分区方法（不改）",
            "hot": "短周期热度加权",
            "cold": "遗漏回归",
            "position": "位置分布后验",
            "random": "随机机选对照",
        }
        ml = [
            "## 四、全部方法对照（每方法附回测概率）",
            "",
            "| 方法 | 大乐透一注 | 大乐透回测 | 双色球一注 | 双色球回测 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in method_rows.get("dlt", []):
            m = item["method"]
            ssq_item = next(
                (x for x in method_rows.get("ssq", []) if x["method"] == m), None
            )
            dlt_rate = method_stats.get("dlt", {}).get(m, "-")
            ssq_rate = method_stats.get("ssq", {}).get(m, "-")
            label = method_names.get(m, m)
            ml.append(
                f"| {label} | {fmt_combo('dlt', item['combo'])} | "
                f"{dlt_rate}% | "
                f"{fmt_combo('ssq', ssq_item['combo']) if ssq_item else '-'} | "
                f"{ssq_rate}% |"
            )
        ml.append("")
        ml.append("### 六种方法各出一注")
        for item in method_rows.get("dlt", []):
            m = item["method"]
            ssq_item = next(
                (x for x in method_rows.get("ssq", []) if x["method"] == m), None
            )
            label = method_names.get(m, m)
            ml.append(
                f"- {label}：大乐透 {fmt_combo('dlt', item['combo'])}；"
                f"双色球 {fmt_combo('ssq', ssq_item['combo']) if ssq_item else '-'}"
            )
        ml.append("")
        ml.append("### 每个方法漏球分析（200期回测）")
        for item in method_rows.get("dlt", []):
            m = item["method"]
            label = method_names.get(m, m)
            dm = method_miss.get("dlt", {}).get(m, {})
            sm = method_miss.get("ssq", {}).get(m, {})

            def fmt_actual(miss):
                return "、".join(
                    f"{n:02d}号{c}次" for n, c in miss.get("missed_actual", [])[:5]
                ) or "无"

            def fmt_pred(miss):
                return "、".join(
                    f"{n:02d}号{c}次" for n, c in miss.get("missed_pred", [])[:5]
                ) or "无"

            ml.append(f"- {label}：")
            ml.append(
                f"  - 大乐透：最常漏掉的开奖球 {fmt_actual(dm)}；"
                f"最常漏掉的预测球 {fmt_pred(dm)}"
            )
            ml.append(
                f"  - 双色球：最常漏掉的开奖球 {fmt_actual(sm)}；"
                f"最常漏掉的预测球 {fmt_pred(sm)}"
            )
        ml.append("")
        ml.append("### 最新一期逐方法漏球分类")
        for game_key, game_name in (("dlt", "大乐透"), ("ssq", "双色球")):
            for item in method_rows.get(game_key, []):
                m = item["method"]
                info = latest_miss.get(game_key, {}).get(m, {})
                if not info:
                    continue
                label = method_names.get(m, m)
                hit = "、".join(f"{n:02d}" for n in info.get("hit_pred", [])) or "无"
                miss = "、".join(f"{n:02d}" for n in info.get("missed_pred", [])) or "无"
                miss_actual = "；".join(
                    f"{d['ball']:02d}号（{d.get('zone', '')}{d['stage']}）"
                    for d in info.get("actual_miss", [])
                ) or "无"
                ml.append(
                    f"- {label} {game_name}：中的球 {hit}；没中的预测球 {miss}；"
                    f"漏掉的开奖球 {miss_actual}"
                )
        idx = lines.index("## 五、分层漏斗选号（20→15→8-10→单注）")
        lines = lines[:idx] + ml + [""] + lines[idx:]
    trend_lines = [
        "",
        "## 十、走势与冷热参考（只作观察，不参与真实概率）",
        "",
        "### 大乐透",
        "- 前区近30期最热：" + "  ".join(n2(x) for x in top_nums(dlt_main["features"], "count_30")),
        "- 前区当前遗漏最长：" + "  ".join(n2(x) for x in top_nums(dlt_main["features"], "gap")),
        "- 前区近5期活跃：" + "  ".join(n2(x) for x in top_nums(dlt_main["features"], "recent5")),
        "- 前区位置最大可能（历史）：" + "、".join(
            f"第{p + 1}位 {n2(mode)}" for p, mode in enumerate(dlt_main["position_modes"])
        ),
        "- 后区近30期最热：" + "  ".join(n2(x) for x in top_nums(dlt_back["features"], "count_30")),
        "- 后区当前遗漏最长：" + "  ".join(n2(x) for x in top_nums(dlt_back["features"], "gap")),
        "- 后区位置最大可能（历史）：" + "、".join(
            f"第{p + 1}位 {n2(mode)}" for p, mode in enumerate(dlt_back["position_modes"])
        ),
    ]
    trend_lines.extend(feature_lines(dlt_main, dlt_combo[0], "前区"))
    trend_lines.extend(position_lines(dlt_main, dlt_combo[0], "前区"))
    trend_lines.extend(feature_lines(dlt_back, dlt_combo[1], "后区"))
    trend_lines.extend(position_lines(dlt_back, dlt_combo[1], "后区"))
    trend_lines.extend(
        [
            "",
            "### 双色球",
            "- 红球近30期最热：" + "  ".join(n2(x) for x in top_nums(ssq_main["features"], "count_30")),
            "- 红球当前遗漏最长：" + "  ".join(n2(x) for x in top_nums(ssq_main["features"], "gap")),
            "- 红球近5期活跃：" + "  ".join(n2(x) for x in top_nums(ssq_main["features"], "recent5")),
            "- 红球位置最大可能（历史）：" + "、".join(
                f"第{p + 1}位 {n2(mode)}" for p, mode in enumerate(ssq_main["position_modes"])
            ),
            "- 蓝球近30期最热：" + "  ".join(n2(x) for x in top_nums(ssq_back["features"], "count_30")),
            "- 蓝球当前遗漏最长：" + "  ".join(n2(x) for x in top_nums(ssq_back["features"], "gap")),
            "- 蓝球位置最大可能（历史）：第1位 " + n2(ssq_back["position_modes"][0]),
        ]
    )
    trend_lines.extend(feature_lines(ssq_main, ssq_combo[0], "红球"))
    trend_lines.extend(position_lines(ssq_main, ssq_combo[0], "红球"))
    trend_lines.extend(feature_lines(ssq_back, list(ssq_combo[1]), "蓝球"))
    trend_lines.extend(position_lines(ssq_back, list(ssq_combo[1]), "蓝球"))
    if backtests.get("dlt") and backtests.get("ssq"):
        dlt_l3 = backtests["dlt"].get("layer3_mean")
        dlt_final = backtests["dlt"].get("main_mean")
        ssq_l3 = backtests["ssq"].get("layer3_mean")
        ssq_final = backtests["ssq"].get("main_mean")
        diag = [
            "## 九、偏差诊断",
            "",
            f"- 大乐透：第3层平均包含实际号码 {dlt_l3} 个，最终一注平均命中 {dlt_final} 个，"
            f"最终选号阶段漏掉约 {dlt_l3 - dlt_final:.3f} 个。",
            f"- 双色球：第3层平均包含实际号码 {ssq_l3} 个，最终一注平均命中 {ssq_final} 个，"
            f"最终选号阶段漏掉约 {ssq_l3 - ssq_final:.3f} 个。",
            "- 结论：主要偏差不在前几层筛选，而在最后从候选主里选一注这一步。",
            "- 为什么没中一等奖：头奖概率固定，200期回测期望一等奖约0次；没中不是选球错误，而是数学概率。",
            "- 建议：如果只买一注，应扩大最终候选范围并加入多样性；如果给客户，使用210注覆盖方案。",
            "",
        ]
        trend_lines = diag + trend_lines
    lines.extend(trend_lines)
    out = BASE / f"本期预测_{config['generated_at'][:10]}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def random_draw(rng, game):
    if game == "dlt":
        return (
            tuple(sorted(rng.sample(range(1, 36), 5))),
            tuple(sorted(rng.sample(range(1, 13), 2))),
        )
    return (
        tuple(sorted(rng.sample(range(1, 34), 6))),
        rng.randint(1, 16),
    )


def ticket_wins(game, ticket, draw):
    if game == "dlt":
        fh = len(set(ticket[0]) & set(draw[0]))
        bh = len(set(ticket[1]) & set(draw[1]))
        return dlt_win(fh, bh)
    rh = len(set(ticket[0]) & set(draw[0]))
    bh = ticket[1][0] == draw[1]
    return ssq_win(rh, bh)


def make_pack(game, zones, n, seed):
    rng = random.Random(seed)
    seen = set()
    pack = []
    while len(pack) < n:
        if game == "dlt":
            front = tuple(sorted(rng.sample(range(1, 36), 5)))
            back = tuple(sorted(rng.sample(range(1, 13), 2)))
            key = (front, back)
        else:
            red = tuple(sorted(rng.sample(range(1, 34), 6)))
            blue = (rng.randint(1, 16),)
            key = (red, blue)
        if key in seen:
            continue
        seen.add(key)
        pack.append(key)
    return pack


def simulate_pack(game, pack, trials, seed):
    rng = random.Random(seed)
    wins = 0
    for _ in range(trials):
        draw = random_draw(rng, game)
        for ticket in pack:
            if ticket_wins(game, ticket, draw):
                wins += 1
                break
    return wins / trials


def coverage_plan(game, zones, target=0.60, trials=120000):
    dlt_p, ssq_p = single_any_prize()
    p_single = dlt_p if game == "dlt" else ssq_p
    n0 = max(1, math.ceil(math.log(1 - target) / math.log(1 - p_single)))
    for n in range(n0, n0 + 10):
        pack = make_pack(game, zones, n, seed=SIM_SEED + (0 if game == "dlt" else 1))
        p = simulate_pack(game, pack, trials, seed=SIM_SEED + 10)
        if p >= target:
            return n, p, pack
    n = n0 + 10
    pack = make_pack(game, zones, n, seed=SIM_SEED + (0 if game == "dlt" else 1))
    p = simulate_pack(game, pack, trials, seed=SIM_SEED + 10)
    return n, p, pack


def fmt_combo(game, ticket):
    if game == "dlt":
        return "  ".join(f"{x:02d}" for x in ticket[0]) + "  +  " + "  ".join(f"{x:02d}" for x in ticket[1])
    return "  ".join(f"{x:02d}" for x in ticket[0]) + "  +  " + f"{ticket[1][0]:02d}"


def write_prediction_summary(result, config, plans):
    dlt_first = result["combos"]["dlt"]["per_issue"][0]
    ssq_first = result["combos"]["ssq"]["per_issue"][0]
    dlt_date = next(s["date"] for s in config["dlt_schedule"] if s["issue"] == dlt_first["issue"])
    ssq_date = next(s["date"] for s in config["ssq_schedule"] if s["issue"] == ssq_first["issue"])

    dlt_p, ssq_p = single_any_prize()
    dlt_total = comb(35, 5) * comb(12, 2)
    ssq_total = comb(33, 6) * 16
    dlt_60_jackpot = math.ceil(dlt_total * 0.6)
    ssq_60_jackpot = math.ceil(ssq_total * 0.6)

    lines = [
        "# 本期预测（一键生成）",
        "",
        f"生成时间：{config['generated_at']}",
        f"最新大乐透：{config['dlt_latest']['issue']}期 · {config['dlt_latest']['result']}",
        f"最新双色球：{config['ssq_latest']['issue']}期 · {config['ssq_latest']['result']}",
        "",
        "## 一、大乐透本期主推",
        f"期号：{dlt_first['issue']} · {dlt_date}",
        "主推：" + fmt_combo("dlt", (dlt_first["combo"]["front"], dlt_first["combo"]["back"])),
        "单注头奖概率：1/" + f"{dlt_total:,}",
        "单注任意奖概率：" + f"{dlt_p*100:.2f}%",
        "",
        "## 二、双色球本期主推",
        f"期号：{ssq_first['issue']} · {ssq_date}",
        "主推：" + fmt_combo("ssq", (ssq_first["combo"]["red"], ssq_first["combo"]["blue"])),
        "单注头奖概率：1/" + f"{ssq_total:,}",
        "单注任意奖概率：" + f"{ssq_p*100:.2f}%",
        "",
        "## 三、60% 覆盖计划（至少中任意奖级一次）",
        f"大乐透：{plans['dlt']['n']} 注，约 {plans['dlt']['n']*2} 元，模拟概率约 {plans['dlt']['p']*100:.1f}%",
    ]
    for i, ticket in enumerate(plans["dlt"]["pack"], 1):
        lines.append(f"  {i:02d}. {fmt_combo('dlt', ticket)}")
    lines.extend(
        [
            "",
        f"双色球：{plans['ssq']['n']} 注，约 {plans['ssq']['n']*2} 元，模拟概率约 {plans['ssq']['p']*100:.1f}%",
        ]
    )
    for i, ticket in enumerate(plans["ssq"]["pack"], 1):
        lines.append(f"  {i:02d}. {fmt_combo('ssq', ticket)}")
    lines.extend(
        [
        "",
        "## 四、如果目标是“头奖概率 60%”",
        f"大乐透：需覆盖约 {dlt_60_jackpot:,} 注，约 {dlt_60_jackpot*2:,} 元",
        f"双色球：需覆盖约 {ssq_60_jackpot:,} 注，约 {ssq_60_jackpot*2:,} 元",
        "",
        "说明：彩票是独立随机事件，单注概率无法通过改号提高；",
        "这里的 60% 是通过购买更多不同合法组合实现的覆盖概率，不是对某一注的预测保证。",
        ]
    )
    out = BASE / f"本期预测_{config['generated_at'][:10]}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def print_plan(game, plan):
    print(f"{'大乐透' if game == 'dlt' else '双色球'} 60% 覆盖计划：")
    print(f"  注数：{plan['n']} 注，约 {plan['n'] * 2} 元")
    print(f"  模拟“至少中任意奖级”概率：{plan['p'] * 100:.1f}%")
    print("  推荐组合：")
    for i, ticket in enumerate(plan["pack"], 1):
        print(f"    {i:02d}. {fmt_combo(game, ticket)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true", help="服务器环境，不生成 Word/PDF")
    args = parser.parse_args()
    print("=" * 60)
    print("一键生成本期预测")
    print("=" * 60)

    print("==> 存档上一期预测（用于开奖后反思）")
    save_pending_predictions()

    try:
        config = update_data_and_config()
    except Exception as exc:
        print("官方数据拉取失败，将使用本地已有数据继续：", exc)
        with open(CONFIG_PATH, encoding="utf-8") as f:
            config = json.load(f)

    dlt_rows = load_rows(DATA_DIR / "dlt_history_500.json")
    ssq_rows = load_rows(DATA_DIR / "ssq_history_500.json")

    print("==> 上一期反思与小调整")
    reflections = reflect_previous_draws({"dlt": dlt_rows, "ssq": ssq_rows})
    for ref in reflections:
        print(
            f"{ref['issue']}期：主区命中 {ref['main_hits']}，"
            f"候选池覆盖 {ref['main_overlap']}，原因：{'；'.join(ref['reasons'])}"
        )

    print("==> 生成下一期一注（分层漏斗 20→15→8-10→单注）")
    dlt_train = rows_oldest_first(dlt_rows[1:])
    ssq_train = rows_oldest_first(ssq_rows[1:])
    dlt_pred = pick_funnel_combo("dlt", dlt_train)
    ssq_pred = pick_funnel_combo("ssq", ssq_train)
    method_rows = {
        "dlt": all_method_tickets("dlt", dlt_train),
        "ssq": all_method_tickets("ssq", ssq_train),
    }
    method_stats = {"dlt": {}, "ssq": {}}
    method_miss = {"dlt": {}, "ssq": {}}
    latest_miss = {"dlt": {}, "ssq": {}}
    for game, rows in (("dlt", dlt_rows), ("ssq", ssq_rows)):
        latest_miss[game] = analyze_latest_miss(game, rows)
        for item in method_rows[game]:
            method_stats[game][item["method"]] = backtest_method(game, rows, item["method"])
            method_miss[game][item["method"]] = backtest_method_miss(game, rows, item["method"])
    if args.headless:
        save_json_file(
            BASE / "method_comparison.json",
            {
                "rows": method_rows,
                "stats": method_stats,
            },
        )
        save_json_file(BASE / "method_miss.json", method_miss)
        save_json_file(BASE / "latest_miss.json", latest_miss)
    print("大乐透一注：", fmt_combo("dlt", dlt_pred["combo"]))
    print("双色球一注：", fmt_combo("ssq", ssq_pred["combo"]))

    override = {
        "dlt": {
            "issue": config["dlt_future"][0],
            "combo": {
                "front": list(dlt_pred["combo"][0]),
                "back": list(dlt_pred["combo"][1]),
            },
        },
        "ssq": {
            "issue": config["ssq_future"][0],
            "combo": {
                "red": list(ssq_pred["combo"][0]),
                "blue": list(ssq_pred["combo"][1]),
            },
        },
    }
    with open(BASE / "next_bayes_combos.json", "w", encoding="utf-8") as f:
        json.dump(override, f, ensure_ascii=False, indent=2)

    if not args.headless:
        run_analysis_and_report()

    print("==> 历史回测验证")
    backtests = {
        "dlt": backtest_bayes("dlt", dlt_rows),
        "ssq": backtest_bayes("ssq", ssq_rows),
    }
    print("大乐透回测：", backtests["dlt"])
    print("双色球回测：", backtests["ssq"])
    if args.headless:
        save_json_file(
            BASE / "mobile_backtest.json",
            {
                "dlt": backtests["dlt"],
                "ssq": backtests["ssq"],
            },
        )

    summary_path = write_next_prediction(config, dlt_pred, ssq_pred, backtests, reflections, method_rows, method_stats, method_miss, latest_miss)
    print("==> 本期预测已保存：", summary_path)
    print("==> 全部完成")


if __name__ == "__main__":
    main()
