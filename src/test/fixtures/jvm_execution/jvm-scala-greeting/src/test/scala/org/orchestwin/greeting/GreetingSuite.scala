package org.orchestwin.greeting

class GreetingSuite extends munit.FunSuite:
  test("renders the provided name"):
    assertEquals(Greeting.forName("JVM"), "Hello, JVM!")
