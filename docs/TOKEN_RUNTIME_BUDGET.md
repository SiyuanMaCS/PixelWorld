# PixelWorld：50k 外部 token 阈值

用户在2026-11-08选择每条视频任务累计 **50,000 API output tokens**。新非legacy配置默认采用：

```json
{
  "output_token_budget": 50000
}
```

legacy v1未明确设置该字段时保留旧协议；`null`可用于明确的无预算对照。任务内不出现预算数字，仅增加避免无明确改进目标的重复检查/执行的一句提醒。

## 记录与执行

- 预算跨请求累计；同模型/track/case的恢复attempt共享50k，不重置。已有attempt用量不明时不分配新的完整预算。
- TRAE后端读取持久化会话的逐请求`token_usage_record`；Codex后端读取`token_count.info.total_token_usage`。不按时间或文本长度估算，不重复加总output中的reasoning。
- 外部每0.25秒检查上报用量。达到阈值后终止CLI及其拥有的工具进程，停止该case的自动重试；其他case可以继续。
- 取首次越过阈值的用量事件时间作为候选截止边界，恢复之前最后一个可校验的快照。完整RGB/首帧/PNG一致性和工具审计仍须通过。真实CLI退出码保留，预算保留的产物标记`completion_mode=budget_frozen`。
- 中断中的产物另存于workspace外，未保存合法候选时记预算失败，不伪造视频。
- 持续执行工具却没有可用实时计数时，终止为`token_usage_unavailable`，不静默运行一个假预算。

## 这是请求结束后的阈值控制

上报用量在请求结束后出现，因此单次请求可能跨过50k。记录实际已上报量和overshoot；此实现不是精确的50k硬请求上限。严格预算需要在API请求边界用剩余量限制输出，并阻止后续请求。

被中断请求的完整usage可能不返回。此时保存已完成请求output的下界，标记`inflight_usage_unknown`，不把下界填成精确总量。没有15分钟墙钟截止；API等待不会按分钟扣掉token预算。既有局部工具卡死保护仍单独存在。

## 验证

逐请求读取器对8条已完成真实TRAE trace、100条API用量记录的累计结果，与每条终端总量完全相等。回归测试覆盖TRAE/Codex记录、去重、半条JSON、外部终止、候选恢复，以及完整runner中的本地CLI测试替身；测试替身不调用模型。

## 大致时间量级

以历史每run的output/墙钟分钟数中位值估算“用满50k”的时间：GPT-5.6约13–16分钟，GPT-6.1约21–23分钟，DeepSeek-V4-Pro约19分钟，Seed Pro约31分钟。Flash只有每track一条完成数据，约13分钟，仅为示例。

这些不是实际前50k的时间测量，也不是新运行的保证。普通GPT-6.1只使用14–16k即可完成的任务仍会在约6分钟结束。限流、等待与工具开销会改变实际耗时；执行只按token阈值。
