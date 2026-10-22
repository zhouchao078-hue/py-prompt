# Prompt Atelier 测试报告

测试日期：2026-10-22  
测试环境：Windows、Python 3.12、FastAPI、SQLite FTS5、DeepSeek、Playwright + Chrome  
服务地址：http://127.0.0.1:8000/

## 一、总体结果

| 检查项 | 结果 |
|---|---|
| Python 自动化测试 | 41 / 41 通过 |
| Ruff | 通过 |
| Pyright | 0 errors, 0 warnings |
| JavaScript 语法检查 | 通过 |
| 桌面浏览器交互 | 通过 |
| 移动端响应式检查 | 通过 |
| 浏览器控制台错误 | 0 |
| 页面运行时异常 | 0 |
| 真实提示词质量评测 | 3 / 3 通过 |

## 二、Python 自动化测试用例

| # | 模块 | 测试用例 | 验证内容 | 结果 |
|---:|---|---|---|---|
| 1 | database | `test_initialize_database_creates_tables` | 初始化数据库并创建主表、FTS 表 | PASS |
| 2 | database | `test_insert_and_fts_search_chinese_token` | 写入记录后通过中文 token 检索 | PASS |
| 3 | database | `test_duplicate_content_hash_is_rejected` | 相同内容 hash 被唯一约束拒绝 | PASS |
| 4 | database | `test_delete_removes_record_from_fts` | 删除主表记录后 FTS 同步删除 | PASS |
| 5 | database | `test_insert_prompt_records` | 批量写入、幂等和 FTS 可检索 | PASS |
| 6 | fake_search | `test_search_finds_hanfu_snow_scene` | JSONL 搜索命中汉服雪夜场景 | PASS |
| 7 | fake_search | `test_search_respects_top_k` | `top_k` 截取生效 | PASS |
| 8 | fake_search | `test_search_returns_empty_when_nothing_matches` | 无匹配时返回空列表 | PASS |
| 9 | fake_search | `test_search_returns_empty_for_empty_request` | 空查询返回空列表 | PASS |
| 10 | fake_search | `test_search_returns_empty_for_zero_top_k` | `top_k=0` 返回空列表 | PASS |
| 11 | prompt_service | `test_prompt_service_falls_back_to_direct_generation` | 解析失败时直接生成提示词 | PASS |
| 12 | query_cache | `test_build_cache_key_is_deterministic` | 缓存 key 稳定且随 prompt 版本变化 | PASS |
| 13 | query_cache | `test_build_prompt_version_is_deterministic` | Prompt 指纹稳定 | PASS |
| 14 | query_cache | `test_cached_prompt_round_trip` | 缓存写入、读取、删除 | PASS |
| 15 | query_cache | `test_prompt_index_version_changes_after_insert` | 提示词索引版本随数据变化 | PASS |
| 16 | skills | `test_prompt_generation_skill_invokes_workflow` | Skill 正确调用工作流 | PASS |
| 17 | smoke | `test_package_imports` | 包可正常导入 | PASS |
| 18 | smoke | `test_load_prompt_records` | 测试 JSONL 可读取 | PASS |
| 19 | sqlite_query_variants | `test_query_variants_recall_composed_chinese_terms` | 查询变体召回“白猫→白色小猫” | PASS |
| 20 | sqlite_query_variants | `test_aspect_ratio_does_not_participate_in_search` | 画幅比例不污染 FTS 查询 | PASS |
| 21 | sqlite_search | `test_search_returns_prompt_candidate` | 返回完整 `PromptCandidate` | PASS |
| 22 | sqlite_search | `test_search_can_match_multiple_records` | 多记录命中 | PASS |
| 23 | sqlite_search | `test_search_respects_top_k` | SQLite 搜索 `top_k` 生效 | PASS |
| 24 | sqlite_search | `test_search_returns_empty_for_zero_top_k` | SQLite `top_k=0` 返回空 | PASS |
| 25 | sqlite_search | `test_search_returns_empty_for_empty_request` | SQLite 空请求返回空 | PASS |
| 26 | sqlite_search | `test_search_returns_empty_when_nothing_matches` | SQLite 无匹配返回空 | PASS |
| 27 | tokenizer | `test_normalize_text` | 清理零宽字符和多余空白 | PASS |
| 28 | tokenizer | `test_chinese_search_token` | 中文子词 token 生成 | PASS |
| 29 | tokenizer | `test_aigc_terms` | AIGC 自定义词识别 | PASS |
| 30 | tokenizer | `test_query_tokens_are_deduplicated` | 查询 token 去重 | PASS |
| 31 | tokenizer | `test_empty_input` | 空文本和纯空格处理 | PASS |
| 32 | tools | `test_search_prompts_tool_returns_serializable_candidates` | Tool 返回 JSON 可序列化候选 | PASS |
| 33 | transformer | `test_prepare_prompt_records` | 规范化、hash、分词和去重 | PASS |
| 34 | webapp | `test_prompt_endpoint_returns_prompt` | `/api/prompt` 返回提示词 | PASS |
| 35 | webapp | `test_media_endpoint_exposes_provider_status` | `/api/media` 返回媒体状态 | PASS |
| 36 | webapp | `test_prompt_endpoint_maps_service_error` | 服务错误映射为 422 | PASS |
| 37 | webapp | `test_index_and_health_are_available` | 首页和健康接口可用 | PASS |
| 38 | workflow | `test_workflow_success` | 解析、检索、重排、拼接完整链路 | PASS |
| 39 | workflow | `test_rerank_filters_unknown_ids_and_limits_to_three` | 非法候选 ID 过滤、最多保留三条 | PASS |
| 40 | workflow | `test_workflow_stops_when_parse_fails` | 解析失败停止后续节点 | PASS |
| 41 | workflow | `test_workflow_sets_needs_generation_when_no_candidates` | 无候选时进入直接生成分支 | PASS |

