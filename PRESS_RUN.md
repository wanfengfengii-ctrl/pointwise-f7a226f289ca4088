# 分段实印与交机

工作台已有双面校样、共同档放行、开印和完工流程，普通办理由 README.md 说明。现场轮印共用一台只报累计出张的印机。启用分段的印单用原开印号接续，可在两段之间让另一单印完。每段只认从占机到交机的计数差。

## 工作台 HTTP 请求

沿用原 JSON 和身份填写规则。新增的送纸张数和开印目标使用正整数。请求或身份冲突返回 400，查无所指开印号或段号返回 404。原接口的已有状态和错误码沿用 README.md。

| 请求 | 字段 | 回应 |
| --- | --- | --- |
| POST /start | order_id, confirmation_id，可加 target_count | 成功的分段印单在原 receipt 中附 target_count。仍须通过原档复验，成功时才固定目标。同一确认号重办须沿用首次成功的模式和目标。 |
| POST /press-turn | start_id, turn_id | 200，返回下述段记录。新段仅受理已取得分段开印首执、尚未完工的印单，且印机空闲。同一段号同一开印号重投只读回该段状态，异参冲突。 |
| POST /press-feed | turn_id, count | 200 accepted，送纸失答且结局待查时可回 202 pending。两种回包均含 status、turn_id、count。同参可重办原送纸，已交机后也可认回原受理。 |
| POST /press-yield | turn_id | 成功 200 yielded，待核 202 yielding，均返回段记录。 |
| GET /press-turn?id=… | 段号 | 200，返回段记录。查询不推进任何设备或工作台状态。 |

段记录包含 status、turn_id、start_id、start_counter、end_counter、count。status 为 active、yielding 或 yielded。占机起点固定，end_counter 和 count 在交机确认前都是 null。交机成功后两者持久固定，其中 count 是两端累计读数之差。各 POST 的成功返回或待办可按原号重办。交机成功的原号重办只返回原段。

余量按开印目标减去本单已确认各段的 count。一次占机最多受理一笔送纸。重复办理可让原设备命令首次到达，不可产生第二笔送纸。变更已受理的数量冲突。开始交机便停止受理本段首次送纸。未核实的段继续占机，别单的首次占机应返回 400。已受理的送纸可在交机前实际出张，也可截断未出的部分。无送纸的段可交回，实际为零。工作台重开后用同一数据库和模拟印机文件续办。

分段印单仍调用 POST /finish，字段照旧。仍在占机、累计未到目标或申报合计不等于实印总数均返回 400。完成后，GET /receipt 按原印单号返回原有完工信息，并在响应顶层附 press_turns，按该单占机先后列出确认的段记录。复领结果固定。普通印单继续按原方式开印、报数和查单，原响应形状照旧。

## 模拟印机

printing.press_device.open_press(workbench_database) 打开同目录下的独立印机库。工作台与试验操作者使用同一工作台数据库路径来定位印机文件。设备按实际出张累加整数读数，初值 100。独立重开保留设备状态，设备接口没有印单号或开印号。

- read() 返回当前 counter、generation 和 drained_through。新代从槽序 1 开始。drained_through 是当前代已经全部出张的连续命令末槽，0 表示尚无全部出张的命令。停在同一计数或同一末槽的两次读数本身不能证明在途送纸已经结束。
- submit(generation, slot, count) 提交送纸。正常命令在受理时完成，返回 accepted。当前代同槽同参返回 duplicate，不再出张，异参抛 ValueError。错代为 stale。越过尚未完成或尚未收到的前槽为 busy，均不出张。输送暂扣时，已受理命令可能只印出头几张，也可能回包丢失。
- advance(expected_generation) 仅在设备当前代等于给定值时换到下一代，计数保留，旧代的后续出张和迟到提交都失效。其他代返回 stale，不改变设备。成功返回 advanced，回包也可能丢失。换代与实际出张的先后由设备裁决。
- 实验操作者可调用 interrupt_next_feed(after=2) 暂扣下一条首次受理命令从第 3 张起的出张并使设备回包丢失。无参数时模拟命令未到设备便失答。resume(generation, slot) 只推进指定仍可继续的暂扣命令。lose_next_advance() 模拟下一次成功换代后失答。失答以 TimeoutError 表示，台架控制由试验操作者使用。

python3 -B -m printing.press_exercise 只核验模拟印机。新业务由交付者接入 .pointwise-runtime.json 的 verify 和 demo 命令。沿用该清单的 version、kind 和 setup 格式，命令以参数数组记录。verify 运行原回归并实际断言轮印结果，断言失败退出非零。demo 展示实际 HTTP 轮印与按原印单号领回的结果。

## 甲乙轮印样例

在带样例参考资料的新工作台上，用 printing.press_exercise.prepare_orders(post) 办理原有两面试印及两张 A 档印单。post 可用 tests.fixture.WorkbenchTestCase 的 post 方法。甲是 O-press-A，乙是 O-press-B。分别以确认号 mount-A、mount-B 开印，目标为 5、2，之后使用各自返回的 start_id。

1. 以 turn-A1 占机。试验操作者启用 after=2，向该段送 3 张。失答时累计为 102。查段和同参重投不多出纸，乙还不能占机。尝试将本段送纸改为 4 张应被拒绝。
2. 办理 turn-A1 交机。若用排空，操作者可放行滞留的第 3 张后重试。若截断先成立，旧代补送和迟到出张均无效。第一段分别可确认为 100→103 或 100→102。重开后按原段号核到同一交机结果。甲此时申报 5 张完工须拒绝。
3. 用 turn-B1 给乙送 2 张并交机。用 turn-A2 给甲按余量送 2 或 3 张并交机。两单实际各为 5 和 2，印机累计为 107，甲的两段不含乙的计数区间。甲申报 4 张合格且废印为 0 时拒绝。甲报 4 张合格和 1 张废印，乙报 2 张合格和 0 张废印，均可封存，重开后按原印单号读回各自完工和段界。
