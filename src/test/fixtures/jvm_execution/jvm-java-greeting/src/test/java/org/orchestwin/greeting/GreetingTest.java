package org.orchestwin.greeting;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

final class GreetingTest {
    @Test
    void rendersTheProvidedName() {
        assertEquals("Hello, JVM!", Greeting.forName("JVM"));
    }
}
