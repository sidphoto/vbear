"""The words of the risk acceptance (design 10) for ``RISK_TEXT_VERSION``.

The screen is made from this module and from nothing else, and the server's
preview record holds the same version; changing a word means changing the
version (acceptance.RISK_TEXT_VERSION), and a changed version makes every
earlier acceptance void. The numbers in the text (disk thresholds, sample
interval) come from the constants the daemon enforces, so the text cannot
say one thing and the code another.

Chinese is the interface language; English is for the documents and for
anyone reading the preview record. The three items are the Codex draft
(drafts/risk-text-2026-10-11.1.md, 2026-10-11) word for word, apart from the
numbers, which are filled in from the constants. Whole items are always
shown, never titles or summaries.
"""

from __future__ import annotations

from . import acceptance
from .runtime import review_codex, review_run

VERSION = acceptance.RISK_TEXT_VERSION

_ITEMS = (
    {
        "id": 'tools',
        "title": {"zh": 'Codex 的工具集合無法事先證明', "en": "Codex's tool set cannot be proved in advance"},
        "body": {
            "zh": 'Codex 0.160.0 沒有能事先列出並確認審查模型全部可用工具的介面。被審查的 repo 內容可能誘導審查者使用不該使用的工具。VBear 使用專用的 `CODEX_HOME`、獨立的 `HOME`、固定啟動參數，停用已知的連接器、瀏覽器、電腦操作等功能，並限制沙盒內指令的網路與寫入範圍；審查後再逐筆核對紀錄中的設定與工具呼叫。這些措施無法證明模型沒有拿到未知工具：工具若存在但未被呼叫，VBear 看不到；若被呼叫，VBear 會把整次審查判為無效，但呼叫已經發生，無法撤銷。最壞影響取決於該工具，可能包括透過 Codex 帳號連接的服務執行動作、對外連線，或讀寫沙盒以外的檔案。此外，Codex 0.160.0 無法關閉多 agent 能力；VBear 釘住實測值 `explicitRequestOnly`，只能以封閉的紀錄種類與工具允許清單偵測，出現 `SUBAGENT_ACTIVITY` 就整次審查無效。子 agent 與主 agent 共用同一個沙盒與權限，不會因派生而擴大權限，但已發生的動作仍無法撤銷。接受這項風險，表示你了解「審查無效」不等於「動作沒有發生」。',
            "en": "Codex 0.160.0 has no interface that can list and establish every tool available to the review model before it runs. Content in the reviewed repository may steer the reviewer into using a tool it should not use. VBear uses a dedicated `CODEX_HOME`, a separate `HOME` and fixed launch arguments, disables known connector, browser and computer-use features, and restricts network access and writes by sandboxed commands. It then checks the recorded settings and tool calls record by record. These measures cannot prove that no unknown tool was offered: VBear cannot see an unused tool, and if a tool is called, VBear invalidates the entire review after the call has already happened. It cannot undo the action. Depending on the tool, the worst effects could include actions in services connected to the Codex account, external connections, or reads and writes outside the sandbox. In addition, Codex 0.160.0 cannot disable multi-agent capability. VBear pins the observed value `explicitRequestOnly` and can only detect activity through a closed set of record kinds and a tool allow-list; `SUBAGENT_ACTIVITY` invalidates the entire review. Sub-agents share the main agent's sandbox and permissions, so spawning does not widen permissions, but actions that have already happened still cannot be undone. Accepting this risk means understanding that an invalid review does not mean no action occurred.",
        },
    },
    {
        "id": 'limits',
        "title": {"zh": '上限的強度不一', "en": 'Limits have different strengths'},
        "body": {
            "zh": '畫面列出的上限不是全部都能在超出之前阻止。Claude 主對話的模型回應數是 daemon 即時計數的硬上限，到達就結束 session，但結束當下正在進行的一次回應仍可能完成；壓縮對話等輔助呼叫不計入這個數字。Claude 的 `--max-budget-usd` 要等一輪結束才檢查，因此一輪內可能超過所設額度，沒有可保證的金額上界；VBear 以回應數與單輪硬逾時限制執行時間，並在下一個動作前核對剩餘額度。訂閱帳號的 `total_cost_usd` 是 CLI 回報的用量金額，不是實際帳單。Codex 的模型回應數只是每秒讀取紀錄的監測值，超過就結束審查並判為無效，兩次讀取之間仍可能多出回應，沒有可證明的超出上界；它的硬上限是單次審查時間。磁碟也一樣：`CODEX_HOME` 的 {home}，以及審查暫存區加臨時 `HOME` 合計的 {work}，都是每 {every} 秒檢查一次的監測門檻，不是磁碟配額。VBear 在啟動前檢查、超限或無法完整計算時拒絕新審查或結束進行中的審查，但兩次檢查之間仍可能用掉磁碟剩餘空間，讓這台機器上其他程式的寫入失敗。VBear 自己寫入的審查輸出有寫入時的硬上限，與這些由 Codex 寫入的區域不同。這些監測無法保證費用或磁碟用量不會超過畫面上的值。',
            "en": "Not every displayed limit can prevent an overrun before it happens. The daemon counts Claude's main-conversation model responses in real time and ends the session at the hard response limit, but the one response in progress may still complete. Auxiliary calls, such as conversation compaction, are not included in this count. Claude checks `--max-budget-usd` only at the end of a turn, so a turn can exceed the configured budget with no guaranteed monetary upper bound. VBear limits execution through response counts and a hard turn timeout and checks the remaining budget before another action. For subscription accounts, `total_cost_usd` is the CLI's usage valuation, not an actual bill. Codex's response count is only monitored by reading its records once per second. An excess ends and invalidates the review, but more responses can occur between reads, with no provable bound on the overrun; the hard limit is the review timeout. The same distinction applies to disk use: {home} for `CODEX_HOME` and {work} for the review scratch directory plus temporary `HOME` are monitoring thresholds checked every {every} seconds, not disk quotas. VBear checks before launch and refuses new reviews or ends a running review if a threshold is exceeded or a complete count is impossible. Between checks, however, Codex could consume all remaining disk space and cause other programs on this machine to fail when writing. Review outputs written by VBear have hard limits enforced during writes, unlike these Codex-written areas. Monitoring cannot guarantee that cost or disk use stays within the displayed values.",
        },
    },
    {
        "id": 'managed',
        "title": {"zh": '伺服器管理設定（Team／Enterprise）', "en": 'Server-managed settings (Team / Enterprise)'},
        "body": {
            "zh": '若 Claude 執行者使用 Team／Enterprise 帳號，組織 Owner 可以從雲端下發伺服器管理設定，優先於 VBear 的命令列設定，可能蓋過 VBear 固定的 API 端點或加入 hooks。最壞情況是 CLI 把資料送往 VBear 原本未核准的端點，或執行 VBear 原本要停用的 hooks，使你以為有效的啟動限制不再有效。VBear 啟動前會檢查已知的本機管理員政策來源；`~/.claude/remote-settings.json` 快取檔存在或無法確認不存在時，也會拒絕啟動。但本機沒有快取檔，不能證明雲端沒有設定；VBear 無法在本機可靠偵測或排除尚未快取的伺服器管理設定。此項風險適用 Team／Enterprise 帳號，個人方案（Pro／Max）不受這種組織伺服器管理設定影響。接受前，請確認你使用的帳號方案與組織設定是否適合這個流程。',
            "en": "If the Claude executor uses a Team or Enterprise account, the organization Owner can send server-managed settings from the cloud. These take precedence over VBear's command-line settings and may override its fixed API endpoint or add hooks. In the worst case, the CLI could send data to an endpoint VBear did not authorize or execute hooks VBear intended to disable, making expected launch restrictions ineffective. Before launch, VBear checks known local administrator-policy sources and refuses to start if the cached `~/.claude/remote-settings.json` exists or its absence cannot be established. However, no local cache file does not prove that no cloud settings exist. VBear cannot reliably detect or exclude server-managed settings that have not been cached locally. This risk applies to Team and Enterprise accounts; personal Pro and Max plans are not subject to this organization-managed mechanism. Before accepting, check that your account plan and organization settings are suitable for this flow.",
        },
    },
)

