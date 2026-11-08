# PixelWorld：输出记录范围与完整性

SFT与分析的固定出口、完整性门槛和文件schema见 [DATA_RECORDING_CONTRACT.md](DATA_RECORDING_CONTRACT.md)。

新流程记录CLI/API向harness公开返回的消息和产物。不能将“完整CLI记录”等同于厂商内部隐藏思考、未结束响应或所有内存草稿。

| 内容 | 保存位置 |
|---|---|
| 原始CLI stdout JSONL字节 | logs/events.raw.jsonl |
| 加外部时间戳的事件 | logs/events.jsonl |
| CLI暴露的消息、工具调用、返回内容、用量记录 | logs/full_rollout.jsonl |
| 图片和其他大内容的blob正文 | logs/rollout-blobs/；rollout_blob_manifest.json列出是否可用及SHA256 |
| 实际返回的工具图片 | logs/tool_images/ |
| 每run终端API usage与预算计数 | logs/token_usage.json、logs/token_budget.json、run_manifest.json |
| 稳定候选的代码、RGB张量、PNG、检查图 | trace/round_*/ |
| 最终或被预算保留的产物 | workspace/；中断中的已保存文件另外保留 |

所有符合CLI协议的大内容blob引用都归档，包括助手文字和工具文本；不是只复制图片。按长度与SHA256核验，缺失内容标记unresolved，不伪造正文。原始JSON保留引用，与blob清单一起构成可恢复记录。

完成且有API usage的run，计数使用API上报字段。TRAE读取去重后的逐请求记录，Codex读取累计计数；不从可见文字分词估算，不重复加总已经包含在output内的reasoning。已核对8条真实TRAE trace、100条API记录的逐请求累计与终端总量完全一致，且每条input+output等于上报total。

## 明确边界

- API只返回reasoning数量或摘要时，可以记录数量/摘要，不能恢复未返回的完整隐藏思考。
- 50k停止发生在上报请求用量后。被中断的下一条请求可能缺少正文末尾和最终usage，标记partial/inflight_usage_unknown；已知用量只是下界。
- 原始stdout按CLI输出保存；工具本身先做的内容截断，不会被改写成未经截断的原始程序stdout。
- 候选和代码历史由外部观察器采样。未保存的草稿，以及同名文件被快速覆盖的短暂版本，可能没有快照。逐保存无遗漏需要另行引入保存点归档协议，当前不声称具备该保证。
- 旧ephemeral v1没有完整rollout时，不能升级宣称有完整视觉工具历史；已有最终代码/RGB和终端usage仍保留。

新manifest的`recording_coverage`标明stdout是否结束、完整rollout状态、未解析blob数、是否预算中断和usage完整性。网页的可读摘要不替代原始记录。
