# Sleep Brain 😴

睡眠醫學文獻日報 · 每日自動更新

## 關於

Sleep Brain 是一個自動化的睡眠醫學文獻日報系統，每日從 PubMed 抓取最新睡眠醫學文獻，透過 AI 分析後生成繁體中文日報。

## 架構

- **資料來源**：PubMed E-utilities API
- **目標期刊**：SLEEP、Sleep Medicine Reviews、Journal of Clinical Sleep Medicine 等 11 本頂尖睡眠醫學期刊
- **AI 模型**：GLM-5.1（Fallback：GLM-5-Turbo → GLM-4.7 → GLM-4.7-Flash）
- **自動化**：GitHub Actions，每日台北時間 11:00 執行
- **部署**：GitHub Pages

## 網站

👉 [https://u8901006.github.io/sleep-brain/](https://u8901006.github.io/sleep-brain/)
