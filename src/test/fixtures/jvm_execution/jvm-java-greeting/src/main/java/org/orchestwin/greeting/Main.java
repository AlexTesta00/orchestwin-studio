package org.orchestwin.greeting;

public final class Main {
    private Main() {}

    public static void main(String[] args) {
        System.out.println(Greeting.forName("JVM"));
    }
}
