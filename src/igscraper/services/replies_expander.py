import json
from selenium.webdriver import ActionChains, Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
import time
import random
from datetime import datetime, timezone
from typing import Optional
import logging
from igscraper.logger import get_logger

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
        logger: Optional[logging.Logger] = None,
        is_headless: bool = False,
    ):
        self.driver = driver
        self.container_selector = container_selector
        self.button_selector = button_selector
        self.max_clicks = max_clicks
        self.base_pause_ms = base_pause_ms
        self.long_pause_chance = long_pause_chance
        self.settle_wait_ms = settle_wait_ms
        # Use provided logger or fallback to get_logger() which respects config.toml
        self.log = logger or get_logger(__name__)
        self.is_headless = is_headless

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

    # ------------------------------------------------------------
    # Docker / headless detection
    # ------------------------------------------------------------
    def _is_headless(self) -> bool:
        return self.is_headless

    # ------------------------------------------------------------
    # JS wheel primitives (injected once)
    # ------------------------------------------------------------
    def _js_wheel_primitives(self) -> str:
        return r"""
        function igWheelScroll(container, delta) {
            if (!container) return null;

            container.dispatchEvent(new WheelEvent("wheel", {
                deltaY: delta,
                bubbles: true,
                cancelable: true
            }));

            container.scrollTop += delta;

            return {
                scrollTop: container.scrollTop,
                scrollHeight: container.scrollHeight,
                ts: performance.now()
            };
        }

        function nextFrame() {
            return new Promise(r => requestAnimationFrame(r));
        }
        """

    # ------------------------------------------------------------
    # Core JS logic (MINIMALLY patched)
    # ------------------------------------------------------------
    def _js_core(self) -> str:
        return r"""
        async function clickAllReplyButtons(options = {}) {
            const {
                containerSelector,
                buttonSelector,
                maxClicks,
                basePauseMs,
                longPauseChance,
                settleWaitMs,
                useWheelScroll = false
            } = options;

            const logs = [];
            const log = (...args) => logs.push(args.join(" "));

            const container = document.querySelector(containerSelector);
            if (!container) {
                return { error: "Container not found", logs };
            }

            const sleep = ms => new Promise(r => setTimeout(r, ms));
            const rand = (a, b) => Math.random() * (b - a) + a;

            function scrollDelta(delta) {
                if (useWheelScroll) {
                    igWheelScroll(container, delta);
                    return nextFrame();
                } else {
                    container.scrollBy(0, delta);
                }
            }

            function getCandidates() {
                const all = [...container.querySelectorAll(buttonSelector)];
                return all.filter(el => {
                    const t = (el.innerText || "").toLowerCase();
                    return (
                        !el.dataset.clicked &&
                        el.offsetParent !== null &&
                        /(view|show|see).*(repl|more|all)/i.test(t)
                    );
                });
            }

            async function gentleSearchScroll(step = 0.4, tries = 8) {
                for (let i = 0; i < tries; i++) {
                    const delta = container.clientHeight * (step + Math.random() * 0.3);
                    await scrollDelta(delta);
                    await sleep(basePauseMs * rand(0.8, 1.3));
                    // 👀 Occasional scan pause while searching
                    if (Math.random() < 0.25) {
                        const scanPause = basePauseMs * rand(1.5, 3.0);
                        log("👀 Scanning comments ~" + Math.round(scanPause) + "ms");
                        await sleep(scanPause);
                    }
                    if (getCandidates().length) return true;
                }
                return false;
            }

            async function clickWithPause(el) {
                await sleep(200 + Math.random() * 400);
                el.click();
                if (useWheelScroll) {
                    igWheelScroll(container, 200);
                    await nextFrame();
                }
                await sleep(200 + Math.random() * 300);
            }

            let clicked = 0;
            const clickedTexts = [];

            for (let i = 0; i < maxClicks; i++) {
                let candidates = getCandidates();
                if (!candidates.length) {
                    const found = await gentleSearchScroll();
                    if (!found) break;
                    candidates = getCandidates();
                    if (!candidates.length) break;
                }

                const el = candidates[0];
                const txt = (el.innerText || "").trim();

                el.scrollIntoView({ block: "center", behavior: "auto" });
                await sleep(basePauseMs * rand(0.7, 1.3));

                if (Math.random() < longPauseChance) {
                    await sleep(basePauseMs * rand(2, 4));
                }

                await clickWithPause(el);
                el.dataset.clicked = "1";
                clicked++;
                clickedTexts.push(txt);
                // 🧠 Occasional human reading pause after expanding replies
                if (Math.random() < 0.3) {
                    const pause = basePauseMs * rand(1.5, 3.5);
                    log("📖 Reading replies ~" + Math.round(pause) + "ms");
                    await sleep(pause);
                }
            }

            await sleep(settleWaitMs);

            return {
                clickedCount: clicked,
                clickedTexts,
                logs,
                timestamp: new Date().toISOString()
            };
        }
        """

    # ------------------------------------------------------------
    # JS payload builder
    # ------------------------------------------------------------
    def _build_js_payload(self) -> str:
        use_wheel = self.is_headless
        return f"""
        {self._js_wheel_primitives()}
        const fn = {self._js_core()};
        return await fn({{
            containerSelector: {json.dumps(self.container_selector)},
            buttonSelector: {json.dumps(self.button_selector)},
            maxClicks: {self.max_clicks},
            basePauseMs: {self.base_pause_ms},
            longPauseChance: {self.long_pause_chance},
            settleWaitMs: {self.settle_wait_ms},
            useWheelScroll: {str(use_wheel).lower()}
        }});
        """

    # ------------------------------------------------------------
    # Execute JS
    # ------------------------------------------------------------
    def _execute_js(self, script: str) -> dict:
        try:
            return self.driver.execute_script(
                "return (async () => { " + script + " })();"
            )
        except Exception as e:
            self.log.exception("JS execution failed")
            return {"error": str(e), "clickedCount": 0, "clickedTexts": []}

    # ------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------
    def expand_replies(self) -> dict:
        result = self._execute_js(self._build_js_payload())

        if "error" in result:
            self.log.error(result["error"])
            return result

        self.log.info(f"Clicked {result.get('clickedCount', 0)} reply buttons")

        for line in result.get("logs", []):
            self.log.debug(f"[JS] {line}")

        return result



    # ---------- internal building blocks ----------

    # def _js_core(self) -> str:
    #     """JavaScript logic injected into the browser."""
    #     return r"""
    #         async function clickAllReplyButtons(options = {}) {
    #         const {
    #             containerSelector = "div.html-div",
    #             buttonSelector = 'div[role="button"][tabindex="0"], a, button, span',
    #             pattern = /\b(view|show|see).*(repl|more|all)\b/i,
    #             maxClicks = 10,
    #             basePauseMs = 400,
    #             longPauseChance = 0.12,
    #             settleWaitMs = 2000,
    #             maxScrollSearch = 10,
    #             logging = true
    #         } = options;

    #         // --- collect logs ---
    #         const logs = [];
    #         const log = (...args) => {
    #             const ts = new Date().toTimeString().split(" ")[0];
    #             const message = `[ReplyExpander ${ts}] ${args.join(" ")}`;
    #             logs.push(message);
    #             if (logging) console.log(message);
    #         };

    #         const container = document.querySelector(containerSelector);
    #         if (!container) {
    #             const errorMsg = `Container not found for selector '${containerSelector}'`;
    #             log("ERROR:", errorMsg);
    #             return {
    #             error: errorMsg,
    #             clickedCount: 0,
    #             clickedTexts: [],
    #             logs,
    #             timestamp: new Date().toISOString()
    #             };
    #         }

    #         const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    #         const randomPause = (base = basePauseMs, factor = [0.8, 1.6]) => {
    #             const [low, high] = factor;
    #             const delay = base * (Math.random() * (high - low) + low);
    #             return sleep(delay);
    #         };

    #         async function gentleScroll(el) {
    #             const behavior = Math.random() < 0.7 ? "smooth" : "auto";
    #             el.scrollIntoView({ behavior, block: "center" });
    #             if (Math.random() < 0.4) {
    #             const jitter = (Math.random() - 0.5) * 200;
    #             container.scrollBy(0, jitter);
    #             }
    #             log("Scrolled element into view");
    #             await randomPause(basePauseMs * (1 + Math.random()));
    #         }

    #         async function clickWithDelay(el) {
    #             try {
    #             await randomPause(250 + Math.random() * 400);
    #             el.click();
    #             log("Clicked:", (el.innerText || "").trim());
    #             await randomPause(200 + Math.random() * 300);
    #             } catch (e) {
    #             log("WARN: Click failed, trying dispatchEvent");
    #             try {
    #                 el.dispatchEvent(
    #                 new MouseEvent("click", { bubbles: true, cancelable: true, view: window })
    #                 );
    #             } catch {}
    #             }
    #         }

    #         function getCandidates() {
    #             const all = [...container.querySelectorAll(buttonSelector)];
    #             const filtered = all.filter((el) => {
    #             const text = (el.innerText || "").trim();
    #             return pattern.test(text) && !el.dataset.clicked && el.offsetParent !== null;
    #             });
    #             log("Found", filtered.length, "clickable buttons");
    #             return filtered;
    #         }

    #         async function waitForDOMChange(timeout = 3000) {
    #             return new Promise((resolve) => {
    #             let changed = false;
    #             const obs = new MutationObserver((mutations) => {
    #                 if (mutations.some((m) => m.addedNodes.length > 0)) {
    #                 changed = true;
    #                 obs.disconnect();
    #                 resolve(true);
    #                 }
    #             });
    #             obs.observe(container, { childList: true, subtree: true });
    #             setTimeout(() => {
    #                 if (!changed) obs.disconnect();
    #                 resolve(false);
    #             }, timeout);
    #             });
    #         }

    #         async function gentleSearchScroll(step = 0.4, maxTries = 10) {
    #             for (let i = 0; i < maxTries; i++) {
    #             const delta = container.clientHeight * (step + Math.random() * 0.3);
    #             container.scrollBy(0, delta);
    #             log(`Search scroll ${i + 1}/${maxTries}, delta=${Math.round(delta)}px`);
    #             await randomPause(basePauseMs * 1.2);
    #             const found = getCandidates();
    #             if (found.length) return true;
    #             const newNodes = await waitForDOMChange(1500);
    #             if (newNodes) {
    #                 const newFound = getCandidates();
    #                 if (newFound.length) return true;
    #             }
    #             }
    #             return false;
    #         }

    #         const clickedTexts = [];
    #         let clickedCount = 0;

    #         log("Starting clickAllReplyButtons");

    #         for (let i = 0; i < maxClicks; i++) {
    #             let candidates = getCandidates();

    #             if (!candidates.length) {
    #             log("No buttons visible, starting gentle search scroll");
    #             const found = await gentleSearchScroll(0.4, maxScrollSearch);
    #             if (!found) {
    #                 log("No new buttons found after search, finishing");
    #                 break;
    #             }
    #             candidates = getCandidates();
    #             if (!candidates.length) break;
    #             }

    #             const el = candidates[0];
    #             const txt = (el.innerText || "").trim();
    #             await gentleScroll(el);

    #             if (Math.random() < longPauseChance) {
    #             log("Taking a longer 'reading' pause");
    #             await sleep(basePauseMs * (2 + Math.random() * 2));
    #             }

    #             await clickWithDelay(el);
    #             el.dataset.clicked = "1";
    #             clickedTexts.push(txt);
    #             clickedCount++;

    #             await waitForDOMChange(3000);
    #             if (Math.random() < 0.15) {
    #             log("Idle pause");
    #             await randomPause(basePauseMs * 2);
    #             }
    #         }

    #         await sleep(settleWaitMs);
    #         log(`Finished. Total clicks: ${clickedCount}`);

    #         return {
    #             clickedCount,
    #             clickedTexts,
    #             logs,
    #             timestamp: new Date().toISOString(),
    #         };
    #         }

    #     """
    #     # // --- wheel primitive injected from Python ---

    # def _build_js_payload(self) -> str:
    #     """Injects runtime options into the JS."""
    #     core = self._js_core()
    #     return f"""
    #     const fn = {core};
    #     return await fn({{
    #       containerSelector: '{self.container_selector}',
    #       buttonSelector: '{self.button_selector}',
    #       maxClicks: {self.max_clicks},
    #       basePauseMs: {self.base_pause_ms},
    #       longPauseChance: {self.long_pause_chance},
    #       settleWaitMs: {self.settle_wait_ms}
    #     }});
    #     """

    # def _execute_js(self, script: str) -> dict:
    #     """Runs JS inside the current page."""
    #     self.log.debug("Executing ReplyExpander JS...")
    #     try:
    #         return self.driver.execute_script(f"return (async ()=>{{ {script} }})()")
    #     except Exception as e:
    #         self.log.exception("JS execution failed")
    #         return {"error": str(e), "clickedCount": 0, "clickedTexts": []}

    # ---------- public interface ----------

    # def expand_replies(self) -> dict:
    #     """Run the JS clicker and return structured result."""
    #     js_script = self._build_js_payload()
    #     result = self._execute_js(js_script)

    #     # Handle JS-side error
    #     if "error" in result:
    #         self.log.error(f"JS Error: {result['error']}")
    #         if result.get("logs"):
    #             for line in result["logs"]:
    #                 self.log.debug(f"[JS] {line}")
    #         return result

    #     # Normal success path
    #     clicked = result.get("clickedCount", 0)
    #     self.log.info(f"Clicked {clicked} reply buttons via JS.")

    #     # Log JS-side messages (if present)
    #     js_logs = result.get("logs", [])
    #     if js_logs:
    #         for line in js_logs:
    #             self.log.debug(f"[JS] {line}")

    #     return result


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


    def only_scrollOG(
        self,
        container_selector: str | None = None,
        base_pause_ms: int = 400,
        idle_stop_seconds: int = 12,
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
                const line = "[" + time + "] " + msg;
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
                const msg = "❌ Container not found: " + containerSelector;
                addLog(msg);
                return {{ status: "error", reason: msg, logs }};
            }}

            // === SEMANTIC SIGNAL: unique usernames via profile anchors ===
            const getUsernameSet = () => {{
                return new Set(
                    Array.from(container.querySelectorAll('a[href^="/"][role="link"]'))
                        .map(a => a.textContent && a.textContent.trim())
                        .filter(name => name && name.length > 1 && !name.includes(" "))
                );
            }};

            let lastUserSet = getUsernameSet();
            let lastChange = performance.now();
            let start = performance.now();
            let newEvents = 0;
            let idleNoNewContent = false;

            addLog("✅ Started human-like scroll (idleStop=" + ({idle_stop_seconds}) + "s)");
            addLog(
                "👤 Initial usernames (" +
                lastUserSet.size +
                "): " +
                Array.from(lastUserSet).join(", ")
            );

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
                addLog("Step " + step + "/" + maxSteps + ": scrolling " + (down ? "down" : "up") + "...");
                await smoothScrollStep(down);
                await randomPause(basePauseMs);

                // Reading pause
                if (Math.random() < 0.15) {{
                    const longPause = basePauseMs * rand(3, 6);
                    addLog("⏸️ Reading pause (~" + Math.round(longPause) + "ms)");
                    lastChange = performance.now();
                    await sleep(longPause);
                    lastChange = performance.now();
                }}

                const currentUserSet = getUsernameSet();
                addLog(
                    "👤 Username check: last=" +
                    lastUserSet.size +
                    ", current=" +
                    currentUserSet.size
                );

                if (currentUserSet.size > lastUserSet.size) {{
                    const diff = Array.from(currentUserSet).filter(x => !lastUserSet.has(x));
                    addLog("🟢 New commenters detected: " + diff.join(", "));
                    lastUserSet = currentUserSet;
                    lastChange = performance.now();
                    newEvents++;
                }}

                const idleFor = performance.now() - lastChange;
                addLog("⏱ Idle timer: " + Math.round(idleFor) + "ms");

                if (idleFor > idleStopMs) {{
                    addLog("🟡 EXIT: No new commenters for " + (idleStopMs / 1000) + "s.");
                    idleNoNewContent = true;
                    break;
                }}
            }}

            const totalTime = performance.now() - start;
            addLog("✅ Finished scroll (" + maxSteps + " steps or idle timeout).");

            return {{
                status: "done",
                steps: maxSteps,
                new_events: newEvents,
                idle_no_new_content: idleNoNewContent,
                totalTimeMs: totalTime,
                logs,
                timestamp: new Date().toISOString()
            }};
        }})();
        """


        try:
            result = self.driver.execute_script(
                f"return (async () => {{ return await {js_script}; }})()"
            )
        except Exception as e:
            self.log.exception("Failed to execute human-like only_scroll JS")
            return {"status": "error", "reason": str(e)}

        if isinstance(result, dict):
            for line in result.get("logs", []):
                self.log.debug(f"[HumanScrollFixed] {line}")
        else:
            self.log.warning(f"Unexpected result from JS: {result}")

        return result


    # def only_scroll(
    #     self,
    #     container_selector: str | None = None,
    #     base_pause_ms: int = 400,
    #     idle_stop_seconds: int = 12,
    #     max_total_seconds: int = 60,
    #     scroll_steps: int = 25,
    # ):
    #     """
    #     Human-like scrolling with reading pauses, micro-jitters, and safe idle handling.
    #     Adds wheel-based scrolling ONLY in headless/Docker.
    #     """

    #     container = container_selector or self.container_selector

    #     # --- detect headless / docker ---
    #     use_wheel = self.is_headless
    #     js_script = f"""
    #     (async function humanScrollFixed() {{
    #         const containerSelector = {json.dumps(container)};
    #         const basePauseMs = {base_pause_ms};
    #         const idleStopMs = {idle_stop_seconds * 1000};
    #         const maxTotalMs = {max_total_seconds * 1000};
    #         const maxSteps = {scroll_steps};
    #         const useWheelScroll = {str(use_wheel).lower()};
    #         const logs = [];

    #         // ---- wheel primitives (safe no-op if unused) ----
    #         function igWheelScroll(container, delta) {{
    #             if (!container) return;
    #             container.dispatchEvent(new WheelEvent("wheel", {{
    #                 deltaY: delta,
    #                 bubbles: true,
    #                 cancelable: true
    #             }}));
    #             container.scrollTop += delta;
    #         }}

    #         function nextFrame() {{
    #             return new Promise(r => requestAnimationFrame(r));
    #         }}

    #         // === Setup log overlay ===
    #         let logDiv = document.getElementById("scrollLogs");
    #         if (!logDiv) {{
    #             logDiv = document.createElement("div");
    #             logDiv.id = "scrollLogs";
    #             logDiv.style.cssText = `
    #                 position: fixed;
    #                 bottom: 0; left: 0;
    #                 background: rgba(0,0,0,0.7);
    #                 color: #0f0;
    #                 font: 12px monospace;
    #                 padding: 6px;
    #                 max-height: 30vh;
    #                 overflow-y: auto;
    #                 z-index: 999999;
    #                 white-space: pre-line;
    #             `;
    #             document.body.appendChild(logDiv);
    #         }}

    #         const addLog = (msg) => {{
    #             const time = new Date().toTimeString().split(" ")[0];
    #             const line = "[" + time + "] " + msg;
    #             console.log(line);
    #             logs.push(line);
    #             const node = document.createElement("div");
    #             node.textContent = line;
    #             logDiv.appendChild(node);
    #             logDiv.scrollTop = logDiv.scrollHeight;
    #         }};

    #         const sleep = (ms) => new Promise(r => setTimeout(r, ms));
    #         const rand = (min, max) => Math.random() * (max - min) + min;
    #         const randomPause = (base = basePauseMs) => sleep(base * rand(0.7, 1.8));

    #         const raw = document.querySelector(containerSelector);
    #         if (!raw) {{
    #             addLog("❌ Container not found: " + containerSelector);
    #             return {{ status: "error", logs }};
    #         }}

    #         function resolveScrollOwner(el) {{
    #             let cur = el;
    #             while (cur && cur !== document.body) {{
    #                 const s = getComputedStyle(cur);
    #                 if (
    #                     /(auto|scroll)/.test(s.overflowY) &&
    #                     cur.scrollHeight > cur.clientHeight + 5
    #                 ) {{
    #                     return cur;
    #                 }}
    #                 cur = cur.parentElement;
    #             }}
    #             return document.scrollingElement || document.documentElement;
    #         }}

    #         const contentEl = raw;
    #         const scrollEl = resolveScrollOwner(raw);
    #         addLog("🧭 Scroll owner resolved → " + scrollEl.tagName);



    #         const getUsernameSet = () => new Set(
    #             Array.from(container.querySelectorAll('a[href^="/"][role="link"]'))
    #                 .map(a => a.textContent && a.textContent.trim())
    #                 .filter(name => name && name.length > 1 && !name.includes(" "))
    #         );

    #         let lastUserSet = getUsernameSet();
    #         let lastChange = performance.now();
    #         let start = performance.now();
    #         let newEvents = 0;
    #         let idleNoNewContent = false;

    #         addLog("✅ Started human-like scroll (wheel=" + useWheelScroll + ")");
    #         addLog("👤 Initial usernames (" + lastUserSet.size + "): " + Array.from(lastUserSet).join(", "));

    #         async function smoothScrollStep(down = true) {{
    #             const totalDistance =
    #                 container.clientHeight * (down ? rand(0.3, 0.9) : -rand(0.1, 0.4));
    #             const segments = Math.floor(rand(3, 7));
    #             const segmentDistance = totalDistance / segments;

    #             for (let i = 0; i < segments; i++) {{
    #                 if (useWheelScroll) {{
    #                     const wheelDelta = Math.sign(segmentDistance) * Math.max(120, Math.abs(segmentDistance));
    #                     igWheelScroll(container, wheelDelta);
    #                     await nextFrame();
    #                 }} else {{
    #                     container.scrollBy({{ top: segmentDistance, behavior: "smooth" }});
    #                     await sleep(rand(40, 120));
    #                 }}
    #             }}

    #             if (Math.random() < 0.3) {{
    #                 const jitter = rand(-40, 40);
    #                 if (useWheelScroll) {{
    #                     igWheelScroll(container, jitter);
    #                     await nextFrame();
    #                 }} else {{
    #                     container.scrollBy({{ top: jitter, behavior: "auto" }});
    #                     await sleep(rand(60, 150));
    #                 }}
    #             }}
    #         }}

    #         for (let step = 1; step <= maxSteps; step++) {{
    #             if (performance.now() - start > maxTotalMs) {{
    #                 addLog("⏰ Max total time reached — EXIT.");
    #                 break;
    #             }}

    #             const down = Math.random() < 0.85;
    #             addLog("Step " + step + "/" + maxSteps + ": scrolling " + (down ? "down" : "up"));
    #             await smoothScrollStep(down);
    #             await randomPause(basePauseMs);

    #             if (Math.random() < 0.15) {{
    #                 const longPause = basePauseMs * rand(3, 6);
    #                 addLog("⏸️ Reading pause (~" + Math.round(longPause) + "ms)");
    #                 lastChange = performance.now();
    #                 await sleep(longPause);
    #                 lastChange = performance.now();
    #             }}

    #             const currentUserSet = getUsernameSet();

    #             addLog(
    #                 "👤 Username check: last=" +
    #             lastUserSet.size +
    #             ", current=" +
    #             currentUserSet.size
    #             );

    #             if (currentUserSet.size > lastUserSet.size) {{
    #                 const diff = Array.from(currentUserSet).filter(x => !lastUserSet.has(x));
    #                 addLog("🟢 New commenters detected: " + diff.join(", "));
    #                 lastUserSet = currentUserSet;
    #                 lastChange = performance.now();
    #                 newEvents++;
    #             }}


    #             const idleFor = performance.now() - lastChange;
    #             addLog("⏱ Idle timer: " + Math.round(idleFor) + "ms");

    #             if (idleFor > idleStopMs) {{
    #                 addLog("🟡 EXIT: No new commenters for " + (idleStopMs / 1000) + "s.");
    #                 idleNoNewContent = true;
    #                 break;
    #             }}

    #         }}

    #         addLog("✅ Finished scroll");

    #         return {{
    #             status: "done",
    #             steps: maxSteps,
    #             new_events: newEvents,
    #             idle_no_new_content: idleNoNewContent,
    #             logs,
    #             timestamp: new Date().toISOString()
    #         }};
    #     }})();
    #     """

    #     try:
    #         result = self.driver.execute_script(
    #             f"return (async () => {{ return await {js_script}; }})()"
    #         )
    #     except Exception as e:
    #         self.log.exception("Failed to execute human-like only_scroll JS")
    #         return {"status": "error", "reason": str(e)}

    #     if isinstance(result, dict):
    #         for line in result.get("logs", []):
    #             self.log.debug(f"[HumanScrollFixed] {line}")

    #     return result

    def only_scrollWorkingVersionExceptDocker(
        self,
        container_selector: str | None = None,
        base_pause_ms: int = 400,
        idle_stop_seconds: int = 12,
        max_total_seconds: int = 60,
        scroll_steps: int = 25,
    ):
        """
        Human-like scrolling with reading pauses, micro-jitters, and safe idle handling.
        Adds wheel-based scrolling ONLY in headless/Docker.
        """

        container = container_selector or self.container_selector
        use_wheel = self.is_headless

        js_script = f"""
        (async function humanScrollFixed() {{
            const containerSelector = {json.dumps(container)};
            const basePauseMs = {base_pause_ms};
            const idleStopMs = {idle_stop_seconds * 1000};
            const maxTotalMs = {max_total_seconds * 1000};
            const maxSteps = {scroll_steps};
            const useWheelScroll = {str(use_wheel).lower()};
            const logs = [];

            function igWheelScroll(el, delta) {{
                if (!el) return;
                el.dispatchEvent(new WheelEvent("wheel", {{
                    deltaY: delta,
                    bubbles: true,
                    cancelable: true
                }}));
                el.scrollTop += delta;
            }}

            function nextFrame() {{
                return new Promise(r => requestAnimationFrame(r));
            }}



            // 🔑 IG-native scroll stimulus (CRITICAL IN HEADLESS)
            function nudgeInstagram() {{
                try {{
                    const focusTarget =
                        document.querySelector('textarea') ||
                        document.querySelector('input') ||
                        document.querySelector('button, div[role="button"]') ||
                        document.body;

                    focusTarget.focus();

                    document.dispatchEvent(
                        new KeyboardEvent("keydown", {{
                            key: "PageDown",
                            code: "PageDown",
                            bubbles: true
                        }})
                    );
                }} catch (e) {{}}
            }}

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
                const line = "[" + time + "] " + msg;
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

            const raw = document.querySelector(containerSelector);
            if (!raw) {{
                addLog("❌ Container not found: " + containerSelector);
                return {{ status: "error", logs }};
            }}

            function resolveScrollOwner(el) {{
                let cur = el;
                while (cur && cur !== document.body) {{
                    const s = getComputedStyle(cur);
                    if (
                        /(auto|scroll)/.test(s.overflowY) &&
                        cur.scrollHeight > cur.clientHeight + 5
                    ) {{
                        return cur;
                    }}
                    cur = cur.parentElement;
                }}
                return document.scrollingElement || document.documentElement;
            }}

            const contentEl = raw;
            const scrollEl = resolveScrollOwner(raw);
            addLog("🧭 Scroll owner resolved → " + scrollEl.tagName);

            const getUsernameSet = () => new Set(
                Array.from(contentEl.querySelectorAll('a[href^="/"][role="link"]'))
                    .map(a => a.textContent && a.textContent.trim())
                    .filter(name => name && name.length > 1 && !name.includes(" "))
            );

            let lastUserSet = getUsernameSet();
            let lastChange = performance.now();
            let start = performance.now();
            let newEvents = 0;
            let idleNoNewContent = false;

            addLog("✅ Started human-like scroll (wheel=" + useWheelScroll + ")");
            addLog("👤 Initial usernames (" + lastUserSet.size + "): " + Array.from(lastUserSet).join(", "));

            async function smoothScrollStep(down = true) {{
                const totalDistance =
                    scrollEl.clientHeight * (down ? rand(0.3, 0.9) : -rand(0.1, 0.4));
                const segments = Math.floor(rand(3, 7));
                const segmentDistance = totalDistance / segments;

                for (let i = 0; i < segments; i++) {{
                    if (useWheelScroll) {{
                        const wheelDelta = Math.sign(segmentDistance) * Math.max(120, Math.abs(segmentDistance));
                        igWheelScroll(scrollEl, wheelDelta);
                        await nextFrame();
                    }} else {{
                        scrollEl.scrollBy({{ top: segmentDistance, behavior: "smooth" }});
                        await sleep(rand(40, 120));
                    }}
                    // 🔑 Force IG to react
                    nudgeInstagram();
                    await sleep(60);
                }}

                if (Math.random() < 0.3) {{
                    const jitter = rand(-40, 40);
                    if (useWheelScroll) {{
                        igWheelScroll(scrollEl, jitter);
                        await nextFrame();
                    }} else {{
                        scrollEl.scrollBy({{ top: jitter, behavior: "auto" }});
                        await sleep(rand(60, 150));
                    }}
                }}
            }}

            for (let step = 1; step <= maxSteps; step++) {{
                if (performance.now() - start > maxTotalMs) {{
                    addLog("⏰ Max total time reached — EXIT.");
                    break;
                }}

                const down = Math.random() < 0.85;
                addLog("Step " + step + "/" + maxSteps + ": scrolling " + (down ? "down" : "up"));
                await smoothScrollStep(down);
                await randomPause(basePauseMs);

                if (Math.random() < 0.15) {{
                    const longPause = basePauseMs * rand(3, 6);
                    addLog("⏸️ Reading pause (~" + Math.round(longPause) + "ms)");
                    lastChange = performance.now();
                    await sleep(longPause);
                    lastChange = performance.now();
                }}

                const currentUserSet = getUsernameSet();
                addLog("👤 Username check: last=" + lastUserSet.size + ", current=" + currentUserSet.size);

                if (currentUserSet.size > lastUserSet.size) {{
                    const diff = Array.from(currentUserSet).filter(x => !lastUserSet.has(x));
                    addLog("🟢 New commenters detected: " + diff.join(", "));
                    lastUserSet = currentUserSet;
                    lastChange = performance.now();
                    newEvents++;
                }}

                const idleFor = performance.now() - lastChange;
                addLog("⏱ Idle timer: " + Math.round(idleFor) + "ms");

                if (idleFor > idleStopMs) {{
                    addLog("🟡 EXIT: No new commenters for " + (idleStopMs / 1000) + "s.");
                    idleNoNewContent = true;
                    break;
                }}
            }}

            addLog("✅ Finished scroll");

            return {{
                status: "done",
                steps: maxSteps,
                new_events: newEvents,
                idle_no_new_content: idleNoNewContent,
                logs,
                timestamp: new Date().toISOString()
            }};
        }})();
        """

        try:
            result = self.driver.execute_script(
                f"return (async () => {{ return await {js_script}; }})()"
            )
        except Exception as e:
            self.log.exception("Failed to execute human-like only_scroll JS")
            return {"status": "error", "reason": str(e)}

        if isinstance(result, dict):
            for line in result.get("logs", []):
                self.log.debug(f"[HumanScrollFixed] {line}")

        return result

    def pauseVideo(self):
        JS_PAUSE_VIDEO = """
        var result = { paused: 0, videos: [] };

        try {
            document.querySelectorAll("video").forEach((v, idx) => {
                try {
                    var info = {
                        index: idx,
                        wasPaused: v.paused,
                        currentTime: v.currentTime
                    };

                    // Pause playback
                    if (!v.paused) {
                        v.pause();
                        result.paused++;
                    }

                    // Make pause stick
                    v.muted = true;
                    v.autoplay = false;
                    v.loop = false;
                    v.removeAttribute("autoplay");

                    // Freeze frame to prevent auto-resume
                    v.currentTime = v.currentTime;

                    result.videos.push(info);
                } catch (e) {
                    result.videos.push({ index: idx, error: String(e) });
                }
            });
        } catch (e) {
            result.error = String(e);
        }

        return result;
        """
        result = self.driver.execute_script(JS_PAUSE_VIDEO)
        self.log.debug(result)



    # def only_scroll(
    #     self,
    #     container_selector,
    #     base_pause_ms: int = 400,
    #     idle_stop_seconds: int = 12,
    #     max_total_seconds: int = 60,
    #     scroll_steps: int = 25,
    # ):
    #     """
    #     Synchronous, Docker-safe scrolling.
    #     """

    #     container =  self.container_selector

    #     start_time = time.time()
    #     last_movement = time.time()
    #     step = 0


    #     SCROLL_JS = """
    #     var result = {
    #         ok: false,
    #         logs: [],
    #         debug: {}
    #     };

    #     try {
    #         var selector = arguments[0];
    #         result.debug.selector = selector;

    #         function resolveScrollOwner(el) {
    #             var cur = el;
    #             while (cur && cur !== document.body) {
    #                 var s = getComputedStyle(cur);
    #                 if (
    #                     /(auto|scroll)/.test(s.overflowY) &&
    #                     cur.scrollHeight > cur.clientHeight + 5
    #                 ) {
    #                     return cur;
    #                 }
    #                 cur = cur.parentElement;
    #             }
    #             return document.scrollingElement || document.documentElement;
    #         }

    #         var raw = null;
    #         try {
    #             raw = selector ? document.querySelector(selector) : null;
    #         } catch (e) {
    #             raw = null;
    #             result.logs.push("Invalid selector");
    #         }

    #         var container = raw
    #             ? resolveScrollOwner(raw)
    #             : (document.scrollingElement || document.documentElement);

    #         var page = document.scrollingElement || document.documentElement;

    #         var beforeTop = container.scrollTop;
    #         result.debug.beforeTop = beforeTop;

    #         /* -------------------------------
    #         HUMAN SCROLL BEHAVIOR MODEL
    #         -------------------------------- */

    #         var r = Math.random();
    #         var direction = 1;
    #         var magnitude;

    #         if (r < 0.20) {
    #             // slow reading drift down
    #             magnitude = container.clientHeight * (0.14 + Math.random() * 0.18);
    #         } else if (r < 0.80) {
    #             // medium skim down
    #             magnitude = container.clientHeight * (0.55 + Math.random() * 0.25);
    #         } else if (r < 0.92) {
    #             // reconsideration scroll up
    #             direction = -1;
    #             magnitude = container.clientHeight * (0.10 + Math.random() * 0.14);
    #         } else {
    #             // barely move (hesitation)
    #             magnitude = container.clientHeight * 0.03;
    #         }

    #         var delta = direction * magnitude;
    #         result.debug.delta = delta;

    #         // more, smaller segments
    #         var segments = Math.floor(4 + Math.random() * 2); // 6-12
    #         var stepDelta = delta / segments;

    #         for (var i = 0; i < segments; i++) {
    #             // tiny viewport nudge (signal only)
    #             // page.scrollTop += stepDelta > 0 ? 1 : -1;
    #             var pageBefore = page.scrollTop;

    #             // tiny viewport nudge (signal only)
    #             page.scrollTop += stepDelta > 0 ? 1 : -1;

    #             // clamp page scroll so we don't drift out of comment viewport
    #             if (page.scrollTop > 100) {
    #                 page.scrollTop = 50;
    #             }
    #             if (page.scrollTop < 0) {
    #                 page.scrollTop = 0;
    #             }


    #             // actual contained scroll
    #             container.scrollTop += stepDelta;

    #             // force layout / observers
    #             container.getBoundingClientRect();

    #             // variable micro pause (human thumb rhythm)
    #             var wait =
    #                 Math.random() < 0.65
    #                     ? 35 + Math.random() * 70    // quick glance
    #                     : 110 + Math.random() * 160; // eye catch

    #             var t0 = performance.now();
    #             while (performance.now() - t0 < wait) {}
    #         }

    #         // occasional re-read hesitation
    #         if (Math.random() < 0.22) {
    #             var pause =
    #                 400 + Math.random() * 700; // 0.4–1.1s

    #             var t1 = performance.now();
    #             while (performance.now() - t1 < pause) {}
    #         }

    #         // tiny corrective adjustment (very human)
    #         if (Math.random() < 0.15) {
    #             var adjust =
    #                 container.clientHeight *
    #                 (Math.random() < 0.5 ? -0.04 : 0.04);
    #             container.scrollTop += adjust;
    #             container.getBoundingClientRect();
    #         }

    #         result.debug.afterTop = container.scrollTop;
    #         result.debug.pageScrollTop = page.scrollTop;

    #         result.moved =
    #             container.scrollTop !== beforeTop ||
    #             page.scrollTop !== beforeTop;

    #         result.ok = true;

    #     } catch (e) {
    #         result.error = String(e);
    #     }

    #     return result;
    #     """


    #     logs = []

    #     try:
    #         while step < scroll_steps:
    #             step += 1

    #             if time.time() - start_time > max_total_seconds:
    #                 logs.append("⏰ Max total time reached")
    #                 break

    #             result = self.driver.execute_script(
    #                 SCROLL_JS,
    #                 container
    #             )

    #             if not result or not result.get("ok"):
    #                 logs.append("❌ Container not found or scroll failed")
    #                 break

    #             if result["moved"]:
    #                 last_movement = time.time()
    #                 logs.append(f"🟢 Step {step}: scrolled")
    #             else:
    #                 logs.append(f"🟡 Step {step}: no movement")

    #             if time.time() - last_movement > idle_stop_seconds:
    #                 logs.append("🟡 Idle timeout reached")
    #                 break
                
    #             # self.pauseVideo()
    #             pause = base_pause_ms / 1000 * random.uniform(0.7, 1.6)
    #             time.sleep(pause)

    #             if random.random() < 0.15:
    #                 time.sleep(base_pause_ms / 1000 * random.uniform(3, 6))

    #     except Exception as e:
    #         self.log.exception("Scroll-only failed")
    #         return {"status": "error", "reason": str(e)}

    #     for line in logs:
    #         self.log.debug(f"[ScrollOnly] {line}")

    #     return {
    #         "status": "done",
    #         "steps": step,
    #         "timestamp": datetime.now(timezone.utc).isoformat()
    #     }


    def only_scroll(self, container_selector, scroll_steps=25, max_runtime=60):
        """
        Human-like, IG-native comment scrolling using keyboard navigation.
        - Safe offset click (never clicks buttons/links)
        - Keyboard-driven (PAGE_DOWN / SPACE / ARROW_DOWN)
        - Page scroll clamp (never drift out of modal)
        - Focus recovery
        - Idle / no-progress exit
        """

        driver = self.driver
        actions = ActionChains(driver)
        UP_CORRECTION_PROB = 0.15

        # -------------------------------
        # Helpers
        # -------------------------------

        def safe_focus_container(container_el):
            """
            Click a guaranteed-safe offset inside the container
            (top-left padding area, no interactive elements).
            """
            rect = container_el.rect
            x = rect["x"] + 2
            y = rect["y"] + 2

            from selenium.webdriver.common.actions.pointer_input import PointerInput
            from selenium.webdriver.common.actions.action_builder import ActionBuilder

            mouse = PointerInput("mouse", "mouse")
            ab = ActionBuilder(driver, mouse=mouse)
            ab.pointer_action.move_to_location(x, y)
            ab.pointer_action.click()
            ab.perform()

        def clamp_page_scroll(max_allowed=50):
            """
            Prevent page drift while allowing tiny movement to wake observers.
            """
            return driver.execute_script("""
                const page = document.scrollingElement || document.documentElement;
                if (page.scrollTop > arguments[0]) {
                    page.scrollTop = 0;
                    return true;
                }
                return false;
            """, max_allowed)

        # -------------------------------
        # Initial setup
        # -------------------------------

        container_el = driver.find_element(By.CSS_SELECTOR, container_selector)

        safe_focus_container(container_el)
        time.sleep(random.uniform(0.3, 0.6))

        start_time = time.time()
        last_progress = time.time()
        step = 0

        KEY_CHOICES = [Keys.SPACE, Keys.ARROW_DOWN]
        KEY_WEIGHTS = [0.1, 0.9]

        # -------------------------------
        # Main loop
        # -------------------------------

        while step < scroll_steps:
            step += 1
            self.log.debug(f"Step {step} of {scroll_steps}")
            # Hard runtime cap
            if time.time() - start_time > max_runtime:
                self.log.debug(f"Max runtime reached: {max_runtime} seconds")
                break

            # ---- Human burst ----
            burst = random.randint(1, 3)
            for _ in range(burst):
                key = random.choices(KEY_CHOICES, weights=KEY_WEIGHTS)[0]
                self.log.debug(f"Sending key: {key}")
                if key == Keys.SPACE:
                    step += 6
                actions.send_keys(key).perform()
                time.sleep(random.uniform(0.15, 0.35))

            # ---- Rare upward correction (human micro-adjustment) ----
            if random.random() < UP_CORRECTION_PROB:
                self.log.debug("Sending rare upward correction (ARROW_UP)")
                actions.send_keys(Keys.ARROW_UP).perform()
                time.sleep(random.uniform(0.08, 0.18))


            # ---- Reading pause ----
            if random.random() < 0.25:
                time.sleep(random.uniform(0.8, 2.0))

            # ---- Periodic refocus (focus *will* get stolen) ----
            if step % 2 == 0:
                try:
                    safe_focus_container(container_el)
                    time.sleep(random.uniform(0.2, 0.4))
                except Exception:
                    pass

            # ---- Pause videos (prevents key hijack) ----


            # ---- Clamp page drift ----
            try:
                if clamp_page_scroll(max_allowed=50):
                    time.sleep(random.uniform(0.05, 0.15))
            except Exception:
                pass

            # ---- Progress detection ----


        return {
            "status": "done",
            "steps": step,
            "duration": round(time.time() - start_time, 2),
        }

