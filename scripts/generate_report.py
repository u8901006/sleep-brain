#!/usr/bin/env python3
"""
Generate sleep medicine daily report HTML using Zhipu AI.
Reads papers JSON, analyzes with AI, generates styled HTML.
"""
import json
import sys
import os
import re
import time
import argparse
from datetime import datetime, timezone, timedelta
import httpx

API_BASE = os.environ.get(
    "ZHIPU_API_BASE", "https://open.bigmodel.cn/api/coding/paas/v4"
)
FALLBACK_MODELS = ["GLM-5.1", "GLM-5-Turbo", "GLM-4.7", "GLM-4.7-Flash"]

SYSTEM_PROMPT = (
    "你是睡眠醫學領域的資深研究員與科學傳播者。你的任務是：\n"
    "1. 從提供的醫學文獻中，篩選出最具臨床意義與研究價值的論文\n"
    "2. 對每篇論文進行繁體中文摘要、分類、PICO 分析\n"
    "3. 評估其臨床實用性（高/中/低）\n"
    "4. 生成適合醫療專業人員閱讀的日報\n\n"
    "輸出格式要求：\n"
    "- 語言：繁體中文（台灣用語）\n"
    "- 專業但易懂\n"
    "- 每篇論文需包含：中文標題、一句話總結、PICO分析、臨床實用性、分類標籤\n"
    "- 最後提供今日精選 TOP 3（最重要/最影響臨床實踐的論文）\n"
    "回傳格式必須是純 JSON，不要用 markdown code block 包裹。"
)


def load_papers(input_path: str) -> dict:
    if input_path == "-":
        data = json.load(sys.stdin)
    else:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    return data


def extract_json_from_text(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1:]
        else:
            text = text[3:]
        text = text.rstrip("`").strip()
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    brace_match = re.search(r"\{[\s\S]*\}", text)
    if brace_match:
        text = brace_match.group(0)
    bracket_match = re.search(r"\[[\s\S]*\]", text)
    if bracket_match and not brace_match:
        text = bracket_match.group(0)
    text = re.sub(r',\s*([}\]])', r'\1', text)
    text = re.sub(r'[\x00-\x1f\x7f]', ' ', text)
    return json.loads(text)