_CHROME = {
    "zh": {"title": "接受殘餘風險",
           "intro": "下列三項殘餘風險無法由設計消除。請逐項完整閱讀；要啟用「由 VBear 啟動 Codex 審查」，必須勾選下方的確認。",
           "confirm": "我了解並接受以上殘餘風險"},
    "en": {"title": "Accept the residual risks",
           "intro": ("The three residual risks below cannot be removed by design. Read each one in full; to turn on "
                     "\"VBear starts the Codex review\" you must tick the confirmation at the end."),
           "confirm": "I understand and accept the residual risks above"},
}


def _mib(n: int) -> str:
    return f"{n >> 20} MiB" if n < (1 << 30) else f"{n >> 30} GiB"


def numbers() -> dict:
    """The figures the text states, from the constants that enforce them."""
    return {"home": _mib(review_codex.HOME_LIMIT), "work": _mib(review_codex.WORK_LIMIT),
            "every": f"{review_run.DISK_EVERY:g}"}


def render(lang: str = "zh") -> dict:
    """{"version", "lang", "title", "intro", "items": [{"id", "title", "body"}], "confirm"}."""
    if lang not in ("zh", "en"):
        raise ValueError("lang 必須是 zh 或 en")
    n = numbers()
    items = [{"id": it["id"], "title": it["title"][lang], "body": it["body"][lang].format(**n)} for it in _ITEMS]
    return {"version": VERSION, "lang": lang, **_CHROME[lang], "items": items}
