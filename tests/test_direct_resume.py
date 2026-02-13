import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
from src.agent_manager import AgentManager
from langgraph.types import Command


async def test_direct_resume():
    print("=" * 50)
    print("Direct AgentManager.stream_resume_interrupt Test")
    print("=" * 50)

    am = AgentManager()
    await am.init()

    # 使用现有的 thread_id
    thread_id = "test-user-2a3af261-8aa1-4435-94dd-7d701352582f"
    action = "continue"

    print(f"\nTesting resume for thread_id: {thread_id}")
    print(f"Action: {action}")

    print("\n--- Starting stream_resume_interrupt ---")
    event_count = 0
    try:
        async for chunk in am.stream_resume_interrupt(thread_id, action):
            print(f"[CHUNK] {chunk[:200]}..." if len(chunk) > 200 else f"[CHUNK] {chunk}")
            event_count += 1
    except Exception as e:
        import traceback
        print(f"[ERROR] {type(e).__name__}: {e}")
        traceback.print_exc()

    print(f"\n--- Resume complete ---")
    print(f"Total events: {event_count}")


if __name__ == "__main__":
    from asyncio import WindowsSelectorEventLoopPolicy
    import asyncio
    asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())
    asyncio.run(test_direct_resume())
