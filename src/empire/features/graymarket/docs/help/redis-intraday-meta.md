<!-- topic:数据库参考|Redis graymarket-intraday-meta -->
<!-- summary:资金榜盘中变化快照的有界临时存储，单独于日终归档，服务重启后不可恢复。 -->
<!-- group:Redis -->
# Redis graymarket-intraday-meta

## 用途与归属

项目eastmoney-graymarket拥有；IntradayStore唯一读写入口，经统一publish_volatile准入发布，不进入待归档Stream和MySQL。

## 结构与身份

键模板：`<namespace>:graymarket:intraday:meta`；类型：Hash。

checked为最后成功观察开始时间；latest为最后变化version；digest为日期和规范内容SHA256；bytes为保留正文总字节；size:<version>为每份大小；evicted为累计淘汰计数；maintenance为已成功收盘复核的北京时间窗口。

## 读写与关联

snapshots、times、meta由共享Lua一次原子维护；按开始观察时间拒绝旧结果，同内容不新增正文。业务日期参与摘要；三类键共同限定一套业务快照，不建立重复归档路径。

同内容确认先传版本和摘要，以Lua原子核对摘要、最新正文及未过期索引，成功免压缩和传输完整正文；不可信则回完整保存并再次原子核对。确认不延长正文绝对到期。maintenance只单调前进，重复或旧窗口不刷新；复核窗口随日终断点保存，整轮成功后补记，中断恢复及补记失败可重试。

## 保留与恢复

最多72小时、32MiB、2048份，容量先到先淘汰最旧。正文绝对到期不因同内容核验延长，索引和元信息空闲72小时到期；维护标记续期不授权保留过期正文。失败不替换有效快照；过期/淘汰显示缺失，不推断空榜。正常重启且Redis存活可继续读，Redis服务重启丢失全部盘中历史，SQL不能恢复。

## 维护与相关说明

只读查询最多200条并绑定快照版本，完成区间不是瞬时冻结行情。不得清空共享Redis；维护仅操作本项目明确键。

[东方财富明盘暗盘资金榜](help:东方财富明盘暗盘资金榜)
