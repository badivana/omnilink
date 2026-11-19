# Visual automation

In the client, select **Automation → + Flow**. Every flow has one trigger. Add blocks from the palette, configure them with **Edit**, and connect an output (`next`, `yes`, `no`, or `error`) to another block's **Input**. Drag block headers to arrange the chart. The connections list can remove links, including on touch devices.

The editor represents blocks as mxGraphModel XML cells (vertices, geometry, and source/target edges). The visual model is stored separately from the flow's executable `{nodes, edges}` graph. The server verifies that they describe the same blocks and connections. Existing flows without a visual model are converted in the browser when edited. Keeping runtime JSON unchanged allows a v0.5 rollback to continue using saved automations.

**Save draft** validates the graph and saves its current revision. **Publish** saves and activates a validated snapshot. Subsequent draft edits do not change that published snapshot. **Pause** stops new automatic runs and cancels active runs. **Run published** executes the published snapshot immediately. **Test draft** simulates writes/integrations, skips delays and creates no commands or alerts; optional sample readings use `{"device_id:pin": value}`. Inspect **Executions** for waiting/completed/failed blocks and variables.

| Block | Behaviour |
|---|---|
| Trigger | Manual; changed pin report; changed telemetry metric; interval; timezone-aware daily weekdays; online/offline transition |
| Condition | Compare a pin or variable; `gt`, `gte`, `lt`, `lte`, `eq`, `ne`; optional AND/OR/NOT comparison list; yes/no routes |
| Write | Typed device command; optionally wait for applied acknowledgement; configurable timeout and retries |
| Delay | Persist a wait in the database; resume when due, including after restart |
| Wait | Wait for a pin comparison; timeout uses the error route |
| Variable | Set a run-local variable |
| Calculate | Add, subtract, multiply, divide, min, max, average; save the result in a variable |
| Alert | Add an account alert with info/warning/critical severity; clients acknowledge it |
| Parallel | Start all connected next branches; branches advance cooperatively |
| Flow | Launch another published flow; parent continues without waiting for it |
| Webhook / email | Invoke a named manager-configured integration; email goes to an enabled owner of the account |
| Stop | End the whole run and discard its remaining branches |

Values use JSON: `true`, `42`, `"text"`, or `{"var":"result"}`. The special variable `trigger` contains the event value. Variables are local to a run, never shared globally. No arbitrary Python/JavaScript is executed. A condition with no pin uses the trigger value unless advanced `value2` is provided through the API.

A condition list takes `[{"left":{"var":"result"},"op":"gt","right":10}]`. AND requires all comparisons, OR any comparison, and NOT negates the conjunction. A write value still passes the device channel's type, writable and range checks at execution time. Reporting a value and acknowledging a command are different operations.

Flows are bounded to 64 blocks and 128 connections; every block must be reachable from the trigger. Cycles are rejected: use interval triggers or device schedules for repetition. Each node runs at most once per execution; converging branches use the first arrival rather than an all-branches barrier. Nested calls have a depth limit of four; account quotas limit simultaneous and per-minute executions. Delays/timeout inputs are bounded to one day per block and a run expires after seven days. These limits prevent accidental infinite automation.

Pin allocations are checked again at execution time. Shared references prevent pin release while saved flows or real executions still use it. Explicit pin moves invalidate affected publications. A physical command may already have left the server when a run is paused; pausing cannot recall an applied action. Manual override temporarily blocks automation writes for a device.

Interval and daily triggers skip missed occurrences more than 30 seconds late after downtime. Online/offline triggers require a transition after their initial observation; online uses accepted recent device activity. Test mode uses current pin values unless samples override them, and a false wait takes its error output immediately.

Integrations are configured only in the server manager. Webhooks use a fixed HTTP(S) endpoint, optional encrypted bearer token, a five-second timeout and no redirect following. Payload: run ID, message and current variables. SMTP uses STARTTLS; credentials are encrypted with the server key. Integration retries can repeat a remote effect after an uncertain response: webhook receivers should deduplicate `X-OmniLink-Run`. External delivery is not claimed as exactly-once. Review endpoints and credentials before enabling real runs.

Completed execution history follows the server retention window (30 days by default); acknowledged alerts can expire after that window. Unacknowledged alerts remain until acknowledged. Flows need the server running, but do not need an open browser.
