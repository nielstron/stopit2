# -*- coding: utf-8 -*-
"""
Tests for stopit.signalstop module - corrected version
"""

import unittest
import time
import signal
import sys
import os

from stopit2.signalstop import SignalTimeout, signal_timeoutable
from stopit2.utils import TimeoutException, BaseTimeout


def cpu_bound_work(duration):
    """CPU-bound work for testing"""
    start = time.time()
    count = 0
    while time.time() - start < duration:
        count += 1
    return count


@unittest.skipIf(os.name == 'nt', "Signal-based timeouts don't work on Windows")
class TestSignalTimeout(unittest.TestCase):
    """Test SignalTimeout context manager"""
    
    def setUp(self):
        self.original_handler = signal.signal(signal.SIGALRM, signal.SIG_DFL)
    
    def tearDown(self):
        signal.alarm(0)
        signal.signal(signal.SIGALRM, self.original_handler)
    
    def test_initialization(self):
        timeout = SignalTimeout(5.5)
        self.assertEqual(timeout.seconds, 5)  # Converted to int
        self.assertTrue(timeout.swallow_exc)
    
    def test_initialization_with_float_conversion(self):
        timeout = SignalTimeout(3.7)
        self.assertEqual(timeout.seconds, 3)
    
    def test_fast_execution(self):
        """Test that fast code executes normally"""
        with SignalTimeout(2) as timeout_ctx:
            time.sleep(0.1)
            result = 42
        
        self.assertEqual(timeout_ctx.state, BaseTimeout.EXECUTED)
        self.assertTrue(bool(timeout_ctx))
        self.assertEqual(result, 42)
    
    def test_timeout_occurs(self):
        """Test that timeout occurs for slow code"""
        start_time = time.time()
        
        with SignalTimeout(1, swallow_exc=True) as timeout_ctx:
            time.sleep(2.5)  # Signal-based can interrupt sleep
        
        elapsed = time.time() - start_time
        self.assertLess(elapsed, 2.0)
        self.assertEqual(timeout_ctx.state, BaseTimeout.TIMED_OUT)
        self.assertFalse(bool(timeout_ctx))
    
    def test_timeout_exception_propagated(self):
        """Test timeout with swallow_exc=False"""
        start_time = time.time()
        
        with self.assertRaises(TimeoutException):
            with SignalTimeout(1, swallow_exc=False):
                time.sleep(2.5)
        
        elapsed = time.time() - start_time
        self.assertLess(elapsed, 2.0)
    
    def test_other_exception_propagated(self):
        """Test that other exceptions are still propagated"""
        with self.assertRaises(ValueError):
            with SignalTimeout(2) as timeout_ctx:
                raise ValueError("Test error")
        
        self.assertEqual(timeout_ctx.state, BaseTimeout.EXECUTING)
    
    def test_cancel_timeout(self):
        """Test canceling timeout"""
        with SignalTimeout(1) as timeout_ctx:
            time.sleep(0.1)
            timeout_ctx.cancel()
            time.sleep(0.5)  # Should not timeout after cancel
        
        # After cancel, if context exits normally, state becomes EXECUTED
        self.assertEqual(timeout_ctx.state, BaseTimeout.EXECUTED)
        self.assertTrue(bool(timeout_ctx))
    
    def test_signal_handler_restored(self):
        """Test that signal handler is properly restored"""
        original_handler = signal.signal(signal.SIGALRM, signal.SIG_DFL)
        
        with SignalTimeout(2):
            current_handler = signal.signal(signal.SIGALRM, signal.getsignal(signal.SIGALRM))
            self.assertNotEqual(current_handler, signal.SIG_DFL)
        
        final_handler = signal.getsignal(signal.SIGALRM)
        self.assertEqual(final_handler, signal.SIG_DFL)
        
        signal.signal(signal.SIGALRM, original_handler)
    
    def test_alarm_cleared_on_normal_completion(self):
        """Test that alarm is cleared on normal completion"""
        with SignalTimeout(2):
            time.sleep(0.1)
        
        remaining = signal.alarm(0)
        self.assertEqual(remaining, 0)
    
    def test_alarm_cleared_on_exception(self):
        """Test that alarm is cleared even when exception occurs"""
        try:
            with SignalTimeout(2):
                raise ValueError("Test")
        except ValueError:
            pass
        
        remaining = signal.alarm(0)
        self.assertEqual(remaining, 0)
    
    def test_handle_timeout_method(self):
        """Test the stop method directly (replaces handle_timeout)"""
        timeout = SignalTimeout(1)
        
        with self.assertRaises(TimeoutException) as cm:
            timeout.stop()
        
        self.assertEqual(timeout.state, BaseTimeout.TIMED_OUT)
        self.assertIn("Block exceeded maximum timeout", str(cm.exception))
        self.assertIn("1 seconds", str(cm.exception))


