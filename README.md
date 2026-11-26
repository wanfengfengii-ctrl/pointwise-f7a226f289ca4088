# 松桥工坊双面海报联印服务

松桥社区版画工坊用同一张纸印制双面节目海报。制版台交来两面的版框和修订号，印机工艺单提供纸样及具名套准档。试印员用校样确定能打样的面和档，印务员根据实际样张放行，印刷员按公布档装版。交班员凭印单号找回实际开印的依据和实印张数。

## 本机运行

需要 Python 3.11，只依赖标准库。以下命令从项目根目录执行。平台提供的 `check_project.py` 运行完整 `unittest` 套件。

```sh
python3 -B check_project.py
python3 -B -m printing.workbench demo
```

演示在独立临时目录创建 SQLite 数据库，在环回地址启动服务，导入 `samples/references.json` 的固定资料，并经真实 HTTP 重放 `samples/events.json`。各步输出实际 JSON。演示返回码为 1 时表示业务断言失败，2 表示 HTTP 调用或响应读取错误，3 表示初始化或启动错误。

手动操作时可建一个测试临时目录，把命令中的路径替换成该目录下的数据库路径。`init` 可单独初始化，`serve` 启动时也会初始化。`--sample` 导入样例参考资料，同号内容冲突则整批回滚。重跑同版本保留已录入资料、校样、试印和印单。服务只监听 `127.0.0.1`，`--port 0` 会选择空闲端口并打印地址。

```sh
python3 -B -m printing.workbench init --db /tmp/songqiao-test/workbench.sqlite3 --sample
python3 -B -m printing.workbench serve --db /tmp/songqiao-test/workbench.sqlite3 --port 8080
```

## HTTP 接口

POST 使用 `Content-Type: application/json` 和 JSON 对象。字段为必填。稿号、校样号等身份使用非空字符串，保留大小写。GET 查询使用单个 `id`，包含特殊字符的身份须进行 URL 编码。

| 方法和路径 | 输入字段 | 成功结果 |
| --- | --- | --- |
| POST `/faces` | `face_id`, `side`, `left_mm`, `right_mm` | 不可变修订，`side` 为 `front` 或 `back` |
| POST `/papers` | `paper_id`, `width_mm`, `print_left_mm`, `print_right_mm`, `min_left_mm`, `min_right_mm` | 固定纸样 |
| POST `/register-tables` | `table_id`, `steps` | 固定档表。每档含 `register_id`, `front_offset_mm`, `back_offset_mm` |
| POST `/freeze` | `edition_id`, `front_id`, `back_id` | 两面修订固定的发布稿 |
| POST `/proof` | `edition_id`, `paper_id`, `table_id` | `proof_id`、逐档 `settings`、`limits`、`common_registers` 及 `reasons` |
| POST `/trial` | `proof_id`, `trial_id`, `face_id`, `register_id`, `left_mm`, `right_mm` | 实试条件 `condition` 和原实测 `result`，含 `passed` 及原因 |
| POST `/void` | `trial_id`, `reason` | 按号保存的废样事实 |
| POST `/release` | `request_id`, `edition_id`, `proof_id` | `pending` 或 `released`，放行后随 `order` 公布档 |
| POST `/start` | `order_id`, `confirmation_id` | `recheck_required` 或 `started`；成功时含 `receipt` |
| POST `/finish` | `start_id`, `good_count`, `waste_count` | 封存的合格与废印张数 |
| GET `/receipt?id=…` | 印单号 | `released`、`recheck_required`、`started` 或 `completed`，附当前适用的印单、回执、完工记录 |
| GET `/faces?id=…`、`/papers?id=…`、`/register-tables?id=…`、`/editions?id=…`、`/proof?id=…`、`/trial?id=…` | 对应资料号 | 原记录，试印查询另附 `void` |

输入或身份冲突返回 400 `rejected`。查无目标返回 404 `not_found`。待验、须复验以及合法空校样返回 200，未产生的回执、印单或完工结果为 `null`。数据库繁忙返回 503，可用原输入重试。

## 纸边与实作口径

以 `[0,W]` 表示纸张物理横坐标。版框 `[l,r]` 在该面朝向观察者时定义，`d` 是工艺档在该面观察方向的偏移。正面物理区间是 `[l+d,r+d]`，反面是 `[W-(r+d),W-(l+d)]`。纸边余量为区间左端和 `W` 减区间右端。印区 `[a,b]` 与纸样各侧下限共同决定门槛，左侧取 `max(a,min_left_mm)`，右侧取 `max(W-b,min_right_mm)`。全部用整数毫米，等号合格。负预测值保留并给出未达下限的侧，缺边、浮点数和布尔值请求被拒绝。

样例纸宽 600，印区 `[10,590]`，纸边下限左 15、右 20。在 A 档，正面 `[20,575]` 偏移 −5 后占 `[15,570]`，余量 `(15,30)`。反面 `[20,570]` 偏移 +5 后镜像占 `[25,575]`，余量 `(25,25)`。两面几何上都可试 A。校样在没有共同可试档时给出空数组和 `no_common_register`，仍保留分面试印设置。预计可试的档位还需实际登记合格试印才可放行。

证据归属由实际面稿、纸样、档表和档号共同确定。同面同档可登记独立样张。废样逐号追加，原测量仍可查询。申请按共同可试档的档号顺序选出首个当前有双面证据的档；没证据时可补试后用原申请重办。仅换反面且工艺条件相同时，原正面证据可继续用。

已公布的档固定。开印与作废共用 SQLite 写提交边界。原档不足时按原单须复验，补齐原档后可重办。开印从各面有效样张里按试印号选首笔，同时保存实际档及两笔出处。相同确认号重领签存回执，其他确认不能再次开印。已签存回执在后续废样后原样读回。完工要求已有开印，两项张数均为非负整数；相同张数重报读回，冲突重报被拒绝。

## 回归覆盖

`tests/test_preparation.py` 核对反面坐标、边界等号、空交集、冻结拒绝及旧稿。`tests/test_proof.py` 核对实测、实际档、单笔作废、异档待验和换稿复用。`tests/test_printing.py` 核对原档复验、同档替换、作废与开印的提交顺序及完工。初始化和重启另有业务回归。部分用例在业务断言之后输出可关联输入、实测和下游结果的 `POINTWISE_SCENARIO` 行。
