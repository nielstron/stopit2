# -*- coding: utf-8 -*-
"""
Integration tests for stopit module
"""

import unittest
import time
import threading
import os

import stopit2 as stopit
from stopit2 import (
    ThreadingTimeout, SignalTimeout, 
    threading_timeoutable, signal_timeoutable,
    TimeoutException, async_raise
)


class TestModuleImports(unittest.TestCase):
    """Test that all public APIs are properly exported"""
    
    def test_all_exports_available(self):
        """Test that __all__ exports are available"""
        expected_exports = [
            'ThreadingTimeout', 'async_raise', 'threading_timeoutable',
            'SignalTimeout', 'signal_timeoutable'
        ]
        
        for export in expected_exports:
            self.assertTrue(hasattr(stopit, export))
    
    def test_version_available(self):
        """Test that version is available"""
        self.assertTrue(hasattr(stopit, '__version__'))
        self.assertIsInstance(stopit.__version__, str)
    
    def test_timeout_exception_available(self):
        """Test that TimeoutException is available"""
        self.assertTrue(hasattr(stopit, 'TimeoutException'))
        self.assertTrue(issubclass(stopit.TimeoutException, Exception))


class TestThreadingIntegration(unittest.TestCase):
    """Integration tests for threading-based timeout controls"""
    
    def test_context_manager_and_decorator_compatibility(self):
        """Test that context manager and decorator can work together"""
        results = []
        
        @threading_timeoutable(default='decorator_timeout')
        def slow_function():
            with ThreadingTimeout(1.0) as inner_timeout:
                time.sleep(0.1)
                results.append('inner_completed')
            return 'function_completed'
        
        result = slow_function(timeout=2.0)
        
        self.assertEqual(result, 'function_completed')
        self.assertEqual(results, ['inner_completed'])
    
    def test_nested_threading_timeouts(self):
        """Test nested threading timeouts work correctly"""
        results = []
        
        with ThreadingTimeout(2.0) as outer:
            time.sleep(0.1)
            results.append('outer_start')
            
            with ThreadingTimeout(1.0) as inner:
                time.sleep(0.1)
                results.append('inner_completed')
            
            results.append('outer_completed')
        
        self.assertEqual(results, ['outer_start', 'inner_completed', 'outer_completed'])
        self.assertEqual(outer.state, stopit.ThreadingTimeout.EXECUTED)
        self.assertEqual(inner.state, stopit.ThreadingTimeout.EXECUTED)
    
    def test_threading_timeout_with_real_work(self):
        """Test threading timeout with CPU-intensive work"""
        def cpu_intensive_work():
            # CPU-bound work that should be interruptible
            total = 0
            for i in range(1000000):
                total += i * i
            return total
        
        start_time = time.time()
        
        with ThreadingTimeout(0.5, swallow_exc=True) as timeout_ctx:
            cpu_intensive_work()
        
        elapsed = time.time() - start_time
        
        # Should timeout (though exact timing may vary due to GIL)
        self.assertLess(elapsed, 1.0)
        # State might be TIMED_OUT or EXECUTED depending on system performance
        self.assertIn(timeout_ctx.state, [
            ThreadingTimeout.TIMED_OUT, 
            ThreadingTimeout.EXECUTED
        ])
    
    def test_async_raise_integration(self):
        """Test async_raise with real thread coordination"""
        results = []
        thread_ready = threading.Event()
        thread_exception = threading.Event()
        
        def worker_thread():
            results.append('thread_started')
            thread_ready.set()
            
            time.sleep(2.0)  # Should be interrupted
            results.append('thread_completed')
        
        thread = threading.Thread(target=worker_thread)
        thread.start()
        
        # Wait for thread to be ready
        thread_ready.wait(timeout=1.0)
        
        # Interrupt the thread
        async_raise(thread.ident, LookupError)
        
        # Wait for thread to handle exception
        thread_exception.wait(timeout=1.0)
        thread.join(timeout=1.0)
        
        expected_results = ['thread_started']
        self.assertEqual(results, expected_results)


@unittest.skipIf(os.name == 'nt', "Signal-based tests don't work on Windows")
class TestSignalIntegration(unittest.TestCase):
    """Integration tests for signal-based timeout controls"""
    
    def test_signal_timeout_with_io_operations(self):
        """Test signal timeout with I/O operations"""
        results = []
        
        with SignalTimeout(1, swallow_exc=True) as timeout_ctx:
            time.sleep(0.1)  # Should complete
            results.append('io_completed')
        
        self.assertEqual(results, ['io_completed'])
        self.assertEqual(timeout_ctx.state, SignalTimeout.EXECUTED)
    
    def test_signal_decorator_with_recursive_function(self):
        """Test signal decorator with recursive function"""
        @signal_timeoutable(default='timeout')
        def fibonacci(n):
            if n <= 1:
                return n
            return fibonacci(n-1) + fibonacci(n-2)
        
        # Fast computation should work
        result = fibonacci(10, timeout=1)
        self.assertEqual(result, 55)  # 10th Fibonacci number
        
        # Slow computation should timeout
        start_time = time.time()
        result = fibonacci(40, timeout=1)  # This should timeout
        elapsed = time.time() - start_time
        
        self.assertEqual(result, 'timeout')
        self.assertLess(elapsed, 2.0)