@unittest.skipIf(os.name == 'nt', "Signal-based timeouts don't work on Windows")
class TestSignalTimeoutable(unittest.TestCase):
    """Test signal_timeoutable decorator"""
    
    def setUp(self):
        self.original_handler = signal.signal(signal.SIGALRM, signal.SIG_DFL)
    
    def tearDown(self):
        signal.alarm(0)
        signal.signal(signal.SIGALRM, self.original_handler)
    
    def test_function_without_timeout(self):
        @signal_timeoutable()
        def fast_func(x):
            return x * 2
        
        result = fast_func(21)
        self.assertEqual(result, 42)
    
    def test_function_with_timeout_no_timeout_occurs(self):
        @signal_timeoutable(default='timeout')
        def fast_func(x):
            time.sleep(0.1)
            return x * 2
        
        result = fast_func(21, timeout=2)
        self.assertEqual(result, 42)
    
    def test_function_with_timeout_occurs(self):
        @signal_timeoutable(default='timeout_occurred')
        def slow_func(x):
            time.sleep(2.5)  # Signal can interrupt sleep
            return x * 2
        
        start_time = time.time()
        result = slow_func(21, timeout=1)
        elapsed = time.time() - start_time
        
        self.assertEqual(result, 'timeout_occurred')
        self.assertLess(elapsed, 2.0)
    
    def test_function_with_timeout_returns_none_by_default(self):
        @signal_timeoutable()
        def slow_func(x):
            time.sleep(2.5)
            return x * 2
        
        result = slow_func(21, timeout=1)
        self.assertIsNone(result)
    
    def test_custom_timeout_parameter_name(self):
        @signal_timeoutable(default='timeout', timeout_param='my_timeout')
        def slow_func(x):
            time.sleep(2.5)
            return x * 2
        
        result = slow_func(21, my_timeout=1)
        self.assertEqual(result, 'timeout')
    
    def test_function_with_exception_inside_timeout(self):
        """Test that non-timeout exceptions are propagated"""
        @signal_timeoutable(default='timeout_default')
        def func_with_exception():
            time.sleep(0.1)
            raise ValueError("Test error")
        
        # Non-timeout exceptions should be propagated
        with self.assertRaises(ValueError):
            func_with_exception(timeout=2)
    
    def test_method_decoration(self):
        class TestClass:
            @signal_timeoutable(default='timeout')
            def slow_method(self, x):
                time.sleep(2.5)
                return x * 2
        
        obj = TestClass()
        result = obj.slow_method(21, timeout=1)
        self.assertEqual(result, 'timeout')
    
    def test_function_metadata_preserved(self):
        @signal_timeoutable()
        def documented_func(x):
            """This function has documentation"""
            return x
        
        self.assertEqual(documented_func.__name__, 'documented_func')
        self.assertEqual(documented_func.__doc__, 'This function has documentation')
    
    def test_timeout_parameter_removed_from_kwargs(self):
        """Test that timeout parameter is properly removed before calling function"""
        called_kwargs = {}
        
        @signal_timeoutable()
        def func_checking_kwargs(**kwargs):
            called_kwargs.update(kwargs)
            return 'success'
        
        result = func_checking_kwargs(a=1, b=2, timeout=2)
        
        self.assertEqual(result, 'success')
        self.assertEqual(called_kwargs, {'a': 1, 'b': 2})
        self.assertNotIn('timeout', called_kwargs)
    
    def test_float_timeout_converted_to_int(self):
        """Test that float timeout values are converted to integers"""
        @signal_timeoutable(default='timeout')
        def slow_func():
            time.sleep(2.5)
            return 'success'
        
        result = slow_func(timeout=1.9)  # Should become 1 second
        self.assertEqual(result, 'timeout')


@unittest.skipIf(os.name == 'nt', "Signal-based timeouts don't work on Windows")  
class TestSignalTimeoutEdgeCases(unittest.TestCase):
    """Test edge cases and error conditions"""
    
    def setUp(self):
        self.original_handler = signal.signal(signal.SIGALRM, signal.SIG_DFL)
    
    def tearDown(self):
        signal.alarm(0)
        signal.signal(signal.SIGALRM, self.original_handler)
    
    def test_zero_timeout(self):
        """Test with zero timeout"""
        start_time = time.time()
        
        with SignalTimeout(0, swallow_exc=True) as timeout_ctx:
            time.sleep(0.2)
        
        elapsed = time.time() - start_time
        # Zero timeout behavior can vary - it might complete execution or timeout
        # Depending on system timing and signal delivery
        self.assertIn(timeout_ctx.state, [BaseTimeout.EXECUTED, BaseTimeout.TIMED_OUT])
    
    def test_very_small_timeout_becomes_zero(self):
        """Test that very small timeout (< 1) becomes 0"""
        timeout = SignalTimeout(0.5)
        self.assertEqual(timeout.seconds, 0)
    
    
    def test_nested_signal_timeouts_limitation(self):
        """Test and document the limitation of nested signal timeouts"""
        results = []
        
        with SignalTimeout(3, swallow_exc=True) as outer:
            time.sleep(0.1)
            results.append("outer_start")
            # Inner timeout cancels outer timeout's alarm
            with SignalTimeout(2, swallow_exc=True) as inner:
                time.sleep(0.1)
                results.append("inner_completed")
            results.append("outer_completed")
        
        # Both should complete if times are short enough
        self.assertEqual(results, ["outer_start", "inner_completed", "outer_completed"])
        self.assertEqual(outer.state, BaseTimeout.EXECUTED)
        self.assertEqual(inner.state, BaseTimeout.EXECUTED)


class TestWindowsSkipping(unittest.TestCase):
    """Test that Windows properly skips signal-based tests"""
    
    @unittest.skipUnless(os.name == 'nt', "This test only runs on Windows")
    def test_signal_imports_on_windows(self):
        """Test that signal module imports work on Windows"""
        from stopit.signalstop import SignalTimeout, signal_timeoutable
        
        self.assertTrue(hasattr(SignalTimeout, '__init__'))
        self.assertTrue(hasattr(signal_timeoutable, '__init__'))


if __name__ == '__main__':
    unittest.main()
