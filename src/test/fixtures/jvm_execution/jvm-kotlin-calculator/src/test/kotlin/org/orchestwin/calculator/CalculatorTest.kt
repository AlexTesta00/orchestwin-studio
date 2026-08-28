package org.orchestwin.calculator

import kotlin.test.Test
import kotlin.test.assertEquals

class CalculatorTest {
    @Test
    fun addsTwoNumbers(): Unit {
        assertEquals(42, Calculator.add(20, 22))
    }

    @Test
    fun subtractsTwoNumbers(): Unit {
        assertEquals(17, Calculator.subtract(20, 3))
    }
}
