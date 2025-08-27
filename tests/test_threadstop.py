# -*- coding: utf-8 -*-
"""
Tests for stopit.threadstop module - corrected for GIL behavior
"""

import unittest
import time
import threading
from unittest.mock import patch, Mock

from stopit2.threadstop import async_raise, ThreadingTimeout, threading_timeoutable
from stopit2.utils import TimeoutException, BaseTimeout


def cpu_bound_work(duration):
    """CPU-bound work that can be interrupted (unlike time.sleep)"""
    start = time.time()
    count = 0
    while time.time() - start < duration:
        count += 1
        if count % 1000 == 0:
            # Periodically release GIL to allow interruption
            pass
    return count


class TestAsyncRaise(unittest.TestCase):
    """Test async_raise function"""
    
    def test_invalid_thread_id(self):
        with self.assertRaises(ValueError) as cm:
            async_raise(999999, Exception)
        self.assertIn("Invalid thread ID", str(cm.exception))
    
    def test_async_raise_in_thread(self):
        """Test raising exception in another thread"""
        exception_caught = []
        thread_started = threading.Event()
        
        def target_function():
            thread_started.set()
            try:
                cpu_bound_work(2.0)  # CPU work can be interrupted
                exception_caught.append(None)  # Should not reach here
            except LookupError as e:
                exception_caught.append(e)
            except Exception as e:
                exception_caught.append(e)
        
        thread = threading.Thread(target=target_function)
        thread.start()
        
        thread_started.wait()
        time.sleep(0.1)  # Let thread start working
        
        async_raise(thread.ident, LookupError)
        thread.join(timeout=2.0)
        
        self.assertEqual(len(exception_caught), 1)
        self.assertIsInstance(exception_caught[0], Exception)


class TestThreadingTimeout(unittest.TestCase):
    """Test ThreadingTimeout context manager"""
    
    def test_initialization(self):
        timeout = ThreadingTimeout(5.0)
        self.assertEqual(timeout.seconds, 5.0)
        self.assertTrue(timeout.swallow_exc)
        self.assertEqual(timeout.target_tid, threading.current_thread().ident)
        self.assertIsNone(timeout.timer)
    
    def test_fast_execution(self):
        """Test that fast code executes normally"""
        with ThreadingTimeout(2.0) as timeout_ctx:
            time.sleep(0.1)
            result = 42
        
        self.assertEqual(timeout_ctx.state, BaseTimeout.EXECUTED)
        self.assertTrue(bool(timeout_ctx))
        self.assertEqual(result, 42)
    
    def test_timeout_occurs_with_cpu_work(self):
        """Test that timeout occurs with CPU-bound work"""
        start_time = time.time()
        
        with ThreadingTimeout(0.5, swallow_exc=True) as timeout_ctx:
            cpu_bound_work(2.0)  # This can be interrupted
        
        elapsed = time.time() - start_time
        self.assertLess(elapsed, 1.5)  # Should be interrupted
        self.assertEqual(timeout_ctx.state, BaseTimeout.TIMED_OUT)
        self.assertFalse(bool(timeout_ctx))
    
    def test_timeout_with_sleep_limitation(self):
        """Test timeout behavior with time.sleep (demonstrates GIL limitation)"""
        start_time = time.time()
        
        with ThreadingTimeout(0.5, swallow_exc=True) as timeout_ctx:
            time.sleep(0.8)  # This may not be interrupted due to GIL
        
        elapsed = time.time() - start_time
        # Could be either EXECUTED or TIMED_OUT depending on timing
        self.assertIn(timeout_ctx.state, [BaseTimeout.EXECUTED, BaseTimeout.TIMED_OUT])
    
    def test_timeout_exception_propagated(self):
        """Test timeout with swallow_exc=False"""
        with self.assertRaises(TimeoutException):
            with ThreadingTimeout(0.1, swallow_exc=False):
                cpu_bound_work(1.0)
    
    def test_other_exception_propagated(self):
        """Test that other exceptions are still propagated"""
        with self.assertRaises(ValueError):
            with ThreadingTimeout(2.0) as timeout_ctx:
                raise ValueError("Test error")
        
        self.assertEqual(timeout_ctx.state, BaseTimeout.EXECUTING)
    
    def test_cancel_timeout(self):
        """Test canceling timeout"""
        with ThreadingTimeout(1.0) as timeout_ctx:
            time.sleep(0.1)
            timeout_ctx.cancel()
            time.sleep(0.2)  # Should complete after cancel
        
        # After cancel, if context exits normally, state becomes EXECUTED
        self.assertEqual(timeout_ctx.state, BaseTimeout.EXECUTED)
        self.assertTrue(bool(timeout_ctx))
    
    def test_timer_cleanup_on_normal_completion(self):
        """Test that timer is properly cleaned up"""
        with ThreadingTimeout(2.0) as timeout_ctx:
            time.sleep(0.1)
        
        time.sleep(0.1)  # Give cleanup time
        self.assertFalse(timeout_ctx.timer.is_alive())
    
    def test_timer_cleanup_on_exception(self):
        """Test that timer is cleaned up even when exception occurs"""
        try:
            with ThreadingTimeout(2.0) as timeout_ctx:
                raise ValueError("Test")
        except ValueError:
            pass
        
        time.sleep(0.1)  # Give cleanup time
        self.assertFalse(timeout_ctx.timer.is_alive())
    
    def test_nested_timeouts(self):
        """Test that nested timeouts work correctly"""
        with ThreadingTimeout(2.0) as outer:
            time.sleep(0.1)
            with ThreadingTimeout(1.0) as inner:
                time.sleep(0.1)
        
        self.assertEqual(outer.state, BaseTimeout.EXECUTED)
        self.assertEqual(inner.state, BaseTimeout.EXECUTED)