## 三、浏览器交互测试

| # | 用例 | 验证内容 | 结果 |
|---:|---|---|---|
| 1 | 桌面初始加载 | 页面标题、左侧工具栏、默认提示词工具 | PASS |
| 2 | 桌面布局 | 1440px 视口无横向溢出 | PASS |
| 3 | 提示词工具请求 | 输入“雪山红围巾白猫”后返回最终提示词 | PASS |
| 4 | 工具切换 | 从提示词工坊切换到影像生成 | PASS |
| 5 | 媒体模式 | 图片/视频分段控件可切换，测试使用视频模式 | PASS |
| 6 | 画幅选择 | 成功选择 16:9 | PASS |
| 7 | 媒体页请求 | 生成机械鲸鱼提示词并更新预览区 | PASS |
| 8 | 移动端布局 | 390px 视口无横向溢出，工具栏固定在顶部 | PASS |
| 9 | 浏览器控制台 | `consoleErrors = 0` | PASS |
| 10 | 页面异常 | `pageErrors = 0` | PASS |

浏览器实测结果：

```json
{
  "desktopWidth": 1440,
  "desktopScrollWidth": 1440,
  "mobileWidth": 390,
  "mobileScrollWidth": 390,
  "mobileToolRailTop": 0,
  "mobileWorkspaceTopbarTop": 70,
  "consoleErrors": 0,
  "pageErrors": 0
}
```

## 四、真实提示词质量评测

评测方式：真实 DeepSeek 生成，再由独立 DeepSeek 质量评审结构化工具体系评分。

### 用例 1

用户需求：

> 雪山上戴红围巾的白色短腿小猫，电影感

评分：95 / 100，PASS  
缺失要求：无  
矛盾：无  
无关内容：无  

最终提示词：

> 一只白色短腿小猫戴着红围巾，平静明亮的神情，站在雪山上，雪地环境，真实摄影质感，电影感光影，超广角镜头，高清摄影作品，画幅 2:3

### 用例 2

用户需求：

> 火星上的紫色机械鲸鱼，赛博朋克，电影感，超广角，--ar 16:9

评分：95 / 100，PASS  
缺失要求：无  
矛盾：无  
无关内容：无  

最终提示词：

> 一只巨大的紫色机械鲸鱼悬浮在火星红色地表上方，金属装甲表面嵌有发光霓虹线条与精密机械结构，鲸身缓慢翻转穿行于尘暴与岩石峡谷之间，远处矗立赛博朋克风格穹顶基地与闪烁霓虹灯牌，火星天空呈暗橙与冷紫交织，强烈逆光勾勒机械轮廓并投下体积光与尘埃光晕，超广角低机位仰拍，电影级构图与景深，赛博朋克科幻美学，高细节金属质感与真实光影渲染，16:9

### 用例 3

用户需求：

> 我要一只在雪山上滑雪的白色短腿胖小猫，电影感真实摄影，超广角，8k，--ar 2:3

评分：88 / 100，PASS  
缺失要求：无  
矛盾：无  
无关内容：无  

最终提示词：

> 一只白色短毛短腿胖小猫在雪山上滑雪，肥胖脑袋瓜，小小身材，平静神情，眼睛明亮，雪地，雪山，真实摄影，电影感，超广角，自然光，高清晰，8k，--ar 2:3

评审意见：核心需求完整；“短毛”与“短腿”存在轻微表述差异，但不构成矛盾。

质量报告原始文件：

```text
data/eval/prompt_quality_report.json
```

## 五、已知限制

1. 图片和视频生成供应商尚未接入。影像页当前生成最终提示词，并返回 `provider_status=not_configured`。
2. 真实质量评测当前覆盖 3 个代表性用例，尚不能代表全部提示词类别。
3. 默认 Python 测试使用假 LLM，避免测试套件产生外部 API 费用；真实模型测试由独立脚本和浏览器用例执行。
4. DeepSeek 结构化输出偶发返回空 Tool Call，当前已通过节点重试和服务层直接生成兜底。

## 六、结论

当前版本的提示词工具、SQLite RAG、多查询召回、LLM 重排、提示词组装、直接生成兜底、精确缓存和 FastAPI 双工具工作台均已通过测试。