class TestCompatibilityAndEdgeCases(unittest.TestCase):
    """Test compatibility and edge cases"""
    
    def test_timeout_accuracy_threading(self):
        """Test timeout accuracy for threading timeout with CPU-bound work"""
        def cpu_work(duration):
            start = time.time()
            while time.time() - start < duration:
                pass
        
        timeouts = []
        
        for expected_timeout in [0.5, 1.0]:
            start_time = time.time()
            
            with ThreadingTimeout(expected_timeout, swallow_exc=True):
                cpu_work(expected_timeout * 3)  # CPU work that can be interrupted
            
            actual_timeout = time.time() - start_time
            timeouts.append((expected_timeout, actual_timeout))
        
        # Check that actual timeouts are reasonably close to expected
        for expected, actual in timeouts:
            # Allow for variance due to system scheduling
            self.assertLess(actual, expected * 2.5)
            self.assertGreater(actual, expected * 0.3)
    
    @unittest.skipIf(os.name == 'nt', "Signal-based tests don't work on Windows")
    def test_timeout_accuracy_signal(self):
        """Test timeout accuracy for signal timeout"""
        timeouts = []
        
        for expected_timeout in [1, 2]:  # Signal timeout requires integers
            start_time = time.time()
            
            with SignalTimeout(expected_timeout, swallow_exc=True):
                time.sleep(expected_timeout * 2)  # Sleep longer than timeout
            
            actual_timeout = time.time() - start_time
            timeouts.append((expected_timeout, actual_timeout))
        
        # Signal timeouts should be more accurate than threading timeouts
        for expected, actual in timeouts:
            self.assertLess(actual, expected + 0.5)
            self.assertGreater(actual, expected - 0.5)
    
    def test_exception_handling_consistency(self):
        """Test that exception handling is consistent across timeout types"""
        
        # Test with threading timeout
        with self.assertRaises(ValueError):
            with ThreadingTimeout(1.0):
                raise ValueError("Threading test")
        
        # Test with signal timeout (skip on Windows)
        if os.name != 'nt':
            with self.assertRaises(ValueError):
                with SignalTimeout(1):
                    raise ValueError("Signal test")
    
    def test_boolean_evaluation_consistency(self):
        """Test that boolean evaluation is consistent"""
        
        # Threading timeout - successful execution
        with ThreadingTimeout(1.0) as threading_ctx:
            time.sleep(0.1)
        self.assertTrue(bool(threading_ctx))
        
        # Threading timeout - timeout occurred
        with ThreadingTimeout(0.1, swallow_exc=True) as threading_ctx:
            time.sleep(0.5)
        self.assertFalse(bool(threading_ctx))
        
        # Signal timeout - successful execution (skip on Windows)
        if os.name != 'nt':
            with SignalTimeout(1) as signal_ctx:
                time.sleep(0.1)
            self.assertTrue(bool(signal_ctx))
    
    def test_multiple_consecutive_timeouts(self):
        """Test multiple consecutive timeout operations"""
        results = []
        
        # Multiple threading timeouts
        for i in range(3):
            with ThreadingTimeout(0.5, swallow_exc=True) as ctx:
                time.sleep(0.1)
                results.append(f'threading_{i}')
            
            self.assertEqual(ctx.state, ThreadingTimeout.EXECUTED)
        
        # Multiple signal timeouts (skip on Windows)
        if os.name != 'nt':
            for i in range(3):
                with SignalTimeout(1, swallow_exc=True) as ctx:
                    time.sleep(0.1)
                    results.append(f'signal_{i}')
                
                self.assertEqual(ctx.state, SignalTimeout.EXECUTED)
        
        expected_results = ['threading_0', 'threading_1', 'threading_2']
        if os.name != 'nt':
            expected_results.extend(['signal_0', 'signal_1', 'signal_2'])
        
        self.assertEqual(results, expected_results)


class TestRealWorldUseCases(unittest.TestCase):
    """Test real-world use cases"""
    
    def test_database_connection_simulation(self):
        """Simulate database connection with timeout"""
        
        @threading_timeoutable(default=None)
        def connect_to_database(host, timeout_duration):
            # Simulate connection attempt
            time.sleep(timeout_duration)
            return f"Connected to {host}"
        
        # Fast connection should work
        result = connect_to_database("localhost", 0.1, timeout=1.0)
        self.assertEqual(result, "Connected to localhost")
        
        # Slow connection should timeout
        result = connect_to_database("remote.server", 2.0, timeout=0.5)
        self.assertIsNone(result)
    
    def test_file_processing_with_timeout(self):
        """Simulate file processing with timeout"""
        
        def process_large_file():
            """Simulate processing a large file"""
            processed_items = 0
            
            with ThreadingTimeout(1.0, swallow_exc=True) as timeout_ctx:
                for i in range(1000000):  # Large number of items
                    processed_items += 1
                    # Simulate some processing time
                    if i % 10000 == 0:
                        time.sleep(0.001)
            
            return processed_items, timeout_ctx.state
        
        processed_items, final_state = process_large_file()
        
        # Should have processed some items
        self.assertGreater(processed_items, 0)
        # Might have completed or timed out depending on system performance
        self.assertIn(final_state, [
            ThreadingTimeout.EXECUTED,
            ThreadingTimeout.TIMED_OUT
        ])
    
    def test_api_request_timeout_simulation(self):
        """Simulate API request with timeout"""
        
        class MockAPIClient:
            @threading_timeoutable(default={'error': 'timeout'})
            def make_request(self, endpoint, delay=0):
                time.sleep(delay)
                return {'data': f'Response from {endpoint}'}
        
        client = MockAPIClient()
        
        # Fast request should work
        response = client.make_request('/users', delay=0.1, timeout=1.0)
        self.assertEqual(response, {'data': 'Response from /users'})
        
        # Slow request should timeout
        response = client.make_request('/slow-endpoint', delay=2.0, timeout=0.5)
        self.assertEqual(response, {'error': 'timeout'})


if __name__ == '__main__':
    unittest.main()