def analyze_papers(api_key: str, papers_data: dict) -> dict:
    tz_taipei = timezone(timedelta(hours=8))
    date_str = papers_data.get("date", datetime.now(tz_taipei).strftime("%Y-%m-%d"))
    paper_count = papers_data.get("count", 0)
    papers_text = json.dumps(
        papers_data.get("papers", []), ensure_ascii=False, indent=2
    )

    prompt = f"""以下是 {date_str} 從 PubMed 抓取的最新睡眠醫學文獻（共 {paper_count} 篇）。
請進行以下分析，並以 JSON 格式回傳（不要用 markdown code block）：
{{
"date": "{date_str}",
"market_summary": "1-2句話總結今天文獻的整體趨勢與亮點",
"top_picks": [
{{
"rank": 1,
"title_zh": "中文標題",
"title_en": "English Title",
"journal": "期刊名",
"summary": "一句話總結（繁體中文，點出核心發現與臨床意義）",
"pico": {{
"population": "研究對象",
"intervention": "介入措施",
"comparison": "對照組",
"outcome": "主要結果"
}},
"clinical_utility": "高/中/低",
"utility_reason": "為什麼實用的一句話說明",
"tags": ["標籤1", "標籤2"],
"url": "原文連結",
"emoji": "相關emoji"
}}
],
"all_papers": [
{{
"title_zh": "中文標題",
"title_en": "English Title",
"journal": "期刊名",
"summary": "一句話總結",
"clinical_utility": "高/中/低",
"tags": ["標籤1"],
"url": "連結",
"emoji": "emoji"
}}
],
"keywords": ["關鍵字1", "關鍵字2"],
"topic_distribution": {{
"失眠": 3,
"睡眠呼吸中止症": 2
}}
}}

原始文獻資料：
{papers_text}

請篩選出最重要的 TOP 5-8 篇論文放入 top_picks（按重要性排序），其餘放入 all_papers。
每篇 paper 的 tags 請從以下選擇：失眠、睡眠呼吸中止症、晝夜節律障礙、嗜睡症、異睡症、不寧腿症候群、CBT-I、睡眠呼吸生理、睡眠剝奪、睡眠結構、REM睡眠行為障礙、褪黑激素、輪班工作、兒童睡眠、睡眠型態、多眠症、體動記錄、慢波睡眠、腦膠淋巴系統、食慾素、睡眠神經科學、睡眠與精神醫學、睡眠公共衛生、生物節律、睡眠科技、睡眠與認知、打鼾。
記住：回傳純 JSON，不要用 ```json``` 包裹。"""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for model in FALLBACK_MODELS:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "top_p": 0.9,
            "max_tokens": 100000,
        }
        for attempt in range(3):
            try:
                print(
                    f"[INFO] Trying {model} (attempt {attempt + 1})...",
                    file=sys.stderr,
                )
                resp = httpx.post(
                    f"{API_BASE}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=660,
                )
                if resp.status_code == 429:
                    wait = 60 * (attempt + 1)
                    print(
                        f"[WARN] Rate limited, waiting {wait}s...",
                        file=sys.stderr,
                    )
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                text = data["choices"][0]["message"]["content"].strip()
                result = extract_json_from_text(text)
                print(
                    f"[INFO] Analysis complete with {model}: "
                    f"{len(result.get('top_picks', []))} top picks, "
                    f"{len(result.get('all_papers', []))} total",
                    file=sys.stderr,
                )
                result["_model_used"] = model
                return result
            except json.JSONDecodeError as e:
                print(
                    f"[WARN] JSON parse failed on attempt {attempt + 1} with {model}: {e}",
                    file=sys.stderr,
                )
                if attempt < 2:
                    time.sleep(5)
                    continue
            except httpx.HTTPStatusError as e:
                print(
                    f"[ERROR] HTTP {e.response.status_code}: {e.response.text[:200]}",
                    file=sys.stderr,
                )
                if e.response.status_code == 429:
                    wait = 60 * (attempt + 1)
                    time.sleep(wait)
                    continue
                break
            except httpx.TimeoutException:
                print(
                    f"[WARN] Timeout on attempt {attempt + 1} with {model}",
                    file=sys.stderr,
                )
                if attempt < 2:
                    time.sleep(10)
                    continue
            except Exception as e:
                print(f"[ERROR] {model} failed: {e}", file=sys.stderr)
                break
    print("[ERROR] All models and attempts failed", file=sys.stderr)
    return None