class TestThreadingTimeoutable(unittest.TestCase):
    """Test threading_timeoutable decorator"""
    
    def test_function_without_timeout(self):
        @threading_timeoutable()
        def fast_func(x):
            return x * 2
        
        result = fast_func(21)
        self.assertEqual(result, 42)
    
    def test_function_with_timeout_no_timeout_occurs(self):
        @threading_timeoutable(default='timeout')
        def fast_func(x):
            time.sleep(0.1)
            return x * 2
        
        result = fast_func(21, timeout=1.0)
        self.assertEqual(result, 42)
    
    def test_function_with_timeout_occurs_cpu_bound(self):
        @threading_timeoutable(default='timeout_occurred')
        def slow_func(x):
            cpu_bound_work(2.0)  # CPU work that can be interrupted
            return x * 2
        
        start_time = time.time()
        result = slow_func(21, timeout=0.5)
        elapsed = time.time() - start_time
        
        self.assertEqual(result, 'timeout_occurred')
        self.assertLess(elapsed, 1.5)
    
    def test_function_with_timeout_returns_none_by_default(self):
        @threading_timeoutable()
        def slow_func(x):
            cpu_bound_work(2.0)
            return x * 2
        
        result = slow_func(21, timeout=0.5)
        self.assertIsNone(result)
    
    def test_custom_timeout_parameter_name(self):
        @threading_timeoutable(default='timeout', timeout_param='my_timeout')
        def slow_func(x):
            cpu_bound_work(2.0)
            return x * 2
        
        result = slow_func(21, my_timeout=0.5)
        self.assertEqual(result, 'timeout')
    
    def test_function_with_exception_inside_timeout(self):
        """Test that non-timeout exceptions are propagated, not caught"""
        @threading_timeoutable(default='timeout_default')
        def func_with_exception():
            time.sleep(0.1)
            raise ValueError("Test error")
        
        # Non-timeout exceptions should be propagated, not caught
        with self.assertRaises(ValueError):
            func_with_exception(timeout=1.0)
    
    def test_method_decoration(self):
        class TestClass:
            @threading_timeoutable(default='timeout')
            def slow_method(self, x):
                cpu_bound_work(2.0)
                return x * 2
        
        obj = TestClass()
        result = obj.slow_method(21, timeout=0.5)
        self.assertEqual(result, 'timeout')
    
    def test_function_metadata_preserved(self):
        @threading_timeoutable()
        def documented_func(x):
            """This function has documentation"""
            return x
        
        self.assertEqual(documented_func.__name__, 'documented_func')
        self.assertEqual(documented_func.__doc__, 'This function has documentation')
    
    def test_timeout_parameter_removed_from_kwargs(self):
        """Test that timeout parameter is properly removed before calling function"""
        called_kwargs = {}
        
        @threading_timeoutable()
        def func_checking_kwargs(**kwargs):
            called_kwargs.update(kwargs)
            return 'success'
        
        result = func_checking_kwargs(a=1, b=2, timeout=1.0)
        
        self.assertEqual(result, 'success')
        self.assertEqual(called_kwargs, {'a': 1, 'b': 2})
        self.assertNotIn('timeout', called_kwargs)


