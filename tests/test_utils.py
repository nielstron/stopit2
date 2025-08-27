# -*- coding: utf-8 -*-
"""
Tests for stopit.utils module
"""

import unittest
import logging
from unittest.mock import patch

from stopit2.utils import TimeoutException, BaseTimeout, base_timeoutable, LOG


class TestTimeoutException(unittest.TestCase):
    """Test TimeoutException class"""
    
    def test_exception_creation(self):
        exc = TimeoutException("Test message")
        self.assertIsInstance(exc, Exception)
        self.assertEqual(str(exc), "Test message")


class TestBaseTimeout(unittest.TestCase):
    """Test BaseTimeout base class"""
    
    def setUp(self):
        # Create a concrete implementation for testing
        class ConcreteTimeout(BaseTimeout):
            def setup_interrupt(self):
                pass
            
            def suppress_interrupt(self):
                pass
        
        self.ConcreteTimeout = ConcreteTimeout
    
    def test_initialization(self):
        timeout = self.ConcreteTimeout(5.0)
        self.assertEqual(timeout.seconds, 5.0)
        self.assertTrue(timeout.swallow_exc)
        self.assertEqual(timeout.state, BaseTimeout.EXECUTED)
    
    def test_initialization_no_swallow(self):
        timeout = self.ConcreteTimeout(3.0, swallow_exc=False)
        self.assertEqual(timeout.seconds, 3.0)
        self.assertFalse(timeout.swallow_exc)
    
    def test_bool_conversion(self):
        timeout = self.ConcreteTimeout(1.0)
        
        # Test different states
        timeout.state = BaseTimeout.EXECUTED
        self.assertTrue(bool(timeout))
        
        timeout.state = BaseTimeout.EXECUTING
        self.assertTrue(bool(timeout))
        
        timeout.state = BaseTimeout.CANCELED
        self.assertTrue(bool(timeout))
        
        timeout.state = BaseTimeout.TIMED_OUT
        self.assertFalse(bool(timeout))
        
        timeout.state = BaseTimeout.INTERRUPTED
        self.assertFalse(bool(timeout))
    
    def test_repr(self):
        timeout = self.ConcreteTimeout(2.0)
        repr_str = repr(timeout)
        self.assertIn("ConcreteTimeout", repr_str)
        self.assertIn("state:", repr_str)
    
    def test_context_manager_normal_execution(self):
        timeout = self.ConcreteTimeout(5.0)
        
        with timeout as ctx:
            self.assertEqual(ctx.state, BaseTimeout.EXECUTING)
            self.assertIs(ctx, timeout)
        
        self.assertEqual(timeout.state, BaseTimeout.EXECUTED)
    
    
    def test_context_manager_with_timeout_exception_not_swallowed(self):
        timeout = self.ConcreteTimeout(1.0, swallow_exc=False)
        
        with self.assertRaises(TimeoutException):
            with timeout:
                raise TimeoutException("Test timeout")
        
        self.assertEqual(timeout.state, BaseTimeout.INTERRUPTED)
    
    def test_context_manager_with_other_exception(self):
        timeout = self.ConcreteTimeout(1.0)
        
        with self.assertRaises(ValueError):
            with timeout:
                raise ValueError("Other error")
        
        # State should remain EXECUTING since it wasn't a TimeoutException
        self.assertEqual(timeout.state, BaseTimeout.EXECUTING)
    
    def test_cancel(self):
        timeout = self.ConcreteTimeout(1.0)
        timeout.state = BaseTimeout.EXECUTING
        timeout.cancel()
        self.assertEqual(timeout.state, BaseTimeout.CANCELED)
    
    def test_setup_interrupt_not_implemented(self):
        timeout = BaseTimeout(1.0)
        with self.assertRaises(NotImplementedError):
            timeout.setup_interrupt()
    
    def test_suppress_interrupt_not_implemented(self):
        timeout = BaseTimeout(1.0)
        with self.assertRaises(NotImplementedError):
            timeout.suppress_interrupt()


class TestBaseTimeoutable(unittest.TestCase):
    """Test base_timeoutable decorator base class"""
    
    def setUp(self):
        # Create a concrete timeout context manager
        class MockTimeout(BaseTimeout):
            def setup_interrupt(self):
                pass
            def suppress_interrupt(self):
                pass
        
        # Create a concrete timeoutable decorator
        class ConcreteTimeoutable(base_timeoutable):
            to_ctx_mgr = MockTimeout
        
        self.ConcreteTimeoutable = ConcreteTimeoutable
        self.MockTimeout = MockTimeout
    
    def test_initialization_defaults(self):
        decorator = self.ConcreteTimeoutable()
        self.assertIsNone(decorator.default)
        self.assertEqual(decorator.timeout_param, 'timeout')
    
    def test_initialization_custom(self):
        decorator = self.ConcreteTimeoutable(default='failed', timeout_param='my_timeout')
        self.assertEqual(decorator.default, 'failed')
        self.assertEqual(decorator.timeout_param, 'my_timeout')
    
    def test_decorator_without_timeout(self):
        @self.ConcreteTimeoutable()
        def test_func(x):
            return x * 2
        
        result = test_func(5)
        self.assertEqual(result, 10)
    
    def test_decorator_with_timeout_no_timeout_occurred(self):
        @self.ConcreteTimeoutable(default='timeout_result')
        def test_func(x):
            return x * 2
        
        result = test_func(5, timeout=1.0)
        self.assertEqual(result, 10)
    
    def test_decorator_preserves_function_metadata(self):
        @self.ConcreteTimeoutable()
        def test_func(x):
            """Test function docstring"""
            return x
        
        self.assertEqual(test_func.__name__, 'test_func')
        self.assertEqual(test_func.__doc__, 'Test function docstring')
    
    def test_custom_timeout_parameter_name(self):
        @self.ConcreteTimeoutable(timeout_param='custom_timeout')
        def test_func(x):
            return x * 2
        
        # Should work with custom parameter name
        result = test_func(5, custom_timeout=1.0)
        self.assertEqual(result, 10)
        
        # Should work without timeout parameter
        result = test_func(5)
        self.assertEqual(result, 10)


class TestLogging(unittest.TestCase):
    """Test logging configuration"""
    
    def test_logger_exists(self):
        self.assertIsInstance(LOG, logging.Logger)
        self.assertEqual(LOG.name, 'stopit2')
    
    def test_logger_has_null_handler(self):
        # The logger should have at least one handler (NullHandler)
        self.assertTrue(len(LOG.handlers) > 0)


if __name__ == '__main__':
    unittest.main()