def generate_html(analysis: dict) -> str:
    tz_taipei = timezone(timedelta(hours=8))
    date_str = analysis.get(
        "date", datetime.now(tz_taipei).strftime("%Y-%m-%d")
    )
    date_parts = date_str.split("-")
    if len(date_parts) == 3:
        date_display = (
            f"{date_parts[0]}年{int(date_parts[1])}月{int(date_parts[2])}日"
        )
    else:
        date_display = date_str
    summary = analysis.get("market_summary", "")
    top_picks = analysis.get("top_picks", [])
    all_papers = analysis.get("all_papers", [])
    keywords = analysis.get("keywords", [])
    topic_dist = analysis.get("topic_distribution", {})
    model_used = analysis.get("_model_used", "GLM-5.1")
    total_count = len(top_picks) + len(all_papers)

    top_picks_html = ""
    for pick in top_picks:
        tags_html = "".join(
            f'<span class="tag">{t}</span>' for t in pick.get("tags", [])
        )
        util = pick.get("clinical_utility", "中")
        utility_class = (
            "utility-high"
            if util == "高"
            else ("utility-mid" if util == "中" else "utility-low")
        )
        pico = pick.get("pico", {})
        pico_html = ""
        if pico:
            pico_html = f"""
            <div class="pico-grid">
              <div class="pico-item"><span class="pico-label">P</span><span class="pico-text">{pico.get("population", "-")}</span></div>
              <div class="pico-item"><span class="pico-label">I</span><span class="pico-text">{pico.get("intervention", "-")}</span></div>
              <div class="pico-item"><span class="pico-label">C</span><span class="pico-text">{pico.get("comparison", "-")}</span></div>
              <div class="pico-item"><span class="pico-label">O</span><span class="pico-text">{pico.get("outcome", "-")}</span></div>
            </div>
          """
        top_picks_html += f"""
        <div class="news-card featured">
          <div class="card-header">
            <span class="rank-badge">#{pick.get("rank", "")}</span>
            <span class="emoji-icon">{pick.get("emoji", "📄")}</span>
            <span class="{utility_class}">{util}實用性</span>
          </div>
          <h3>{pick.get("title_zh", pick.get("title_en", ""))}</h3>
          <p class="journal-source">{pick.get("journal", "")} &middot; {pick.get("title_en", "")}</p>
          <p>{pick.get("summary", "")}</p>
          {pico_html}
          <div class="card-footer">
            {tags_html}
            <a href="{pick.get("url", "#")}" target="_blank">閱讀原文 →</a>
          </div>
        </div>
        """

    all_papers_html = ""
    for paper in all_papers:
        tags_html = "".join(
            f'<span class="tag">{t}</span>' for t in paper.get("tags", [])
        )
        util = paper.get("clinical_utility", "中")
        utility_class = (
            "utility-high"
            if util == "高"
            else ("utility-mid" if util == "中" else "utility-low")
        )
        all_papers_html += f"""
        <div class="news-card">
          <div class="card-header-row">
            <span class="emoji-sm">{paper.get("emoji", "📄")}</span>
            <span class="{utility_class} utility-sm">{util}</span>
          </div>
          <h3>{paper.get("title_zh", paper.get("title_en", ""))}</h3>
          <p class="journal-source">{paper.get("journal", "")}</p>
          <p>{paper.get("summary", "")}</p>
          <div class="card-footer">
            {tags_html}
            <a href="{paper.get("url", "#")}" target="_blank">PubMed →</a>
          </div>
        </div>
        """

    keywords_html = "".join(
        f'<span class="keyword">{k}</span>' for k in keywords
    )

    topic_bars_html = ""
    if topic_dist:
        max_count = max(topic_dist.values()) if topic_dist else 1
        for topic, count in topic_dist.items():
            width_pct = int((count / max_count) * 100)
            topic_bars_html += f"""
            <div class="topic-row">
              <span class="topic-name">{topic}</span>
              <div class="topic-bar-bg"><div class="topic-bar" style="width:{width_pct}%"></div></div>
              <span class="topic-count">{count}</span>
            </div>
            """

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Sleep Brain &middot; 睡眠醫學文獻日報 &middot; {date_display}</title>
<meta name="description" content="{date_display} 睡眠醫學文獻日報，由 AI 自動彙整 PubMed 最新論文"/>
<style>
  :root {{ --bg: #0d1b2a; --surface: #1b2838; --line: #2a3f55; --text: #e0e6ed; --muted: #8899aa; --accent: #00b4d8; --accent-soft: rgba(0,180,216,0.12); --card-bg: rgba(27,40,56,0.92); --glow: rgba(0,180,216,0.15); }}
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: linear-gradient(135deg, #0d1b2a 0%, #1b2838 40%, #162447 100%); color: var(--text); font-family: "Noto Sans TC", "PingFang TC", "Helvetica Neue", Arial, sans-serif; min-height: 100vh; overflow-x: hidden; }}
  body::before {{ content: ""; position: fixed; top: -50%; left: -50%; width: 200%; height: 200%; background: radial-gradient(circle at 30% 20%, rgba(0,180,216,0.04) 0%, transparent 50%), radial-gradient(circle at 70% 80%, rgba(72,149,239,0.03) 0%, transparent 50%); z-index: 0; pointer-events: none; }}
  .container {{ position: relative; z-index: 1; max-width: 880px; margin: 0 auto; padding: 60px 32px 80px; }}
  header {{ display: flex; align-items: center; gap: 16px; margin-bottom: 52px; animation: fadeDown 0.6s ease both; }}
  .logo {{ width: 48px; height: 48px; border-radius: 14px; background: linear-gradient(135deg, var(--accent), #4895ef); display: flex; align-items: center; justify-content: center; font-size: 22px; flex-shrink: 0; box-shadow: 0 4px 20px rgba(0,180,216,0.3); }}
  .header-text h1 {{ font-size: 22px; font-weight: 700; color: var(--text); letter-spacing: -0.3px; }}
  .header-meta {{ display: flex; gap: 8px; margin-top: 6px; flex-wrap: wrap; align-items: center; }}
  .badge {{ display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 11px; letter-spacing: 0.3px; }}
  .badge-date {{ background: var(--accent-soft); border: 1px solid rgba(0,180,216,0.3); color: var(--accent); }}
  .badge-count {{ background: rgba(0,180,216,0.06); border: 1px solid var(--line); color: var(--muted); }}
  .badge-source {{ background: transparent; color: var(--muted); font-size: 11px; padding: 0 4px; }}
  .summary-card {{ background: var(--card-bg); border: 1px solid var(--line); border-radius: 24px; padding: 28px 32px; margin-bottom: 32px; box-shadow: 0 20px 60px rgba(0,0,0,0.2), 0 0 40px var(--glow); animation: fadeUp 0.5s ease 0.1s both; }}
  .summary-card h2 {{ font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.6px; color: var(--accent); margin-bottom: 16px; }}
  .summary-text {{ font-size: 15px; line-height: 1.8; color: var(--text); }}
  .section {{ margin-bottom: 36px; animation: fadeUp 0.5s ease both; }}
  .section-title {{ display: flex; align-items: center; gap: 10px; font-size: 17px; font-weight: 700; color: var(--text); margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--line); }}
  .section-icon {{ width: 28px; height: 28px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 14px; flex-shrink: 0; background: var(--accent-soft); }}
  .news-card {{ background: var(--card-bg); border: 1px solid var(--line); border-radius: 24px; padding: 22px 26px; margin-bottom: 12px; box-shadow: 0 8px 30px rgba(0,0,0,0.15); transition: background 0.2s, border-color 0.2s, transform 0.2s; }}
  .news-card:hover {{ transform: translateY(-2px); box-shadow: 0 12px 40px rgba(0,180,216,0.1); border-color: rgba(0,180,216,0.3); }}
  .news-card.featured {{ border-left: 3px solid var(--accent); }}
  .news-card.featured:hover {{ border-color: var(--accent); }}
  .card-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }}
  .rank-badge {{ background: linear-gradient(135deg, var(--accent), #4895ef); color: #fff; font-weight: 700; font-size: 12px; padding: 2px 8px; border-radius: 6px; }}
  .emoji-icon {{ font-size: 18px; }}
  .card-header-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
  .emoji-sm {{ font-size: 14px; }}
  .news-card h3 {{ font-size: 15px; font-weight: 600; color: var(--text); margin-bottom: 8px; line-height: 1.5; }}
  .journal-source {{ font-size: 12px; color: var(--accent); margin-bottom: 8px; opacity: 0.8; }}
  .news-card p {{ font-size: 13.5px; line-height: 1.75; color: var(--muted); }}
  .card-footer {{ margin-top: 12px; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }}
  .tag {{ padding: 2px 9px; background: var(--accent-soft); border-radius: 999px; font-size: 11px; color: var(--accent); }}
  .news-card a {{ font-size: 12px; color: var(--accent); text-decoration: none; opacity: 0.7; margin-left: auto; }}
  .news-card a:hover {{ opacity: 1; }}
  .utility-high {{ color: #4ade80; font-size: 11px; font-weight: 600; padding: 2px 8px; background: rgba(74,222,128,0.1); border-radius: 4px; }}
  .utility-mid {{ color: #fbbf24; font-size: 11px; font-weight: 600; padding: 2px 8px; background: rgba(251,191,36,0.1); border-radius: 4px; }}
  .utility-low {{ color: var(--muted); font-size: 11px; font-weight: 600; padding: 2px 8px; background: rgba(136,153,170,0.08); border-radius: 4px; }}
  .utility-sm {{ font-size: 10px; }}
  .pico-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px; padding: 12px; background: rgba(13,27,42,0.6); border-radius: 14px; border: 1px solid var(--line); }}
  .pico-item {{ display: flex; gap: 8px; align-items: baseline; }}
  .pico-label {{ font-size: 10px; font-weight: 700; color: #fff; background: var(--accent); padding: 2px 6px; border-radius: 4px; flex-shrink: 0; }}
  .pico-text {{ font-size: 12px; color: var(--muted); line-height: 1.4; }}
  .keywords-section {{ margin-bottom: 36px; }}
  .keywords {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }}
  .keyword {{ padding: 5px 14px; background: var(--accent-soft); border: 1px solid var(--line); border-radius: 20px; font-size: 12px; color: var(--accent); cursor: default; transition: background 0.2s; }}
  .keyword:hover {{ background: rgba(0,180,216,0.2); }}
  .topic-section {{ margin-bottom: 36px; }}
  .topic-row {{ display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }}
  .topic-name {{ font-size: 13px; color: var(--muted); width: 120px; flex-shrink: 0; text-align: right; }}
  .topic-bar-bg {{ flex: 1; height: 8px; background: var(--line); border-radius: 4px; overflow: hidden; }}
  .topic-bar {{ height: 100%; background: linear-gradient(90deg, var(--accent), #4895ef); border-radius: 4px; transition: width 0.6s ease; }}
  .topic-count {{ font-size: 12px; color: var(--accent); width: 24px; }}
  .clinic-banner {{ margin-top: 48px; animation: fadeUp 0.5s ease 0.4s both; }}
  .clinic-links {{ display: flex; flex-direction: column; gap: 10px; }}
  .clinic-link {{ display: flex; align-items: center; gap: 14px; padding: 18px 24px; background: var(--card-bg); border: 1px solid var(--line); border-radius: 24px; text-decoration: none; color: var(--text); transition: all 0.2s; box-shadow: 0 8px 30px rgba(0,0,0,0.15); }}
  .clinic-link:hover {{ border-color: var(--accent); transform: translateY(-2px); box-shadow: 0 12px 40px rgba(0,180,216,0.1); }}
  .clinic-icon {{ font-size: 28px; flex-shrink: 0; }}
  .clinic-name {{ font-size: 15px; font-weight: 700; color: var(--text); flex: 1; }}
  .clinic-arrow {{ font-size: 18px; color: var(--accent); font-weight: 700; }}
  .newsletter-desc {{ font-size: 12px; color: var(--muted); font-weight: 400; }}
  footer {{ margin-top: 32px; padding-top: 22px; border-top: 1px solid var(--line); font-size: 11.5px; color: var(--muted); display: flex; justify-content: space-between; animation: fadeUp 0.5s ease 0.5s both; }}
  footer a {{ color: var(--muted); text-decoration: none; }}
  footer a:hover {{ color: var(--accent); }}
  @keyframes fadeDown {{ from {{ opacity: 0; transform: translateY(-16px); }} to {{ opacity: 1; transform: translateY(0); }} }}
  @keyframes fadeUp {{ from {{ opacity: 0; transform: translateY(16px); }} to {{ opacity: 1; transform: translateY(0); }} }}
  @media (max-width: 600px) {{ .container {{ padding: 36px 18px 60px; }} .summary-card, .news-card {{ padding: 20px 18px; }} .pico-grid {{ grid-template-columns: 1fr; }} footer {{ flex-direction: column; gap: 6px; text-align: center; }} .topic-name {{ width: 80px; font-size: 11px; }} .clinic-links {{ flex-direction: column; }} }}
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="logo">😴</div>
    <div class="header-text">
      <h1>Sleep Brain &middot; 睡眠醫學文獻日報</h1>
      <div class="header-meta">
        <span class="badge badge-date">📅 {date_display}</span>
        <span class="badge badge-count">📊 {total_count} 篇文獻</span>
        <span class="badge badge-source">Powered by PubMed + Zhipu AI</span>
      </div>
    </div>
  </header>

  <div class="summary-card">
    <h2>📋 今日文獻趨勢</h2>
    <p class="summary-text">{summary}</p>
  </div>

  {"<div class='section'><div class='section-title'><span class='section-icon'>⭐</span>今日精選 TOP Picks</div>" + top_picks_html + "</div>" if top_picks_html else ""}

  {"<div class='section'><div class='section-title'><span class='section-icon'>📚</span>其他值得關注的文獻</div>" + all_papers_html + "</div>" if all_papers_html else ""}

  {"<div class='topic-section section'><div class='section-title'><span class='section-icon'>📊</span>主題分佈</div>" + topic_bars_html + "</div>" if topic_bars_html else ""}

  {"<div class='keywords-section section'><div class='section-title'><span class='section-icon'>🏷️</span>關鍵字</div><div class='keywords'>" + keywords_html + "</div></div>" if keywords_html else ""}

  <div class="clinic-banner">
    <div class="clinic-links">
      <a href="https://www.leepsyclinic.com/" class="clinic-link" target="_blank">
        <span class="clinic-icon">🏥</span>
        <span class="clinic-name">李政洋身心診所首頁</span>
        <span class="clinic-arrow">→</span>
      </a>
      <a href="https://blog.leepsyclinic.com/" class="clinic-link" target="_blank">
        <span class="clinic-icon">📬</span>
        <span class="clinic-name">訂閱電子報 <span class="newsletter-desc">· 掌握最新睡眠醫學資訊</span></span>
        <span class="clinic-arrow">→</span>
      </a>
    </div>
  </div>

  <footer>
    <span>資料來源：PubMed &middot; 分析模型：{model_used}</span>
    <span><a href="https://github.com/u8901006/sleep-brain">GitHub</a></span>
  </footer>
</div>
</body>
</html>"""
    return html


def main():
    parser = argparse.ArgumentParser(
        description="Generate sleep medicine daily report HTML"
    )
    parser.add_argument("--input", required=True, help="Input papers JSON file")
    parser.add_argument("--output", required=True, help="Output HTML file")
    parser.add_argument(
        "--api-key",
        default=os.environ.get("ZHIPU_API_KEY", ""),
        help="Zhipu API key",
    )
    args = parser.parse_args()
    if not args.api_key:
        print(
            "[ERROR] No API key provided. Set ZHIPU_API_KEY env var or use --api-key",
            file=sys.stderr,
        )
        sys.exit(1)
    papers_data = load_papers(args.input)
    if not papers_data or not papers_data.get("papers"):
        print(
            "[WARN] No papers found, generating empty report", file=sys.stderr
        )
        tz_taipei = timezone(timedelta(hours=8))
        analysis = {
            "date": datetime.now(tz_taipei).strftime("%Y-%m-%d"),
            "market_summary": "今日 PubMed 暫無新的睡眠醫學文獻更新。請明天再查看。",
            "top_picks": [],
            "all_papers": [],
            "keywords": [],
            "topic_distribution": {},
        }
    else:
        analysis = analyze_papers(args.api_key, papers_data)
    if not analysis:
        print(
            "[ERROR] Analysis failed, cannot generate report", file=sys.stderr
        )
        sys.exit(1)
    html = generate_html(analysis)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[INFO] Report saved to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
