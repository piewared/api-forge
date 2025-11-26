"""Unit tests for the async context manager system."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from src.app.runtime.config.config_data import ConfigData
from src.app.runtime.context import (
    AppContext,
    get_config,
    get_context,
    set_context,
    with_context,
)


class TestContextManager:
    """Test the context manager functionality."""

    def test_default_context_available(self):
        """Should have a default context available."""
        context = get_context()
        config = get_config()

        assert isinstance(context, AppContext)
        assert isinstance(config, ConfigData)
        assert context.config is config

    def test_with_context_override_single_level(self):
        """Should override config for the duration of the context manager."""
        original_config = get_config()
        original_host = original_config.app.host

        # Create test config with different value
        test_config = ConfigData()
        test_config.app.host = "custom_host"

        with with_context(test_config):
            override_config = get_config()
            assert override_config.app.host == "custom_host"
            assert override_config is not original_config

        # Should revert after context
        after_config = get_config()
        assert after_config.app.host == original_host
        assert after_config is original_config

    def test_with_context_nested_overrides(self):
        """Should handle nested context overrides correctly."""
        original_config = get_config()
        original_host = original_config.app.host

        # First level override
        level1_config = ConfigData()
        level1_config.app.host = "level1_host"
        level1_config.app.port = 8001

        with with_context(level1_config):
            level1_context = get_config()
            assert level1_context.app.host == "level1_host"
            assert level1_context.app.port == 8001

            # Second level override
            level2_config = ConfigData()
            level2_config.app.host = "level2_host"
            level2_config.app.port = 8002
            level2_config.logging.level = "DEBUG"

            with with_context(level2_config):
                level2_context = get_config()
                assert level2_context.app.host == "level2_host"
                assert level2_context.app.port == 8002
                assert level2_context.logging.level == "DEBUG"

                # Third level override
                level3_config = ConfigData()
                level3_config.app.host = "level3_host"
                level3_config.database.url = "sqlite:///level3.db"

                with with_context(level3_config):
                    level3_context = get_config()
                    assert level3_context.app.host == "level3_host"
                    assert level3_context.database.url == "sqlite:///level3.db"

                # Back to level 2
                back_to_level2 = get_config()
                assert back_to_level2.app.host == "level2_host"
                assert back_to_level2.app.port == 8002
                assert back_to_level2.logging.level == "DEBUG"

            # Back to level 1
            back_to_level1 = get_config()
            assert back_to_level1.app.host == "level1_host"
            assert back_to_level1.app.port == 8001

        # Back to original
        final_config = get_config()
        assert final_config.app.host == original_host
        assert final_config is original_config

    def test_with_context_no_override(self):
        """Should work without any override (current context)."""
        original_config = get_config()

        with with_context():
            context_config = get_config()
            assert context_config is original_config

        after_config = get_config()
        assert after_config is original_config

    def test_context_isolation_in_nested_calls(self):
        def inner_function() -> str:
            """Function that reads config in different context."""
            return get_config().app.host

        def middle_function() -> tuple[str, int]:
            """Function that creates its own context and calls inner."""
            middle_config = ConfigData()
            middle_config.app.host = "middle_host"

            with with_context(middle_config):
                return inner_function(), get_config().app.port

        # Set up outer context
        outer_config = ConfigData()
        outer_config.app.host = "outer_host"
        outer_config.app.port = 8001

        with with_context(outer_config):
            # Call middle function which creates its own context
            middle_host, middle_port = middle_function()

            # Middle function should see its own host but inherit port
            # (inheritance means child inherits parent's non-overridden values)
            assert middle_host == "middle_host"
            assert middle_port == 8001  # Inherited from outer context

            # After middle function, should be back to outer context
            assert get_config().app.host == "outer_host"
            assert get_config().app.port == 8001

    def test_exception_handling_in_context(self):
        """Should properly restore context even when exceptions occur."""
        original_config = get_config()
        original_host = original_config.app.host

        test_config = ConfigData()
        test_config.app.host = "exception_test_host"

        try:
            with with_context(test_config):
                assert get_config().app.host == "exception_test_host"
                raise ValueError("Test exception")
        except ValueError:
            pass  # Expected

        # Should restore original context even after exception
        after_config = get_config()
        assert after_config.app.host == original_host
        assert after_config is original_config

    def test_context_manager_with_different_config_properties(self):
        """Should handle overriding different configuration properties."""
        original_config = get_config()

        test_config = ConfigData()
        test_config.app.host = "test_host"
        test_config.app.port = 9000
        test_config.logging.level = "DEBUG"
        test_config.database.url = "sqlite:///test.db"
        test_config.redis.url = "redis://test:6379"
        test_config.temporal.url = "test-temporal:7233"

        with with_context(test_config):
            override_config = get_config()

            assert override_config.app.host == "test_host"
            assert override_config.app.port == 9000
            assert override_config.logging.level == "DEBUG"
            assert override_config.database.url == "sqlite:///test.db"
            assert override_config.redis.url == "redis://test:6379"
            assert override_config.temporal.url == "test-temporal:7233"

        # All should revert
        after_config = get_config()
        assert after_config is original_config


class TestAsyncContextManager:
    """Test context manager behavior in async contexts."""

    @pytest.mark.asyncio
    async def test_async_context_isolation(self):
        """Should maintain context isolation in async functions."""
        original_config = get_config()

        async def async_worker(worker_id: str) -> str:
            """Async worker that creates its own context."""
            worker_config = ConfigData()
            worker_config.app.host = f"worker_{worker_id}_host"

            with with_context(worker_config):
                # Simulate some async work
                await asyncio.sleep(0.01)
                return get_config().app.host

        # Run multiple async workers concurrently
        tasks = [async_worker(str(i)) for i in range(5)]
        results = await asyncio.gather(*tasks)

        # Each worker should see its own context
        expected = [f"worker_{i}_host" for i in range(5)]
        assert results == expected

        # Original context should be unchanged
        assert get_config() is original_config

    @pytest.mark.asyncio
    async def test_async_nested_contexts(self):
        """Should handle nested contexts in async functions."""
        original_config = get_config()

        async def level2_async() -> tuple[str, str]:
            """Second level async function with its own context."""
            level2_config = ConfigData()
            level2_config.app.host = "level2_async_host"

            with with_context(level2_config):
                await asyncio.sleep(0.01)
                return get_config().app.host, str(get_config().app.port)

        # Level 1 context
        level1_config = ConfigData()
        level1_config.app.host = "level1_async_host"
        level1_config.app.port = 8001

        with with_context(level1_config):
            # Should see level 1 context
            assert get_config().app.host == "level1_async_host"
            assert get_config().app.port == 8001

            # Call level 2 async function
            host, port = await level2_async()

            # Level 2 should see its own host but inherit port
            # (inheritance means child inherits parent's non-overridden values)
            assert host == "level2_async_host"
            assert port == "8001"  # Inherited from level 1 context

            # Back to level 1 after async call
            assert get_config().app.host == "level1_async_host"
            assert get_config().app.port == 8001

        # Back to original
        assert get_config() is original_config

    @pytest.mark.asyncio
    async def test_async_context_with_concurrent_tasks(self):
        """Should maintain context isolation with concurrent async tasks."""
        results = {}

        async def async_task(task_id: int) -> None:
            """Async task that works in its own context."""
            task_config = ConfigData()
            task_config.app.host = f"task_{task_id}_host"
            # Cycle through different ports
            task_config.app.port = 8000 + task_id

            with with_context(task_config):
                # Simulate varying amounts of async work
                await asyncio.sleep(0.01 * task_id)

                # Store results from this task's context
                results[task_id] = {
                    "host": get_config().app.host,
                    "port": get_config().app.port,
                }

        # Start multiple concurrent tasks
        tasks = [async_task(i) for i in range(1, 6)]
        await asyncio.gather(*tasks)

        # Each task should have seen its own context
        for i in range(1, 6):
            assert results[i]["host"] == f"task_{i}_host"
            expected_port = 8000 + i
            assert results[i]["port"] == expected_port


class TestThreadSafety:
    """Test context manager behavior across threads."""

    def test_thread_isolation(self):
        """Should maintain context isolation across threads."""
        original_config = get_config()
        results = {}

        def thread_worker(worker_id: int) -> None:
            """Worker function that runs in its own thread."""
            worker_config = ConfigData()
            worker_config.app.host = f"thread_{worker_id}_host"
            # Cycle through different ports
            worker_config.app.port = 8000 + worker_id

            with with_context(worker_config):
                # Simulate some work
                import time

                time.sleep(0.01)

                # Store results from this thread's context
                results[worker_id] = {
                    "host": get_config().app.host,
                    "port": get_config().app.port,
                }

        # Run workers in separate threads
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(thread_worker, i) for i in range(1, 6)]

            # Wait for all threads to complete
            for future in futures:
                future.result()

        # Each thread should have seen its own context
        for i in range(1, 6):
            assert results[i]["host"] == f"thread_{i}_host"
            assert results[i]["port"] == 8000 + i

        # Main thread context should be unchanged
        assert get_config() is original_config

    def test_mixed_async_and_thread_contexts(self):
        """Should handle mixed async and thread contexts correctly."""
        import threading
        import time

        results = []

        def thread_function():
            """Function that runs in a separate thread."""
            thread_config = ConfigData()
            thread_config.app.host = "thread_host"

            with with_context(thread_config):
                time.sleep(0.02)  # Simulate work
                results.append(("thread", get_config().app.host))

        # Start thread context
        main_config = ConfigData()
        main_config.app.host = "main_host"

        with with_context(main_config):
            # Record main thread context
            results.append(("main_before", get_config().app.host))

            # Start separate thread
            thread = threading.Thread(target=thread_function)
            thread.start()

            # Record main thread context while thread is running
            results.append(("main_during", get_config().app.host))

            # Wait for thread to complete
            thread.join()

            # Record main thread context after thread completes
            results.append(("main_after", get_config().app.host))

        # Verify results
        expected = [
            ("main_before", "main_host"),
            ("main_during", "main_host"),
            ("thread", "thread_host"),
            ("main_after", "main_host"),
        ]

        # Sort by context name for consistent comparison
        results.sort()
        expected.sort()
        assert results == expected


class TestContextManagerEdgeCases:
    """Test edge cases and error conditions."""

    def test_rapid_context_switching(self):
        """Should handle rapid context switching correctly."""
        original_config = get_config()

        configs = []
        for i in range(100):
            config = ConfigData()
            config.app.host = f"rapid_{i}"
            configs.append(config)

        # Rapidly switch contexts
        for i, config in enumerate(configs):
            with with_context(config):
                assert get_config().app.host == f"rapid_{i}"

        # Should be back to original
        assert get_config() is original_config

    def test_deeply_nested_contexts(self):
        """Should handle deeply nested contexts without stack overflow."""
        original_config = get_config()
        depth = 50  # Deep nesting

        def create_nested_context(level: int) -> str:
            """Recursively create nested contexts."""
            if level == 0:
                return get_config().app.host

            config = ConfigData()
            config.app.host = f"deep_{level}"

            with with_context(config):
                return create_nested_context(level - 1)

        result = create_nested_context(depth)
        assert result == "deep_1"  # Deepest level

        # Should be back to original
        assert get_config() is original_config

    def test_context_manager_reentrance(self):
        """Should handle reentrant context manager calls."""
        original_config = get_config()

        test_config = ConfigData()
        test_config.app.host = "reentrant_host"

        with with_context(test_config):
            assert get_config().app.host == "reentrant_host"

            # Reentrant call with same config
            with with_context(test_config):
                assert get_config().app.host == "reentrant_host"

                # Another level
                with with_context(test_config):
                    assert get_config().app.host == "reentrant_host"

        # Should be back to original
        assert get_config() is original_config

    def test_context_inheritance_partial_override(self):
        """Should properly inherit non-overridden properties from parent context."""

        # Parent context sets multiple properties
        parent_config = ConfigData()
        parent_config.app.host = "parent_host"
        parent_config.app.port = 8001
        parent_config.logging.level = "DEBUG"
        parent_config.database.url = "sqlite:///parent.db"

        with with_context(parent_config):
            # Child context only overrides some properties
            child_config = ConfigData()
            child_config.app.host = "child_host"  # Override
            # Don't set port, logging.level, database.url - should inherit

            with with_context(child_config):
                child_context = get_config()

                # Should see overridden property
                assert child_context.app.host == "child_host"

                # Should inherit parent's non-overridden properties
                # Note: This tests proper inheritance behavior where child contexts
                # inherit non-overridden values from their parent context
                assert child_context.app.port == 8001  # Inherited from parent
                assert child_context.logging.level == "DEBUG"  # Inherited from parent

            # Back to parent context
            parent_context = get_config()
            assert parent_context.app.host == "parent_host"
            assert parent_context.app.port == 8001
            assert parent_context.logging.level == "DEBUG"