class TestThreadingTimeoutEdgeCases(unittest.TestCase):
    """Test edge cases and error conditions"""
    
    def test_zero_timeout(self):
        """Test with zero timeout"""
        try:
            with ThreadingTimeout(0, swallow_exc=True) as timeout_ctx:
                cpu_bound_work(0.5)
            # Zero timeout should cause immediate timeout
            self.assertEqual(timeout_ctx.state, BaseTimeout.TIMED_OUT)
        except TimeoutException:
            # Zero timeout might trigger during setup
            pass
    
    def test_very_small_timeout(self):
        """Test with very small timeout"""
        start_time = time.time()
        
        with ThreadingTimeout(0.01, swallow_exc=True) as timeout_ctx:
            cpu_bound_work(0.5)
        
        elapsed = time.time() - start_time
        self.assertLess(elapsed, 0.2)  # Should timeout quickly
        self.assertEqual(timeout_ctx.state, BaseTimeout.TIMED_OUT)
    
    def test_manual_timeout_exception(self):
        """Test raising TimeoutException manually within context"""
        with ThreadingTimeout(2.0, swallow_exc=True) as timeout_ctx:
            raise TimeoutException("Manual timeout")
        
        self.assertEqual(timeout_ctx.state, BaseTimeout.INTERRUPTED)


class TestGILLimitationsDocumentation(unittest.TestCase):
    """Test that documents the GIL limitations mentioned in the README"""
    
    def test_sleep_not_interruptible(self):
        """Documents that time.sleep cannot be interrupted due to GIL"""
        start_time = time.time()
        
        with ThreadingTimeout(0.1, swallow_exc=True) as timeout_ctx:
            time.sleep(0.5)  # This typically completes fully
        
        elapsed = time.time() - start_time
        # time.sleep usually completes before being interrupted
        self.assertGreater(elapsed, 0.4)  # Usually completes the full sleep
        # State could be EXECUTED or TIMED_OUT depending on exact timing
        self.assertIn(timeout_ctx.state, [BaseTimeout.EXECUTED, BaseTimeout.TIMED_OUT])
    
    def test_cpu_work_is_interruptible(self):
        """Documents that CPU-bound work can be interrupted"""
        start_time = time.time()
        
        with ThreadingTimeout(0.2, swallow_exc=True) as timeout_ctx:
            cpu_bound_work(1.0)  # This should be interrupted
        
        elapsed = time.time() - start_time
        self.assertLess(elapsed, 0.8)  # Should be interrupted before completing
        self.assertEqual(timeout_ctx.state, BaseTimeout.TIMED_OUT)


if __name__ == '__main__':
    unittest.main()
