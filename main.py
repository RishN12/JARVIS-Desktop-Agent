import argparse
import sys
import time

def run_diagnostics():
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print("=" * 55)
    print("[*] RUNNING DESKTOP AGENT DIAGNOSTICS")
    print("=" * 55)

    # 1. Test Ollama connectivity
    print("\n[1/5] Checking Ollama Connection...")
    try:
        import httpx
        from core.config import config
        r = httpx.get(f"{config.ollama_base_url}/api/tags", timeout=5.0)
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            print(f"  [OK] Connected to Ollama! Available models: {', '.join(models)}")
        else:
            print(f"  [FAIL] Ollama returned status {r.status_code}")
    except Exception as e:
        print(f"  [FAIL] Failed to connect to Ollama: {e}")

    # 2. Test Screen capture
    print("\n[2/5] Testing Screen Capture & Multi-Monitor Attachment...")
    try:
        from core.screen import ScreenManager
        sm = ScreenManager()
        bounds = sm.get_virtual_screen_bounds()
        print(f"  Desktop bounds: {bounds}")
        img = sm.capture_screen()
        print(f"  [OK] Screen captured successfully! Resolution: {img.size}")
    except Exception as e:
        print(f"  [FAIL] Screen capture failed: {e}")
        img = None

    # 3. Test PyAutoGUI & Mouse tracking
    print("\n[3/5] Testing Mouse Tracking & Failsafe...")
    try:
        import pyautogui
        pos = pyautogui.position()
        print(f"  Current mouse position: ({pos.x}, {pos.y})")
        print("  [OK] Mouse and PyAutoGUI active.")
    except Exception as e:
        print(f"  [FAIL] Mouse tracking failed: {e}")

    # 4. Test Screen Vision
    print("\n[4/5] Testing Screen Vision (Ollama)...")
    try:
        if img is None:
            raise RuntimeError("Screen capture was unavailable.")
        from core.vision import ScreenVision
        from core.config import config
        vision = ScreenVision(model_name=config.vision_model)
        t0 = time.time()
        description = vision.describe(img)
        elapsed = time.time() - t0
        if description.startswith("Vision unavailable:"):
            print(f"  [FAIL] Vision request failed after {elapsed:.2f}s: {description}")
        else:
            print(f"  [OK] Vision responded in {elapsed:.2f}s:")
            print(f"     {description[:700]}")
    except Exception as e:
        print(f"  [FAIL] Screen vision test failed: {e}")

    # 5. Test Brain JSON planning
    print("\n[5/5] Testing Local Brain (Ollama) Action Planning...")
    try:
        from core.brain import AgentBrain
        brain = AgentBrain(model_name="qwen2.5:3b")
        t0 = time.time()
        res = brain.decide_next_action(
            goal="Open calculator",
            history=[],
            screen_summary="Desktop clean.",
        )
        print(f"  [OK] Brain responded in {time.time()-t0:.2f}s:")
        print(f"     Thought: {res.get('thought')}")
        print(f"     Action:  {res.get('action')}")
        print(f"     Params:  {res.get('params')}")
    except Exception as e:
        print(f"  [FAIL] Brain decision failed: {e}")

    print("\n" + "=" * 55)
    print("[SUCCESS] ALL DIAGNOSTICS COMPLETED!")
    print("=" * 55)


def main():
    parser = argparse.ArgumentParser(description="Autonomous Windows Desktop Agent")
    parser.add_argument("--test", action="store_true", help="Run system diagnostics and verify components")
    parser.add_argument("--cli", action="store_true", help="Run in headless command-line mode without GUI")
    parser.add_argument("--goal", type=str, help="Goal to execute in CLI mode")
    parser.add_argument("--model", type=str, default="qwen2.5:3b", help="Ollama model to use")

    args = parser.parse_args()

    if args.test:
        run_diagnostics()
        return

    if args.cli:
        if not args.goal:
            print("Error: --goal is required when running in --cli mode.")
            sys.exit(1)
        from core.agent import DesktopAgent
        agent = DesktopAgent()
        print(f"Starting goal in CLI mode: '{args.goal}' using model {args.model}")
        agent.start_task(args.goal, model_name=args.model)
        try:
            while agent._worker_thread and agent._worker_thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nAborting via KeyboardInterrupt...")
            agent.stop()
        return

    # Default: launch CustomTkinter GUI
    from gui.app import run_gui
    run_gui()


if __name__ == "__main__":
    main()
