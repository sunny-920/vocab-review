# 單字複習

讀英文文章時遇到的生字，丟進來由**本機 AI** 整理成單字卡，再用「不同天累計答對」的間隔複習，直到真的記住。
全部在自己的電腦上執行，資料不上雲。介面是繁體中文。

## 功能

- **新增單字**：貼上一串字（可以附原文句子），字典＋本機 AI（Ollama）自動整理意思、詞性、例句、字根拆解、相關字、易混淆字，確認後存入
- **複習**：英→中、中→英（提示）、例句填空、聽寫、混合；紅黃綠燈號＋間隔排程；每日複習和自由複習（可依分類、燈號、加入日期、下次複習、出處文章篩選）
- **文章閱讀**：貼上文章自動排版（AI 只決定分段，不改原文）；選字查「在這句的意思」並和學過的意思比對；整句翻譯；標出單字庫裡不熟的字；片語與文法筆記；只記在這篇的專有名詞；Markdown 備註；朗讀
- **自然語音**：本機 Kokoro 語音（只用 CPU、不佔 GPU），單字發音會快取，文章即時產生
- **單字卡、單字庫、統計**，匯出 CSV
- **手機版**：同一個網址，手機上自動換版面（iPhone 可「加入主畫面」當 App 用）

詳細規格見 [SPEC.md](SPEC.md)。

## 需要

- Windows（其他系統要自己改啟動腳本）
- Python 3.13
- [Ollama](https://ollama.com/)，並下載模型：`ollama pull qwen3:8b`（約 5GB，建議有 8GB 以上 VRAM 的顯示卡）
- 約 500MB 硬碟空間（字典＋語音模型）；要用字根資料的話另外約 10GB（Wiktionary，選用）

## 安裝與啟動

1. 雙擊 `安裝.bat`：建立 `.venv`、安裝套件、下載離線字典（ECDICT）和語音模型（Kokoro）
2. 雙擊 `啟動.bat`：瀏覽器會自動打開 `http://127.0.0.1:8765`

   8765 被其他程式佔用時，可以用環境變數 `VOCAB_PORT` 換成別的 port，例如在 `啟動.bat` 的 `set PYTHONUTF8=1` 下面加一行 `set VOCAB_PORT=8770`。

選用：建立 Wiktionary 字源資料庫（字根拆解更準）。到 [kaikki.org](https://kaikki.org/dictionary/rawdata.html) 下載 `raw-wiktextract-data.jsonl.gz`，再執行：

```
.venv\Scripts\python.exe tools\build_wiktionary.py <下載的檔案>
```

## 資料

所有個人資料都在 `data\`（**不在版本控管裡**）：

| 檔案 | 內容 |
|---|---|
| `vocab.db` | 單字、複習紀錄、文章、片語 |
| `backups\` | 每日自動備份（升級資料庫前也會先備份） |
| `settings.json` | 設定 |
| `tts_cache\` | 單字發音快取 |
| `ecdict_lite.db`、`kokoro\`、`wiktionary.db` | 字典、語音模型、字源資料（可以重新下載） |

## 用手機連回來

程式只聽本機（`127.0.0.1`），**沒有登入功能，不要直接開放到網路上**。
要在手機或其他電腦用，建議裝 [Tailscale](https://tailscale.com/)，在跑程式的電腦執行 `tailscale serve --bg 8765`（有改 port 的話換成你的 port），
只有登入同一個 Tailscale 帳號的裝置連得到。

## 使用的資料與模型

- 字典：[ECDICT](https://github.com/skywind3000/ECDICT)（MIT）
- 字源：[Wiktionary](https://www.wiktionary.org/)（CC BY-SA），經 [kaikki.org / wiktextract](https://kaikki.org/) 整理
- 語音：[Kokoro](https://huggingface.co/hexgrad/Kokoro-82M)（Apache 2.0），透過 [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx)
- 簡轉繁：[OpenCC](https://github.com/BYVoid/OpenCC)（Apache 2.0）
- AI：[Ollama](https://ollama.com/) + Qwen3

## 授權

[MIT](LICENSE)
