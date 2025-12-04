import json
import logging
from selenium.webdriver.remote.webdriver import WebDriver


class ReplyExpander:
    """
    Expands all 'View replies' / 'Show more' buttons using injected JavaScript.
    Avoids Selenium click events; performs human-like scroll and pause behavior.
    """

    def __init__(
        self,
        driver: WebDriver,
        container_selector: str = "div.html-div",
        button_selector: str = 'div[role="button"][tabindex="0"], button, span',
        max_clicks: int = 8,
        base_pause_ms: int = 350,
        long_pause_chance: float = 0.25,
        settle_wait_ms: int = 1000,
        logger: logging.Logger | None = None,
    ):
        self.driver = driver
        self.container_selector = container_selector
        self.button_selector = button_selector
        self.max_clicks = max_clicks
        self.base_pause_ms = base_pause_ms
        self.long_pause_chance = long_pause_chance
        self.settle_wait_ms = settle_wait_ms
        self.log = logger or logging.getLogger(__name__)

    @classmethod
    def with_container(
        cls,
        driver: WebDriver,
        container_selector: str,
        **kwargs
    ) -> "ReplyExpander":
        """
        Alternative constructor that sets the container selector at creation time.

        Example:
            expander = ReplyExpander.with_container(driver, "div.comment-thread", max_clicks=15)
        """
        if not container_selector or not isinstance(container_selector, str):
            raise ValueError("container_selector must be a non-empty string")

        instance = cls(driver, **kwargs)
        instance.container_selector = container_selector
        instance.log.debug(f"Initialized with container selector '{container_selector}'")
        return instance

    # ---------- internal building blocks ----------

    def _js_core(self) -> str:
        """JavaScript logic injected into the browser."""
        return r"""
            async function clickAllReplyButtons(options = {}) {
            const {
                containerSelector = "div.html-div",
                buttonSelector = 'div[role="button"][tabindex="0"], a, button, span',
                pattern = /\b(view|show|see).*(repl|more|all)\b/i,
                maxClicks = 10,
                basePauseMs = 400,
                longPauseChance = 0.12,
                settleWaitMs = 2000,
                maxScrollSearch = 10,
                logging = true
            } = options;

            // --- collect logs ---
            const logs = [];
            const log = (...args) => {
                const ts = new Date().toTimeString().split(" ")[0];
                const message = `[ReplyExpander ${ts}] ${args.join(" ")}`;
                logs.push(message);
                if (logging) console.log(message);
            };

            const container = document.querySelector(containerSelector);
            if (!container) {
                const errorMsg = `Container not found for selector '${containerSelector}'`;
                log("ERROR:", errorMsg);
                return {
                error: errorMsg,
                clickedCount: 0,
                clickedTexts: [],
                logs,
                timestamp: new Date().toISOString()
                };
            }

            const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
            const randomPause = (base = basePauseMs, factor = [0.8, 1.6]) => {
                const [low, high] = factor;
                const delay = base * (Math.random() * (high - low) + low);
                return sleep(delay);
            };

            async function gentleScroll(el) {
                const behavior = Math.random() < 0.7 ? "smooth" : "auto";
                el.scrollIntoView({ behavior, block: "center" });
                if (Math.random() < 0.4) {
                const jitter = (Math.random() - 0.5) * 200;
                container.scrollBy(0, jitter);
                }
                log("Scrolled element into view");
                await randomPause(basePauseMs * (1 + Math.random()));
            }

            async function clickWithDelay(el) {
                try {
                await randomPause(250 + Math.random() * 400);
                el.click();
                log("Clicked:", (el.innerText || "").trim());
                await randomPause(200 + Math.random() * 300);
                } catch (e) {
                log("WARN: Click failed, trying dispatchEvent");
                try {
                    el.dispatchEvent(
                    new MouseEvent("click", { bubbles: true, cancelable: true, view: window })
                    );
                } catch {}
                }
            }

            function getCandidates() {
                const all = [...container.querySelectorAll(buttonSelector)];
                const filtered = all.filter((el) => {
                const text = (el.innerText || "").trim();
                return pattern.test(text) && !el.dataset.clicked && el.offsetParent !== null;
                });
                log("Found", filtered.length, "clickable buttons");
                return filtered;
            }

            async function waitForDOMChange(timeout = 3000) {
                return new Promise((resolve) => {
                let changed = false;
                const obs = new MutationObserver((mutations) => {
                    if (mutations.some((m) => m.addedNodes.length > 0)) {
                    changed = true;
                    obs.disconnect();
                    resolve(true);
                    }
                });
                obs.observe(container, { childList: true, subtree: true });
                setTimeout(() => {
                    if (!changed) obs.disconnect();
                    resolve(false);
                }, timeout);
                });
            }

            async function gentleSearchScroll(step = 0.4, maxTries = 10) {
                for (let i = 0; i < maxTries; i++) {
                const delta = container.clientHeight * (step + Math.random() * 0.3);
                container.scrollBy(0, delta);
                log(`Search scroll ${i + 1}/${maxTries}, delta=${Math.round(delta)}px`);
                await randomPause(basePauseMs * 1.2);
                const found = getCandidates();
                if (found.length) return true;
                const newNodes = await waitForDOMChange(1500);
                if (newNodes) {
                    const newFound = getCandidates();
                    if (newFound.length) return true;
                }
                }
                return false;
            }

            const clickedTexts = [];
            let clickedCount = 0;

            log("Starting clickAllReplyButtons");

            for (let i = 0; i < maxClicks; i++) {
                let candidates = getCandidates();

                if (!candidates.length) {
                log("No buttons visible, starting gentle search scroll");
                const found = await gentleSearchScroll(0.4, maxScrollSearch);
                if (!found) {
                    log("No new buttons found after search, finishing");
                    break;
                }
                candidates = getCandidates();
                if (!candidates.length) break;
                }

                const el = candidates[0];
                const txt = (el.innerText || "").trim();
                await gentleScroll(el);

                if (Math.random() < longPauseChance) {
                log("Taking a longer 'reading' pause");
                await sleep(basePauseMs * (2 + Math.random() * 2));
                }

                await clickWithDelay(el);
                el.dataset.clicked = "1";
                clickedTexts.push(txt);
                clickedCount++;

                await waitForDOMChange(3000);
                if (Math.random() < 0.15) {
                log("Idle pause");
                await randomPause(basePauseMs * 2);
                }
            }

            await sleep(settleWaitMs);
            log(`Finished. Total clicks: ${clickedCount}`);

            return {
                clickedCount,
                clickedTexts,
                logs,
                timestamp: new Date().toISOString(),
            };
            }

        """

    def _build_js_payload(self) -> str:
        """Injects runtime options into the JS."""
        core = self._js_core()
        return f"""
        const fn = {core};
        return await fn({{
          containerSelector: '{self.container_selector}',
          buttonSelector: '{self.button_selector}',
          maxClicks: {self.max_clicks},
          basePauseMs: {self.base_pause_ms},
          longPauseChance: {self.long_pause_chance},
          settleWaitMs: {self.settle_wait_ms}
        }});
        """

    def _execute_js(self, script: str) -> dict:
        """Runs JS inside the current page."""
        self.log.debug("Executing ReplyExpander JS...")
        try:
            return self.driver.execute_script(f"return (async ()=>{{ {script} }})()")
        except Exception as e:
            self.log.exception("JS execution failed")
            return {"error": str(e), "clickedCount": 0, "clickedTexts": []}

    # ---------- public interface ----------

    def expand_replies(self) -> dict:
        """Run the JS clicker and return structured result."""
        js_script = self._build_js_payload()
        result = self._execute_js(js_script)

        # Handle JS-side error
        if "error" in result:
            self.log.error(f"JS Error: {result['error']}")
            if result.get("logs"):
                for line in result["logs"]:
                    self.log.debug(f"[JS] {line}")
            return result

        # Normal success path
        clicked = result.get("clickedCount", 0)
        self.log.info(f"Clicked {clicked} reply buttons via JS.")

        # Log JS-side messages (if present)
        js_logs = result.get("logs", [])
        if js_logs:
            for line in js_logs:
                self.log.debug(f"[JS] {line}")

        return result


    def summary(self, result: dict) -> str:
        """Readable summary for logs or console output."""
        if "error" in result:
            err = result["error"]
            log_count = len(result.get("logs", []))
            return f"[ReplyExpander] ❌ Error: {err} (JS logs: {log_count} lines)"

        count = result.get("clickedCount", 0)
        texts = result.get("clickedTexts", [])
        logs = result.get("logs", [])
        log_tail = logs[-3:] if len(logs) > 3 else logs

        summary = f"[ReplyExpander] ✅ Clicked {count} buttons"
        if texts:
            summary += f": {', '.join(t[:40] for t in texts)}"
        if logs:
            summary += f" | JS logs ({len(logs)} total, last few): " + " / ".join(log_tail)
        return summary

    def only_scroll(
        self,
        container_selector: str | None = None,
        base_pause_ms: int = 400,
        idle_stop_seconds: int = 12,  # slightly longer buffer
        max_total_seconds: int = 60,
        scroll_steps: int = 25,
    ):
        """
        Human-like scrolling with reading pauses, micro-jitters, and safe idle handling.
        Does not exit prematurely during reading pauses.
        """
        container = container_selector or self.container_selector

        js_script = f"""
        (async function humanScrollFixed() {{
        const containerSelector = {json.dumps(container)};
        const basePauseMs = {base_pause_ms};
        const idleStopMs = {idle_stop_seconds * 1000};
        const maxTotalMs = {max_total_seconds * 1000};
        const maxSteps = {scroll_steps};
        const logs = [];

        // === Setup log overlay ===
        let logDiv = document.getElementById("scrollLogs");
        if (!logDiv) {{
            logDiv = document.createElement("div");
            logDiv.id = "scrollLogs";
            logDiv.style.cssText = `
            position: fixed;
            bottom: 0; left: 0;
            background: rgba(0,0,0,0.7);
            color: #0f0;
            font: 12px monospace;
            padding: 6px;
            max-height: 30vh;
            overflow-y: auto;
            z-index: 999999;
            white-space: pre-line;
            `;
            document.body.appendChild(logDiv);
        }}

        const addLog = (msg) => {{
            const time = new Date().toTimeString().split(" ")[0];
            const line = `[{{time}}] ${{msg}}`;
            console.log(line);
            logs.push(line);
            const node = document.createElement("div");
            node.textContent = line;
            logDiv.appendChild(node);
            logDiv.scrollTop = logDiv.scrollHeight;
        }};

        const sleep = (ms) => new Promise(r => setTimeout(r, ms));
        const rand = (min, max) => Math.random() * (max - min) + min;
        const randomPause = (base = basePauseMs) => sleep(base * rand(0.7, 1.8));

        // === Resolve container ===
        const container = document.querySelector(containerSelector);
        if (!container) {{
            const msg = `❌ Container not found: ${{containerSelector}}`;
            addLog(msg);
            return {{ status: "error", reason: msg, logs }};
        }}

        let lastHeight = container.scrollHeight;
        let lastNodes = container.querySelectorAll("*").length;
        let lastChange = performance.now();
        let start = performance.now();
        let newNodes = 0;

        addLog(`✅ Started human-like scroll (idleStop={idle_stop_seconds}s)`);

        async function smoothScrollStep(down = true) {{
            const totalDistance = container.clientHeight * (down ? rand(0.3, 0.9) : -rand(0.1, 0.4));
            const segments = Math.floor(rand(3, 7));
            const segmentDistance = totalDistance / segments;
            for (let i = 0; i < segments; i++) {{
            container.scrollBy({{ top: segmentDistance, behavior: "smooth" }});
            await sleep(rand(40, 120));
            }}
            if (Math.random() < 0.3) {{
            container.scrollBy({{ top: rand(-40, 40), behavior: "auto" }});
            await sleep(rand(60, 150));
            }}
        }}

        for (let step = 1; step <= maxSteps; step++) {{
            const now = performance.now();
            if (now - start > maxTotalMs) {{
            addLog("⏰ Max total time reached — EXIT.");
            break;
            }}

            const down = Math.random() < 0.85;
            addLog(`Step ${{step}}/${{maxSteps}}: scrolling ${{down ? "down" : "up"}}...`);
            await smoothScrollStep(down);
            await randomPause(basePauseMs);

            // Occasionally simulate a reading pause
            if (Math.random() < 0.15) {{
            const longPause = basePauseMs * rand(3, 6);
            addLog(`⏸️ Reading pause (~${{Math.round(longPause)}}ms)`);
            // mark this as 'activity' so idle detection doesn't trigger
            lastChange = performance.now();
            await sleep(longPause);
            lastChange = performance.now(); // refresh again after pause
            }}

            const newHeight = container.scrollHeight;
            const newCount = container.querySelectorAll("*").length;
            if (newHeight > lastHeight + 5 || newCount > lastNodes) {{
            addLog(`🟢 Change: height ${{lastHeight}}→${{newHeight}}, nodes ${{lastNodes}}→${{newCount}}`);
            lastHeight = newHeight;
            lastNodes = newCount;
            lastChange = performance.now();
            newNodes++;
            }}

            if (performance.now() - lastChange > idleStopMs) {{
            addLog(`🟡 EXIT: No new content or DOM change for ${{idleStopMs / 1000}}s.`);
            break;
            }}
        }}

        const totalTime = performance.now() - start;
        addLog(`✅ Finished scroll (${scroll_steps} steps or idle timeout).`);

        return {{
            status: "done",
            steps: {scroll_steps},
            newNodes,
            totalTimeMs: totalTime,
            logs,
            timestamp: new Date().toISOString()
        }};
        }})();
        """

        try:
            result = self.driver.execute_script(f"return (async () => {{ return await {js_script}; }})()")
        except Exception as e:
            self.log.exception("Failed to execute human-like only_scroll JS")
            return {"status": "error", "reason": str(e)}

        if isinstance(result, dict):
            for line in result.get("logs", []):
                self.log.debug(f"[HumanScrollFixed] {line}")
        else:
            self.log.warning(f"Unexpected result from JS: {result}")

        return result
