package org.orchestwin.greeting

object Main:
  def main(args: Array[String]): Unit =
    println(Greeting.forName("JVM"))
